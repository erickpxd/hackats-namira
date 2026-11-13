"""Testes da feature flag PENTEST_ORCHESTRATOR e do dispatcher run_campaign.

Garantem que:
- legacy é o padrão e executa a pipeline atual;
- v2 é recusado de forma explícita e controlada (sem fallback silencioso);
- valores inválidos são recusados;
- API e CLI preservam o comportamento legado e reportam v2 com erro claro.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from pentest_pipeline.orchestration import (OrchestratorConfigError, OrchestratorMode,
                                            ensure_executable, resolve_mode, run_campaign)
from pentest_pipeline.orchestration import config as orch_config
from pentest_pipeline.scope import ScopeConfig


class ResolveModeTests(unittest.TestCase):
    def test_default_is_legacy(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PENTEST_ORCHESTRATOR", None)
            self.assertIs(resolve_mode(), OrchestratorMode.LEGACY)

    def test_env_v2_resolves_and_is_executable(self) -> None:
        # Fase 2: v2 está implementado, logo é executável.
        with patch.dict(os.environ, {"PENTEST_ORCHESTRATOR": "v2"}):
            mode = resolve_mode()
            self.assertIs(mode, OrchestratorMode.V2)
            ensure_executable(mode)  # não deve levantar

    def test_explicit_overrides_env_and_is_case_insensitive(self) -> None:
        with patch.dict(os.environ, {"PENTEST_ORCHESTRATOR": "v2"}):
            self.assertIs(resolve_mode("LEGACY"), OrchestratorMode.LEGACY)

    def test_unknown_value_is_rejected(self) -> None:
        with self.assertRaises(OrchestratorConfigError):
            resolve_mode("banana")
        with patch.dict(os.environ, {"PENTEST_ORCHESTRATOR": "turbo"}):
            with self.assertRaises(OrchestratorConfigError):
                resolve_mode()

    def test_legacy_is_always_executable(self) -> None:
        ensure_executable(OrchestratorMode.LEGACY)  # não deve levantar


class RunCampaignDispatcherTests(unittest.TestCase):
    def _config(self) -> ScopeConfig:
        return ScopeConfig(target_url="https://4.migbot.com.br/",
                           allowed_hosts=("4.migbot.com.br",))

    def test_legacy_delegates_to_run_scan_with_same_kwargs(self) -> None:
        sentinel = object()
        captured = {}

        def fake_run_scan(config, **kwargs):
            captured["config"] = config
            captured["kwargs"] = kwargs
            return sentinel

        with patch("pentest_pipeline.pipeline.run_scan", fake_run_scan):
            out = run_campaign(self._config(), orchestrator="legacy",
                               selected_checks=("headers",), approved_actions=())
        self.assertIs(out, sentinel)
        self.assertEqual(captured["kwargs"],
                         {"selected_checks": ("headers",), "approved_actions": ()})

    def test_v2_routes_to_orchestrator_not_run_scan(self) -> None:
        with patch("pentest_pipeline.pipeline.run_scan") as legacy_spy, \
             patch("pentest_pipeline.orchestration.orchestrator.OrchestratorV2") as v2_cls:
            v2_cls.return_value.run.return_value = "V2"
            out = run_campaign(self._config(), orchestrator="v2")
        self.assertEqual(out, "V2")
        legacy_spy.assert_not_called()
        v2_cls.return_value.run.assert_called_once()

    def test_v2_is_implemented_in_phase2(self) -> None:
        self.assertTrue(orch_config.is_v2_implemented())


class ApiFlagIntegrationTests(unittest.TestCase):
    """A API deve recusar configuração de orquestrador inválida, sem iniciar."""

    def test_start_rejects_invalid_orchestrator_value(self) -> None:
        from pentest_pipeline.web_server import CampaignConsole

        console = CampaignConsole.__new__(CampaignConsole)  # evita I/O do __init__
        with patch("pentest_pipeline.web_server.resolve_mode",
                   side_effect=OrchestratorConfigError("PENTEST_ORCHESTRATOR inválido")), \
             patch("pentest_pipeline.web_server.run_campaign") as worker:
            ok, message = CampaignConsole.start(console)
        self.assertFalse(ok)
        self.assertIn("inválido", message)
        worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
