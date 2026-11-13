"""Phase 6.5 acceptance: fixture transport and recorded, deterministic workers only."""
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch
import subprocess

from pentest_pipeline.execution.container_manager import (
    ContainerError, ContainerCancelled, ContainerCleanupError, DockerContainerManager,
    InProcessContainerManager)
from pentest_pipeline.execution.laboratory import LaboratoryManager, LaboratoryValidationRequest
from pentest_pipeline.execution.policy import PolicyEngine
from pentest_pipeline.execution.config import ContainerExecutionMode
from pentest_pipeline.execution.worker_protocol import WorkerResponse
from pentest_pipeline.execution.workers import validate_result_structure
from pentest_pipeline.orchestration.orchestrator import OrchestratorV2
from pentest_pipeline.orchestration.execution_history import execution_history, hypothesis_history, evidence_history
from pentest_pipeline.persistence import CheckpointStore, plan_recovery
from test_orchestrator_v2_integration import FakeTransport, _cfg, _responses, resp


class FixtureResearch:
    def research(self, components):
        return {"coverage": "complete", "providers_ok": ["fixture"], "providers_failed": [],
                "failures": [], "records": {c.component_id: [{
                    "vulnerability_id": "CVE-2099-0001", "source": "fixture",
                    "affected": [{"product": c.normalized_name, "ecosystem": c.ecosystem,
                                  "introduced": "13.0.0", "fixed": "15.0.0"}]}] for c in components}}


def fixture_transport(config, **kw):
    responses = _responses(config)
    responses[("GET", "/")] = resp(config.target_url, 200, b'<html ng-version="14.0.0">Fixture</html>')
    return FakeTransport(config, responses=responses, **kw)


class Phase65IntegrationTests(unittest.TestCase):
    def campaign(self, manager, store=None, stop=None):
        with patch.dict(os.environ, {"PENTEST_LABORATORY": "enabled"}), patch(
            "pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=fixture_transport), patch(
            "pentest_pipeline.orchestration.executors_laboratory.DockerContainerManager", return_value=manager):
            return OrchestratorV2(cve_intelligence=True, cve_service=FixtureResearch(),
                                  checkpoint_store=store).run(_cfg(), stop_event=stop)

    def test_hypothesis_worker_evidence_chain_and_intermediate_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CheckpointStore(directory)
            saves = []
            original = store.save
            def capture(*args, **kwargs):
                saves.append(kwargs)
                return original(*args, **kwargs)
            with patch.object(store, "save", side_effect=capture):
                result = self.campaign(InProcessContainerManager(), store)
            payload = result.to_dict()
            rows = execution_history(payload["execution_events"], payload)
            validation = next(e for e in rows if e["hypothesis_id"])
            self.assertEqual(validation["execution_status"], "completed")
            self.assertEqual(validation["validation_status"], "supported")
            self.assertEqual(validation["execution_backend"], "simulated")
            self.assertEqual(validation["agent_id"], "laboratory_validation")
            self.assertIsInstance(validation["duration_ms"], int)
            h = hypothesis_history(payload)[0]
            self.assertEqual(h["hypothesis_id"], validation["hypothesis_id"])
            self.assertEqual(h["version"], "14.0.0")
            self.assertEqual(h["correlation_status"], "potentially_affected")
            self.assertTrue(set(h["evidence_refs"]).issubset(validation["evidence_refs"]))
            self.assertTrue(validation["output_evidence_refs"])
            self.assertTrue(validation["worker_responded"])
            self.assertEqual(validation["authorization_status"], "approved")
            self.assertTrue(evidence_history(payload, payload["execution_events"]))
            self.assertFalse(any("CVE-2099-0001" in f.title for f in result.findings))
            middle = next(s for s in saves if any(e["event_type"] == "validation_started"
                          for e in s["execution_events"]) and s["task_states"].get("laboratory_validation") == "running")
            recovery = plan_recovery(middle)
            self.assertIn("laboratory_validation", recovery.needs_manual_review)
            loaded = store.load(result.run_id)
            self.assertEqual(loaded["task_states"]["laboratory_validation"], "completed")
            self.assertTrue(any(e["event_type"] == "validation_completed" for e in loaded["execution_events"]))

    def test_runtime_failure_keeps_hypothesis_without_validation(self):
        manager = Mock(isolation_level="container")
        manager.available.return_value = True
        manager.run.side_effect = ContainerError("exec denied")
        manager.cleanup_status = "completed"
        result = self.campaign(manager).to_dict()
        row = next(e for e in execution_history(result["execution_events"], result) if e["hypothesis_id"])
        self.assertEqual((row["execution_status"], row["validation_status"]), ("failed", "not_evaluated"))
        validation = next(o for o in result["observations"] if o["type"] == "laboratory_validation")
        self.assertEqual(validation["supporting_evidence"], ())
        self.assertTrue(hypothesis_history(result))

    def test_cancel_after_dispatch_is_terminal_and_checkpoint_preserved(self):
        stop = Event()
        manager = InProcessContainerManager()
        original = manager.run
        def cancel(request, config):
            response = original(request, config)
            stop.set()
            return response
        with patch.object(manager, "run", side_effect=cancel):
            result = self.campaign(manager, stop=stop).to_dict()
        row = next(e for e in execution_history(result["execution_events"], result) if e["hypothesis_id"])
        self.assertEqual(row["execution_status"], "cancelled")
        self.assertEqual(row["validation_status"], "not_evaluated")
        self.assertFalse(any(e["execution_status"] == "running" for e in execution_history(result["execution_events"], result)))


class LaboratoryFailureTests(unittest.TestCase):
    def run_lab(self, manager):
        events = []
        request = LaboratoryValidationRequest("v", "c", "h", "inventory", "normalize_technology_inventory", ("e",))
        result = LaboratoryManager(manager, PolicyEngine(mode=ContainerExecutionMode.ENABLED,
            container_eligible_types=frozenset({"laboratory_validation"}))).validate(request, hypotheses=[{
                "hypothesis_id": "h", "campaign_id": "c", "evidence_refs": ["e"]}],
                task_id="t", emit=events.append)
        return result, execution_history(events)[0]

    def test_unavailable_runtime_is_recorded_without_start(self):
        manager = Mock(isolation_level="container", cleanup_status="not_started")
        manager.available.return_value = False
        result, row = self.run_lab(manager)
        self.assertEqual(result.status, "failed")
        self.assertIsNone(row["started_at"])
        manager.run.assert_not_called()

    def test_wrong_response_identity_cannot_support_a_hypothesis(self):
        manager = Mock(isolation_level="none", cleanup_status="not_applicable")
        manager.run.return_value = WorkerResponse("different", "completed", {"validation_status": "supported"})
        result, row = self.run_lab(manager)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.supporting_evidence, ())
        self.assertEqual(row["validation_status"], "not_evaluated")

    def test_unknown_evidence_is_invalid_even_with_empty_catalog(self):
        self.assertEqual(validate_result_structure({"findings": [{"id": "f", "severity": "low",
                         "evidence_ref": "missing"}]})["validation_status"], "contradicted")

    def test_cancel_during_communicate_and_cleanup_failure_are_distinct(self):
        for cleanup_code in (0, 1):
            with self.subTest(cleanup_code=cleanup_code):
                stop = Event()
                proc = Mock()
                proc.poll.return_value = None
                def communicate(*args, **kwargs):
                    if "timeout" in kwargs:
                        stop.set()
                        raise subprocess.TimeoutExpired("docker", .1)
                    return (b"", b"")
                proc.communicate.side_effect = communicate
                cleanup = subprocess.CompletedProcess([], cleanup_code, b"", b"daemon unreachable")
                manager = DockerContainerManager(stop_event=stop)
                with patch("subprocess.Popen", return_value=proc), patch("subprocess.run", return_value=cleanup):
                    with self.assertRaises(ContainerCancelled if cleanup_code == 0 else ContainerCleanupError):
                        manager._subprocess_runner(["docker", "run", "image"], b"{}", 30)
                self.assertEqual(manager.cleanup_status, "completed" if cleanup_code == 0 else "failed")


if __name__ == "__main__":
    unittest.main()
