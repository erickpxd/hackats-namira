from dataclasses import replace
from threading import Event
from unittest import TestCase
from unittest.mock import Mock
import hashlib
import json
from pentest_pipeline.contracts import TaskDefinition
from pentest_pipeline.execution.laboratory import LaboratoryManager, LaboratoryValidationRequest
from pentest_pipeline.execution.container_manager import InProcessContainerManager, ContainerTimeout
from pentest_pipeline.orchestration.execution_history import execution_history
from pentest_pipeline.execution.policy import PolicyEngine
from pentest_pipeline.execution.config import ContainerExecutionMode


class LaboratoryTests(TestCase):
    def setUp(self):
        self.manager = LaboratoryManager(InProcessContainerManager(), PolicyEngine(
            mode=ContainerExecutionMode.ENABLED, container_eligible_types=frozenset({"laboratory_validation"})))
        self.request = LaboratoryValidationRequest("v1", "c1", "h1", "inventory",
            "normalize_technology_inventory", ("e1",), {"framework": {}})
        self.hypotheses = [{"hypothesis_id": "h1", "campaign_id": "c1", "evidence_refs": ["e1"]}]
        self.events = []

    def run_lab(self, request=None, **kw):
        return self.manager.validate(request or self.request, hypotheses=self.hypotheses,
                                     emit=self.events.append, task_id="t1", **kw)

    def test_result_and_real_isolation_label(self):
        result = self.run_lab()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.isolation_level, "none")
        self.assertFalse(result.supporting_evidence)
        self.assertEqual(self.events[-1]["type"], "validation_completed")

    def test_unknown_lab_and_operation(self):
        for key in ("laboratory_id", "operation_id", "hypothesis_id", "campaign_id"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_lab(replace(self.request, **{key: "unknown"}))

    def test_unknown_evidence(self):
        with self.assertRaises(ValueError):
            self.run_lab(replace(self.request, evidence_refs=("missing",)))

    def test_missing_evidence_inconclusive(self):
        result = self.run_lab(replace(self.request, evidence_refs=()))
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.validation_status, "not_evaluated")
        self.assertFalse(any(e["type"] == "validation_started" for e in self.events))

    def test_cancelled(self):
        stop = Event()
        stop.set()
        self.assertEqual(self.run_lab(stop_event=stop).status, "cancelled")

    def test_excess_limit(self):
        with self.assertRaises(ValueError):
            self.run_lab(replace(self.request, execution_limits={"timeout_seconds": 900}))

    def test_policy_denial_never_dispatches_worker(self):
        runtime = Mock(isolation_level="container", cleanup_status="not_started")
        self.manager.manager = runtime
        task = TaskDefinition("t1", "laboratory_validation", "laboratory_validation", requires_approval=True)
        result = self.run_lab(task=task)
        runtime.run.assert_not_called()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.validation_status, "not_evaluated")
        self.assertTrue(any(e.get("authorization_status") == "denied" for e in self.events))

    def test_timeout_preserves_no_security_conclusion(self):
        runtime = Mock(isolation_level="container", cleanup_status="completed")
        runtime.run.side_effect = ContainerTimeout("fixture timeout")
        self.manager.manager = runtime
        result = self.run_lab()
        self.assertEqual((result.status, result.error_code, result.validation_status), ("failed", "timeout", "not_evaluated"))
        self.assertFalse(result.worker_responded)
        self.assertEqual(result.output_evidence_refs, ())

    def test_attempt_ids_and_output_evidence_are_verifiable_and_safe(self):
        request = replace(self.request, input_data={"framework": {}, "password": "do-not-persist", "raw_body": "do-not-persist"})
        first, second = self.run_lab(request), self.run_lab(request)
        self.assertNotEqual(first.execution_id, second.execution_id)
        self.assertEqual(len(execution_history(self.events)), 2)
        for result in (first, second):
            self.assertEqual((result.campaign_id, result.task_id, result.hypothesis_id), ("c1", "t1", "h1"))
            evidence = next(e["evidence"] for e in self.events if e.get("evidence", {}).get("execution_id") == result.execution_id)
            body = {k: v for k, v in evidence.items() if k != "sha256"}
            self.assertEqual(evidence["sha256"], hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode()).hexdigest())
            self.assertIn(evidence["evidence_id"], result.output_evidence_refs)
        self.assertNotIn("do-not-persist", json.dumps(self.events))
