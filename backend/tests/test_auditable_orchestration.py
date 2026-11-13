"""Regressions for the observed partial campaign and verifiable capture."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pentest_pipeline.orchestration.assessment import summarize
from pentest_pipeline.orchestration.projection import project
from pentest_pipeline.orchestration.event_store import EventStore
from pentest_pipeline.orchestration.orchestrator import OrchestratorV2, build_registry
from pentest_pipeline.orchestration.executors_intelligence import _include_framework_records
from pentest_pipeline.intelligence.cve_research import CveResearchService, default_research_service
from pentest_pipeline.intelligence.cache import TTLCache
from pentest_pipeline.intelligence.correlation import CveCorrelationEngine
from pentest_pipeline.contracts import TaskResult, TechnologyComponent, AffectedRange, CveRecord, TaskDefinition
from pentest_pipeline.execution.capture import sanitize, persist, read, digest
from pentest_pipeline.execution.policy import PolicyEngine, PolicyError
from pentest_pipeline.execution.config import ContainerExecutionMode
from pentest_pipeline.execution.worker_protocol import WorkerRequest
from pentest_pipeline.execution.demo_operations import inspect_demo_environment, correlate_fixture_version
from pentest_pipeline.demo.fixtures import cases, pair
from pentest_pipeline.scope import ScopeConfig
from test_orchestrator_v2_integration import _mk


class AssessmentTests(unittest.TestCase):
    def test_mixed_success_never_hides_inconclusive(self):
        events = [{"event_type": "task_completed", "task_id": "target_analysis", "task_type": "target_analysis", "status": "completed"},
                  {"event_type": "task_inconclusive", "task_id": "cve_research", "task_type": "cve_research", "status": "inconclusive"},
                  {"event_type": "task_completed", "task_id": "cve_correlation", "task_type": "cve_correlation", "state": "skipped"}]
        out = project(events, campaign_state="completed")
        self.assertEqual((out["execution_status"], out["assessment_status"]), ("completed", "partial"))
        macro = next(m for m in out["macrophases"] if m["id"] == "multiagent")
        self.assertEqual(macro["assessment_status"], "partial")
        self.assertNotEqual(macro["status"], "completed")
        self.assertEqual(out["progress"]["finished_tasks"], 3)
        self.assertEqual(out["progress"]["completed_tasks"], 1)

    def test_optional_noop_does_not_become_mandatory(self):
        events = [{"type": "task_completed", "task_id": "ai_advisor", "state": "skipped",
                   "reason_code": "no_advisor_or_findings"}]
        self.assertEqual(summarize(events, "completed")["assessment_status"], "complete")

    def test_planned_tasks_count_before_dispatch(self):
        out = project([{"type": "task_planned", "task_id": "cve_research", "task_type": "cve_research"}])
        self.assertEqual(out["progress"]["total_tasks"], 1)
        self.assertEqual(out["progress"]["global_estimate"], 0)

    def test_skips_keep_structured_reason_and_dependencies(self):
        store = EventStore("c")
        store.append({"type": "task_planned", "task_id": "lab", "task_type": "laboratory_validation",
                      "depends_on": ["registration"], "optional": True})
        store.append({"type": "task_completed", "task_id": "lab", "task_type": "laboratory_validation", "state": "skipped",
                      "reason_code": "no_eligible_hypotheses", "output_summary": {"skip_reasons": {"identity_missing": 1}}})
        macro = next(m for m in project(store.all())["macrophases"] if m["id"] == "multiagent")
        row = macro["tasks"][0]
        self.assertEqual(row["depends_on"], ["registration"])
        self.assertIn("critérios", row["reason"])
        self.assertEqual(row["output_summary"]["skip_reasons"]["identity_missing"], 1)

    def test_mismatched_result_fails_and_blocks_dependents_with_cause(self):
        registry = build_registry()
        executor = registry.get("target_analysis")
        with patch.object(executor, "execute", return_value=TaskResult("wrong-id", "completed")), \
             patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            result = OrchestratorV2(registry=registry).run(ScopeConfig.for_target_url("https://example.com/"))
        events = result.execution_events
        self.assertTrue(any(e["event_type"] == "task_failed" and e["task_id"] == "target_analysis" for e in events))
        blocked = next(e for e in events if e["event_type"] == "task_cancelled" and e["task_id"] == "ai_target_review")
        self.assertEqual(blocked["reason_code"], "dependency_failed")
        self.assertIn("target_analysis", blocked["output_summary"]["blocked_by"])
        self.assertEqual(result.to_dict()["assessment_status"], "partial")


class IntelligenceHandoffTests(unittest.TestCase):
    def test_local_advisory_uses_shared_criteria_and_product_identity(self):
        from pentest_pipeline.frameworks import inspect_angular
        from pentest_pipeline.orchestration.executors_intelligence import _record_from_dict
        from types import SimpleNamespace
        component = TechnologyComponent("tech:@angular/core", "Angular", "@angular/core", "npm", version="22.2.2", version_confidence="exact")
        advisory = {"id": "LOCAL-TEST", "package": "@angular/upgrade", "affected": [
            {"product": "@angular/upgrade", "ecosystem": "npm", "introduced": "22.0.0", "fixed": "22.2.4"}]}
        context = SimpleNamespace(get=lambda _: {"advisories_for_review": [advisory]})
        out = _include_framework_records({"records": {}, "coverage": "partial"}, context, [component])
        record = _record_from_dict(out["records"][component.component_id][0])
        self.assertTrue(record.affected)
        self.assertEqual(CveCorrelationEngine().correlate(component, record).status, "inconclusive")
        self.assertEqual(out["coverage"], "partial")

    def test_empty_supplied_cache_is_retained_and_zero_results_are_cacheable(self):
        cache = TTLCache()
        service = default_research_service(fetch=lambda *a, **k: {}, cache=cache)
        self.assertIs(service.cache, cache)
        class Provider:
            name = "local-test"
            calls = 0
            def query(self, component):
                self.calls += 1
                return []
        provider = Provider()
        service = CveResearchService([provider], cache=cache)
        component = pair(cases()[0])[0]
        service.research([component])
        self.assertEqual(service.research([component])["cache_hits"][0]["provider"], provider.name)
        self.assertEqual(provider.calls, 1)

    def test_no_providers_is_not_full_coverage(self):
        self.assertEqual(CveResearchService([]).research([pair(cases()[0])[0]])["coverage"], "none")


class CaptureTests(unittest.TestCase):
    def test_redaction_controls_encoding_and_bound(self):
        raw = b'\x1b[31m{"password": "two secret words", "token":"abc123"} Bearer abc.def\x00\xff'
        out = sanitize(raw)
        for secret in ("two secret words", "abc123", "abc.def", "\x1b", "\x00"):
            self.assertNotIn(secret, out)
        self.assertIn("[REDACTED]", out)
        self.assertLessEqual(len(sanitize(b"x" * 50000)), 8192)

    def test_separate_streams_integrity_tamper_and_retention(self):
        metadata = {"execution_id": "exec-" + "a" * 32, "worker_id": "worker1", "exit_code": 0}
        with tempfile.TemporaryDirectory() as directory:
            meta = persist(metadata, b"real stdout", b"real stderr", root=directory)
            self.assertNotIn("stdout_excerpt", meta)
            self.assertEqual(read(meta, root=directory)["stderr_excerpt"], "real stderr")
            path = Path(directory) / (metadata["execution_id"] + ".json")
            item = json.loads(path.read_text()); item["stdout_excerpt"] = "tampered"; path.write_text(json.dumps(item))
            self.assertFalse(read(meta, root=directory)["capture_available"])
        with tempfile.TemporaryDirectory() as directory:
            meta = persist(metadata, b"discard", b"", root=directory, retention_days=0)
            self.assertFalse(read(meta, root=directory)["capture_available"])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_invalid_capture_path_rejected(self):
        with self.assertRaises(ValueError):
            persist({"execution_id": "../../outside"}, b"", b"")


class DemoControlTests(unittest.TestCase):
    def test_unknown_operation_rejected_before_dispatch(self):
        policy = PolicyEngine(mode=ContainerExecutionMode.ENABLED, container_eligible_types=frozenset({"unknown"}))
        with self.assertRaises(PolicyError):
            policy.authorize_operation(TaskDefinition("unknown", "unknown", "unknown"), build_registry(), "unknown")

    def test_diagnostic_rejects_commands_and_paths(self):
        for data in ({"command": "id"}, {"path": "/etc/shadow"}, {"args": []}):
            with self.assertRaises(ValueError):
                inspect_demo_environment(data)

    def test_fixture_comparison_reads_local_case_and_keeps_missing_version(self):
        for case, verdict in zip(cases(), ("supported", "contradicted", "inconclusive")):
            component, record = pair(case)
            output = correlate_fixture_version({"fixture_id": case["component_id"], "component": component.to_dict(), "record": record.to_dict()})
            self.assertEqual(output["validation_status"], verdict)
            if verdict == "inconclusive":
                self.assertIsNone(component.version)

    def test_fixture_comparison_rejects_substitution(self):
        case = cases()[0]; component, record = pair(case)
        with self.assertRaises(ValueError):
            correlate_fixture_version({"fixture_id": case["component_id"], "component": {**component.to_dict(), "version": "9.0.0"}, "record": record.to_dict()})
