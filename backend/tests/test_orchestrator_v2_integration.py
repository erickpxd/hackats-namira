"""Testes de integração do OrchestratorV2 e equivalência com o legado (Fase 2).

Nenhum alvo externo é contatado: todo transporte é simulado.
"""

from __future__ import annotations

from email.message import Message
from urllib.parse import urlsplit
import os
import tempfile
import unittest
from unittest.mock import patch

from pentest_pipeline import run_campaign, run_scan
from pentest_pipeline.orchestration import project
from pentest_pipeline.orchestration.orchestrator import OrchestratorV2
from pentest_pipeline.persistence import CheckpointStore
from pentest_pipeline.scope import ScopeConfig
from pentest_pipeline.transport import RequestBudgetExceeded, Response


def resp(url, status, body=b"", ct="text/html", **h):
    m = Message()
    m["Content-Type"] = ct
    for k, v in h.items():
        m[k.replace("_", "-")] = v
    return Response(url, status, m, body, False, 1)


class FakeTransport:
    def __init__(self, config, *, stop_event=None, on_event=None, responses=None,
                 budget_after=None):
        self.config = config
        self.responses = responses or {}
        self.budget_after = budget_after
        self.request_count = 0
        self.actions: list[dict] = []
        self.on_event = on_event
        self.seen: list[tuple[str, str]] = []

    def request(self, url, *, method="GET", phase="test"):
        self.config.assert_request(url, method)
        if self.budget_after is not None and self.request_count >= self.budget_after:
            raise RequestBudgetExceeded("budget")
        key = (method, urlsplit(url).path)
        self.seen.append(key)
        self.request_count += 1
        if key not in self.responses:
            raise AssertionError(f"unexpected {key}")
        i = self.responses[key]
        return Response(url, i.status, i.headers, i.body, i.truncated, i.elapsed_ms)

    def record(self, t, p, m, **d):
        e = {"type": t, "phase": p, "message": m, **d}
        self.actions.append(e)
        if self.on_event:
            self.on_event(e)


def _cfg():
    return ScopeConfig.for_target_url("https://example.com/#/")


def _responses(c):
    return {("GET", "/"): resp(c.target_url, 200, b"<html>Home</html>"),
            ("GET", "/robots.txt"): resp(c.target_url, 404),
            ("GET", "/.well-known/security.txt"): resp(c.target_url, 404)}


def _mk(c, **kw):
    return FakeTransport(c, responses=_responses(c), **kw)


class EquivalenceTests(unittest.TestCase):
    """Critério essencial: legado vs V2 na mesma fixture."""

    def test_v2_matches_legacy_on_contract_fields(self) -> None:
        cfg = _cfg()
        with patch("pentest_pipeline.pipeline.BoundedTransport", side_effect=_mk):
            legacy = run_scan(cfg)
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            v2 = OrchestratorV2().run(cfg)

        self.assertEqual(v2.status, legacy.status)
        self.assertEqual(v2.summary["selected_checks"], legacy.summary["selected_checks"])
        self.assertEqual(v2.summary["ruleset_hash"], legacy.summary["ruleset_hash"])
        self.assertEqual(len(v2.findings), len(legacy.findings))
        self.assertEqual(v2.summary["by_severity"], legacy.summary["by_severity"])
        self.assertEqual(v2.summary["by_status"], legacy.summary["by_status"])
        self.assertEqual([f.to_dict() for f in v2.findings],
                         [f.to_dict() for f in legacy.findings])
        self.assertEqual(v2.recommendations, legacy.recommendations)

    def test_v2_is_not_a_run_scan_facade(self) -> None:
        # Garante que o V2 executa via scheduler (run_scan não é chamado).
        cfg = _cfg()
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk), \
             patch("pentest_pipeline.pipeline.run_scan") as legacy_spy:
            OrchestratorV2().run(cfg)
        legacy_spy.assert_not_called()


class DispatcherAndFlagTests(unittest.TestCase):
    def test_run_campaign_v2_executes_orchestrator(self) -> None:
        cfg = _cfg()
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            result = run_campaign(cfg, orchestrator="v2")
        self.assertEqual(result.status, "completed")

    def test_env_flag_selects_v2(self) -> None:
        cfg = _cfg()
        with patch.dict(os.environ, {"PENTEST_ORCHESTRATOR": "v2"}), \
             patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            result = run_campaign(cfg)
        self.assertEqual(result.status, "completed")

    def test_default_is_still_legacy(self) -> None:
        cfg = _cfg()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PENTEST_ORCHESTRATOR", None)
            with patch("pentest_pipeline.pipeline.run_scan") as legacy_spy, \
                 patch("pentest_pipeline.orchestration.orchestrator.OrchestratorV2") as v2_spy:
                legacy_spy.return_value = "L"
                out = run_campaign(cfg)
        self.assertEqual(out, "L")
        v2_spy.assert_not_called()


class ControlledTerminationTests(unittest.TestCase):
    def test_budget_exhaustion_in_v2(self) -> None:
        cfg = _cfg()

        def mk(c, **kw):
            return FakeTransport(c, responses=_responses(c), budget_after=0, **kw)

        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=mk):
            result = OrchestratorV2().run(cfg)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.stop_reason, "request_budget_exhausted")

    def test_isolated_local_analysis_failure_does_not_crash_campaign(self) -> None:
        cfg = _cfg()

        class BoomRemediation:
            def run(self, findings, transport):
                raise RuntimeError("remediation failed")

        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk), \
             patch("pentest_pipeline.orchestration.executors.RemediationAgent", BoomRemediation):
            result = OrchestratorV2().run(cfg)
        # A campanha continua; achados preservados apesar da falha local.
        self.assertIn(result.status, ("completed", "inconclusive"))
        self.assertEqual(result.status, "completed")


class EventsAndCheckpointTests(unittest.TestCase):
    def test_structured_events_emitted(self) -> None:
        cfg = _cfg()
        events_seen: list[dict] = []
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            OrchestratorV2().run(cfg, on_event=events_seen.append)
        types = {e.get("type") for e in events_seen}
        for expected in ("campaign_started", "plan_created", "task_completed",
                         "campaign_completed"):
            self.assertIn(expected, types)
        # todos os eventos do orquestrador carregam identificadores de rastreio
        orch = [e for e in events_seen if e.get("orchestrator") == "v2"]
        self.assertTrue(all("campaign_id" in e and "correlation_id" in e for e in orch))

    def test_projection_from_real_run_marks_macrophases(self) -> None:
        cfg = _cfg()
        collected: list[dict] = []
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            result = OrchestratorV2().run(cfg, on_event=collected.append)
        state = project(collected, campaign_state=result.status, running=False)
        self.assertEqual(state["mode"], "v2")
        by_id = {m["id"]: m["status"] for m in state["macrophases"]}
        self.assertEqual(by_id["scope"], "completed")
        self.assertEqual(by_id["discovery"], "completed")
        self.assertEqual(by_id["triage"], "completed")
        self.assertEqual(by_id["monitoring"], "completed")  # segue status da campanha
        # nenhuma macrofase executada ficou pendente indevidamente
        self.assertNotEqual(by_id["safe_tests"], "pending")

    def test_checkpoint_saved_and_loadable(self) -> None:
        cfg = _cfg()
        tmp = tempfile.mkdtemp()
        store = CheckpointStore(tmp)
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            result = OrchestratorV2(checkpoint_store=store).run(cfg)
        loaded = store.load(result.run_id)
        self.assertEqual(loaded["campaign_state"], result.status)
        self.assertIn("scope", loaded["task_states"])
        self.assertEqual(loaded["task_states"]["scope"], "completed")


if __name__ == "__main__":
    unittest.main()
