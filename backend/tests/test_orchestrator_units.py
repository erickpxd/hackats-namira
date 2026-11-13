"""Testes unitários dos componentes do OrchestratorV2 (Fase 2)."""

from __future__ import annotations

import threading
import time
import unittest

from pentest_pipeline.contracts import ExecutionPlan, TaskDefinition, TaskResult
from pentest_pipeline.models import ScanResult
from pentest_pipeline.contracts import CampaignContext
from pentest_pipeline.scope import ScopeConfig
from pentest_pipeline.orchestration import state_machine as sm
from pentest_pipeline.orchestration.context import ExecutionContext
from pentest_pipeline.orchestration.scheduler import SchedulerFatal, TaskScheduler
from pentest_pipeline.orchestration.task_registry import RegistryError, TaskRegistry
from pentest_pipeline.persistence import (CheckpointError, CheckpointStore, plan_recovery)


# ------------------------- State machine ---------------------------------- #
class StateMachineTests(unittest.TestCase):
    def test_valid_task_path(self) -> None:
        m = sm.task_machine()
        for target in (sm.TASK_READY, sm.TASK_RUNNING, sm.TASK_COMPLETED):
            m.transition(target)
        self.assertTrue(m.is_terminal)
        self.assertEqual([h["to"] for h in m.history][-1], sm.TASK_COMPLETED)

    def test_invalid_task_transition_rejected(self) -> None:
        m = sm.task_machine()
        with self.assertRaises(sm.TransitionError):
            m.transition(sm.TASK_COMPLETED)  # pending -> completed proibido

    def test_terminal_is_frozen(self) -> None:
        m = sm.task_machine(sm.TASK_COMPLETED)
        with self.assertRaises(sm.TransitionError):
            m.transition(sm.TASK_RUNNING)

    def test_unknown_state_rejected(self) -> None:
        m = sm.task_machine()
        with self.assertRaises(sm.TransitionError):
            m.transition("teleported")

    def test_campaign_path_and_invalid(self) -> None:
        c = sm.campaign_machine()
        c.transition(sm.CAMPAIGN_PLANNING)
        c.transition(sm.CAMPAIGN_RUNNING)
        c.transition(sm.CAMPAIGN_COMPLETED)
        self.assertTrue(c.is_terminal)
        with self.assertRaises(sm.TransitionError):
            sm.campaign_machine().transition(sm.CAMPAIGN_RUNNING)  # created -> running proibido


# ------------------------- Registry --------------------------------------- #
class _Exec:
    def __init__(self, task_type, requires_approval=False, result_state="completed",
                 fail=False, sink=None):
        self.task_type = task_type
        self.requires_approval = requires_approval
        self._state = result_state
        self._fail = fail
        self._sink = sink

    def execute(self, task, context):
        if self._sink is not None:
            self._sink.append(task.task_id)
        if self._fail:
            raise RuntimeError("boom")
        return TaskResult(task_id=task.task_id, state=self._state)


class RegistryTests(unittest.TestCase):
    def test_register_get_and_unknown(self) -> None:
        reg = TaskRegistry()
        reg.register(_Exec("scope"))
        self.assertTrue(reg.has("scope"))
        self.assertEqual(reg.get("scope").task_type, "scope")
        with self.assertRaises(RegistryError):
            reg.get("ghost")

    def test_duplicate_and_bad_executor_rejected(self) -> None:
        reg = TaskRegistry()
        reg.register(_Exec("scope"))
        with self.assertRaises(RegistryError):
            reg.register(_Exec("scope"))
        with self.assertRaises(RegistryError):
            reg.register(_Exec(""))

    def test_validate_plan_types_blocks_unknown(self) -> None:
        reg = TaskRegistry()
        reg.register(_Exec("scope"))
        with self.assertRaises(RegistryError):
            reg.validate_plan_types(["scope", "exploit"])

    def test_requires_approval_metadata(self) -> None:
        reg = TaskRegistry()
        reg.register(_Exec("approve_me", requires_approval=True))
        self.assertTrue(reg.requires_approval("approve_me"))


# ------------------------- Scheduler -------------------------------------- #
def _ctx() -> ExecutionContext:
    scope = ScopeConfig(target_url="https://example.com/", allowed_hosts=("example.com",))
    campaign = CampaignContext("c1", "corr1", scope)
    result = ScanResult(run_id="c1", target="https://example.com/", campaign_name="t",
                        started_at="now")
    return ExecutionContext(campaign=campaign, transport=None, result=result)


def _task(tid, deps=(), ttype=None):
    return TaskDefinition(task_id=tid, task_type=ttype or tid, executor=tid, depends_on=deps)


class SchedulerTests(unittest.TestCase):
    def test_linear_dependencies_execute_in_order(self) -> None:
        order: list[str] = []
        reg = TaskRegistry()
        for name in ("a", "b", "c"):
            reg.register(_Exec(name, sink=order))
        plan = ExecutionPlan("p", 1, tasks=(_task("a"), _task("b", ("a",)), _task("c", ("b",))))
        report = TaskScheduler(reg).run(plan, _ctx())
        self.assertEqual(order, ["a", "b", "c"])
        self.assertTrue(all(s == "completed" for s in report.states.values()))

    def test_independent_tasks_run_in_parallel(self) -> None:
        active = {"n": 0, "max": 0}
        lock = threading.Lock()

        class Slow:
            task_type = "x"
            requires_approval = False

            def __init__(self, tid):
                self.task_type = tid

            def execute(self, task, context):
                with lock:
                    active["n"] += 1
                    active["max"] = max(active["max"], active["n"])
                time.sleep(0.05)
                with lock:
                    active["n"] -= 1
                return TaskResult(task_id=task.task_id, state="completed")

        reg = TaskRegistry()
        for name in ("a", "b", "c"):
            reg.register(Slow(name))
        plan = ExecutionPlan("p", 1, tasks=(_task("a"), _task("b"), _task("c")))
        TaskScheduler(reg, max_concurrency=3).run(plan, _ctx())
        self.assertGreaterEqual(active["max"], 2)  # houve paralelismo real

    def test_dependency_failure_cancels_dependents(self) -> None:
        reg = TaskRegistry()
        reg.register(_Exec("a", fail=True))     # não crítica -> falha isolada
        reg.register(_Exec("b"))
        plan = ExecutionPlan("p", 1, tasks=(_task("a"), _task("b", ("a",))))
        report = TaskScheduler(reg).run(plan, _ctx())
        self.assertEqual(report.states["a"], "failed")
        self.assertEqual(report.states["b"], "cancelled")

    def test_critical_failure_is_fatal(self) -> None:
        reg = TaskRegistry()
        reg.register(_Exec("a", fail=True))
        plan = ExecutionPlan("p", 1, tasks=(_task("a"),))
        with self.assertRaises(SchedulerFatal):
            TaskScheduler(reg, critical_types=frozenset({"a"})).run(plan, _ctx())

    def test_external_cancellation_stops_scheduling(self) -> None:
        reg = TaskRegistry()
        reg.register(_Exec("a"))
        plan = ExecutionPlan("p", 1, tasks=(_task("a"),))
        ctx = _ctx()
        ctx.stop_event = threading.Event()
        ctx.stop_event.set()
        report = TaskScheduler(reg).run(plan, ctx)
        self.assertTrue(report.cancelled_externally)
        self.assertEqual(report.states["a"], "cancelled")


# ------------------------- Checkpoints ------------------------------------ #
class CheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def _store(self):
        return CheckpointStore(self.tmp)

    def _save(self, store):
        return store.save("camp-1", plan={"plan_id": "p", "version": 1,
                                           "tasks": [{"task_id": "scope", "task_type": "scope"}]},
                          task_states={"scope": "completed"},
                          task_results={"scope": {"task_id": "scope", "state": "completed"}},
                          campaign_state="completed", scope_summary={"target": "x"})

    def test_save_and_load_roundtrip(self) -> None:
        store = self._store()
        self._save(store)
        loaded = store.load("camp-1")
        self.assertEqual(loaded["campaign_id"], "camp-1")
        self.assertEqual(loaded["task_states"], {"scope": "completed"})

    def test_integrity_failure_detected(self) -> None:
        store = self._store()
        path = self._save(store)
        import json
        data = json.loads(path.read_text())
        data["task_states"]["scope"] = "tampered"
        path.write_text(json.dumps(data))
        with self.assertRaises(CheckpointError):
            store.load("camp-1")

    def test_incompatible_version_rejected(self) -> None:
        store = self._store()
        path = self._save(store)
        import json
        data = json.loads(path.read_text())
        data["format_version"] = 999
        data["integrity"] = __import__("hashlib").sha256(
            json.dumps({k: v for k, v in data.items() if k != "integrity"},
                       sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path.write_text(json.dumps(data))
        with self.assertRaises(CheckpointError):
            store.load("camp-1")

    def test_conservative_recovery_classification(self) -> None:
        checkpoint = {
            "task_states": {"scope": "completed", "discovery": "running",
                            "remediation": "pending", "triage": "failed"},
            "plan": {"tasks": [
                {"task_id": "scope", "task_type": "scope"},
                {"task_id": "discovery", "task_type": "discovery"},
                {"task_id": "remediation", "task_type": "remediation"},
                {"task_id": "triage", "task_type": "triage"}]},
        }
        rec = plan_recovery(checkpoint)
        self.assertIn("scope", rec.keep_completed)
        self.assertIn("discovery", rec.needs_manual_review)   # interrompida tocando rede
        self.assertIn("remediation", rec.reschedulable)       # local, pendente
        self.assertIn("triage", rec.needs_manual_review)      # falhou


if __name__ == "__main__":
    unittest.main()
