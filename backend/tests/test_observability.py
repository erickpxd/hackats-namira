"""Testes da observabilidade: Event Store e projeção de macrofases (Fase 3)."""

from __future__ import annotations

import unittest

from pentest_pipeline.orchestration import EventStore, MACROPHASES, project
from pentest_pipeline.orchestration import events as ev


def _v2(event_type, task_id=None, task_type=None, **extra):
    e = {"type": event_type, "orchestrator": "v2", "campaign_id": "c1",
         "correlation_id": "corr", "timestamp": f"t{task_id or 0}"}
    if task_id:
        e["task_id"] = task_id
        e["task_type"] = task_type or task_id
    e.update(extra)
    return e


class EventStoreTests(unittest.TestCase):
    def test_normalizes_to_canonical_schema(self) -> None:
        store = EventStore(campaign_id="c1")
        event = store.append(_v2("task_started", "scope", "scope"))
        for field in ("event_id", "campaign_id", "task_id", "agent_id", "event_type",
                      "timestamp", "status", "parent_event_id", "decision_source",
                      "reason", "evidence_refs"):
            self.assertIn(field, event)
        self.assertEqual(event["event_type"], "task_started")
        self.assertEqual(event["agent_id"], "scope")

    def test_dedup_and_stable_ids(self) -> None:
        store = EventStore(campaign_id="c1")
        raw = _v2("task_started", "scope", "scope")
        self.assertIsNotNone(store.append(raw))
        self.assertIsNone(store.append(raw))  # duplicado ignorado
        self.assertEqual(len(store.all()), 1)

    def test_sanitizes_sensitive_fields(self) -> None:
        store = EventStore(campaign_id="c1")
        event = store.append({"type": "decision", "api_key": "SECRET", "token": "x",
                              "message": "ok"})
        self.assertNotIn("api_key", event)
        self.assertNotIn("token", event)

    def test_pagination_is_ordered_and_consistent(self) -> None:
        store = EventStore(campaign_id="c1")
        for i in range(5):
            store.append(_v2("task_started", f"t{i}", "scope", message=f"m{i}"))
        first = store.page(after_seq=0, limit=2)
        self.assertEqual(len(first["events"]), 2)
        self.assertTrue(first["has_more"])
        second = store.page(after_seq=first["next_seq"], limit=10)
        self.assertEqual(second["events"][0]["seq"], first["next_seq"] + 1)


class ProjectionTests(unittest.TestCase):
    def test_eight_macrophases_always_present(self) -> None:
        state = project([], campaign_state=None, running=False)
        self.assertEqual(len(state["macrophases"]), 8)
        self.assertEqual([m["id"] for m in state["macrophases"]],
                         [m["id"] for m in MACROPHASES])

    def test_multiple_parallel_agents_supported(self) -> None:
        events = [
            _v2("task_started", "remediation", "remediation"),
            _v2("task_started", "target_analysis", "target_analysis"),
            _v2("task_started", "ai_advisor", "ai_advisor"),
        ]
        state = project(events, running=True)
        self.assertEqual(state["active_agent_count"], 3)
        self.assertIn("remediation", state["active_agents"])
        # macrofase multiagente deve estar ativa (tem 2 das 3 tarefas rodando)
        multi = next(m for m in state["macrophases"] if m["id"] == "multiagent")
        self.assertEqual(multi["status"], "running")
        self.assertGreaterEqual(multi["active_count"], 2)

    def test_completed_task_sets_macrophase_completed(self) -> None:
        events = [_v2("task_started", "scope", "scope"),
                  _v2("task_completed", "scope", "scope", state="completed")]
        state = project(events)
        scope = next(m for m in state["macrophases"] if m["id"] == "scope")
        self.assertEqual(scope["status"], "completed")

    def test_failed_task_not_marked_completed(self) -> None:
        events = [_v2("task_started", "discovery", "discovery"),
                  _v2("task_failed", "discovery", "discovery")]
        state = project(events)
        disc = next(m for m in state["macrophases"] if m["id"] == "discovery")
        self.assertEqual(disc["status"], "failed")

    def test_pending_macrophase_stays_pending(self) -> None:
        events = [_v2("task_completed", "scope", "scope", state="completed")]
        state = project(events)
        triage = next(m for m in state["macrophases"] if m["id"] == "triage")
        self.assertEqual(triage["status"], "pending")

    def test_waiting_approval_is_not_completion(self) -> None:
        events = [_v2("task_started", "surface_checks", "surface_checks"),
                  {"type": "task_started", "task_id": "surface_checks",
                   "task_type": "surface_checks", "status": "waiting_approval"}]
        # força estado waiting_approval via evento específico
        events.append({"type": "approval_requested", "task_id": "surface_checks",
                       "task_type": "surface_checks"})
        state = project(events, running=True)
        safe = next(m for m in state["macrophases"] if m["id"] == "safe_tests")
        self.assertIn(safe["status"], ("running", "waiting_approval"))

    def test_legacy_fallback_uses_phases(self) -> None:
        events = [{"type": "stage_plan", "phase": "scope", "message": "x"},
                  {"type": "stage_plan", "phase": "discovery", "message": "y"}]
        state = project(events, campaign_state=None, running=True)
        self.assertEqual(state["mode"], "legacy")
        ids = {m["id"]: m["status"] for m in state["macrophases"]}
        self.assertEqual(ids["scope"], "completed")
        self.assertEqual(ids["discovery"], "running")
        self.assertEqual(ids["triage"], "pending")

    def test_monitoring_phase_follows_campaign_state(self) -> None:
        events = [_v2("task_completed", "triage", "triage", state="completed")]
        state = project(events, campaign_state="completed", running=False)
        monitoring = next(m for m in state["macrophases"] if m["id"] == "monitoring")
        self.assertEqual(monitoring["status"], "completed")


if __name__ == "__main__":
    unittest.main()
