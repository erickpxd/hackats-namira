import hashlib
import json
import unittest
from unittest.mock import Mock, patch
from threading import Event
from pentest_pipeline.execution.container_manager import DockerContainerManager, ContainerCancelled
from pentest_pipeline.orchestration.execution_history import execution_history
from pentest_pipeline.orchestration.event_store import EventStore
from pentest_pipeline.execution.laboratory_operations import compare_local_results, verify_integrity, correlate_local_version


class HistoryTests(unittest.TestCase):
    def test_docker_cancel_kills_client_and_removes_own_container(self):
        stop = Event()
        stop.set()
        process = Mock()
        process.poll.return_value = None
        process.communicate.return_value = (b"", b"")
        with patch("pentest_pipeline.execution.container_manager.subprocess.Popen", return_value=process), patch(
            "pentest_pipeline.execution.container_manager.subprocess.run") as cleanup:
            cleanup.return_value.returncode = 0
            with self.assertRaises(ContainerCancelled):
                DockerContainerManager(stop_event=stop)._subprocess_runner(["docker", "run", "image"], b"{}", 30)
            process.kill.assert_called_once()
            self.assertEqual(cleanup.call_args.args[0][:3], ["docker", "rm", "-f"])
            self.assertTrue(cleanup.call_args.args[0][3].startswith("namira-worker-"))

    def test_planned_is_not_executed(self):
        row = execution_history([{"type": "task_planned", "task_id": "t"}])[0]
        self.assertEqual(row["execution_status"], "planned")
        self.assertIsNone(row["started_at"])

    def test_success_not_confirmation(self):
        store = EventStore("campaign")
        store.append({"type": "task_started", "task_id": "t", "timestamp": "start"})
        store.append({"type": "task_completed", "task_id": "t", "state": "completed", "timestamp": "end"})
        row = execution_history(store.all())[0]
        self.assertEqual(row["execution_status"], "completed")
        self.assertEqual(row["validation_status"], "inconclusive")

    def test_worker_failure_persists_identity(self):
        store = EventStore("campaign")
        store.append({"type": "validation_failed", "task_id": "t", "validation_id": "v",
                      "hypothesis_id": "h", "status": "failed", "isolation_level": "container"})
        row = execution_history(store.all())[0]
        self.assertEqual((row["hypothesis_id"], row["execution_status"]), ("h", "failed"))
        self.assertEqual(row["evidence_refs"], [])

    def test_contradiction_and_incomplete(self):
        self.assertEqual(compare_local_results({"observed": 2, "expected": 1})["validation_status"], "contradicted")
        self.assertEqual(compare_local_results({})["validation_status"], "inconclusive")
        self.assertEqual(compare_local_results({"expected": None, "observed": None})["validation_status"], "inconclusive")

    def test_integrity(self):
        evidence = {"value": 3}
        digest = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(verify_integrity({"evidence": evidence, "sha256": digest})["validation_status"], "supported")
        self.assertEqual(verify_integrity({"evidence": {}, "sha256": digest})["validation_status"], "contradicted")

    def test_version_boundaries(self):
        data = {"component": {"component_id": "c", "name": "demo", "normalized_name": "demo",
                "version": "1.0", "version_confidence": "exact", "ecosystem": "npm"},
                "record": {"vulnerability_id": "fixture", "source": "fixture",
                "affected": [{"product": "demo", "ecosystem": "npm", "introduced": "1.0", "fixed": "2.0"}]}}
        self.assertEqual(correlate_local_version(data)["validation_status"], "supported")
        data["component"]["version"] = "2.0"
        self.assertEqual(correlate_local_version(data)["validation_status"], "contradicted")
        data["record"]["affected"][0]["introduced"] = "3.0"
        self.assertEqual(correlate_local_version(data)["validation_status"], "inconclusive")
