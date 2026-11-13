"""Regressão para a migração da Fase 1.

Fixa comportamentos que NÃO podem mudar enquanto o orquestrador v2 é
construído: o dispatcher legado deve ser idêntico a ``run_scan``, os
encerramentos controlados devem continuar válidos e o contrato público de
``ScanResult``/``Finding`` consumido pelo frontend deve permanecer estável.

Todo o tráfego é simulado localmente — nenhum alvo externo é contatado.
"""

from __future__ import annotations

from email.message import Message
from urllib.parse import urlsplit
import json
import unittest
from unittest.mock import patch

from pentest_pipeline import run_campaign, run_scan
from pentest_pipeline.scope import ScopeConfig
from pentest_pipeline.transport import RequestBudgetExceeded, Response


def response(url: str, status: int, body: bytes = b"", content_type: str = "text/html",
             **headers: str) -> Response:
    message = Message()
    message["Content-Type"] = content_type
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    return Response(url, status, message, body, False, 1)


class FakeTransport:
    """Transporte simulado: nunca toca a rede; respeita escopo e orçamento."""

    def __init__(self, config, *, stop_event=None, on_event=None, responses=None,
                 budget_after=None):
        self.config = config
        self.responses = responses or {}
        self.budget_after = budget_after
        self.request_count = 0
        self.actions: list[dict] = []
        self.on_event = on_event
        self.seen: list[tuple[str, str]] = []

    def request(self, url: str, *, method: str = "GET", phase: str = "test") -> Response:
        self.config.assert_request(url, method)
        if self.budget_after is not None and self.request_count >= self.budget_after:
            raise RequestBudgetExceeded("request budget exhausted")
        key = (method, urlsplit(url).path)
        self.seen.append(key)
        self.request_count += 1
        if key not in self.responses:
            raise AssertionError(f"Unexpected simulated request: {key}")
        item = self.responses[key]
        return Response(url, item.status, item.headers, item.body, item.truncated,
                        item.elapsed_ms)

    def record(self, type_: str, phase: str, message: str, **details) -> None:
        event = {"type": type_, "phase": phase, "message": message, **details}
        self.actions.append(event)
        if self.on_event:
            self.on_event(event)


def _generic_config() -> ScopeConfig:
    return ScopeConfig.for_target_url("https://example.com/#/")


def _happy_responses(cfg) -> dict:
    return {
        ("GET", "/"): response(cfg.target_url, 200, b"<html>Home</html>"),
        ("GET", "/robots.txt"): response(cfg.target_url, 404),
        ("GET", "/.well-known/security.txt"): response(cfg.target_url, 404),
    }


class LegacyEquivalenceTests(unittest.TestCase):
    """run_campaign(legacy) deve produzir o mesmo resultado que run_scan."""

    def test_dispatcher_matches_run_scan_on_stable_fields(self) -> None:
        cfg = _generic_config()

        def make(cfg_, **kwargs):
            return FakeTransport(cfg_, responses=_happy_responses(cfg_), **kwargs)

        with patch("pentest_pipeline.pipeline.BoundedTransport", side_effect=make):
            direct = run_scan(cfg)
            viaflag = run_campaign(cfg, orchestrator="legacy")

        self.assertEqual(direct.status, "completed")
        self.assertEqual(viaflag.status, direct.status)
        self.assertEqual(viaflag.summary["selected_checks"], direct.summary["selected_checks"])
        self.assertEqual(viaflag.summary["ruleset_hash"], direct.summary["ruleset_hash"])
        self.assertEqual(len(viaflag.findings), len(direct.findings))

    def test_dispatcher_uses_env_default_when_mode_unset(self) -> None:
        cfg = _generic_config()

        def make(cfg_, **kwargs):
            return FakeTransport(cfg_, responses=_happy_responses(cfg_), **kwargs)

        with patch("pentest_pipeline.pipeline.BoundedTransport", side_effect=make):
            result = run_campaign(cfg)  # sem orchestrator explícito -> legacy padrão
        self.assertEqual(result.status, "completed")


class ControlledTerminationTests(unittest.TestCase):
    def test_budget_exhaustion_stops_without_claiming_completion(self) -> None:
        cfg = _generic_config()

        def make(cfg_, **kwargs):
            return FakeTransport(cfg_, responses=_happy_responses(cfg_),
                                 budget_after=0, **kwargs)

        with patch("pentest_pipeline.pipeline.BoundedTransport", side_effect=make):
            result = run_campaign(cfg)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.stop_reason, "request_budget_exhausted")
        self.assertNotEqual(result.status, "completed")


class PublicContractTests(unittest.TestCase):
    """Pino do contrato público consumido pela API/relatórios/frontend."""

    FRONTEND_RESULT_FIELDS = {"run_id", "target", "campaign_name", "status",
                              "stop_reason", "summary", "findings", "actions",
                              "recommendations", "observations", "started_at", "ended_at"}

    def test_scanresult_serialization_keeps_frontend_fields(self) -> None:
        cfg = _generic_config()

        def make(cfg_, **kwargs):
            return FakeTransport(cfg_, responses=_happy_responses(cfg_), **kwargs)

        with patch("pentest_pipeline.pipeline.BoundedTransport", side_effect=make):
            result = run_campaign(cfg)
        payload = result.to_dict()
        self.assertTrue(self.FRONTEND_RESULT_FIELDS.issubset(payload.keys()),
                        f"faltam campos: {self.FRONTEND_RESULT_FIELDS - set(payload)}")
        json.dumps(payload)  # deve ser JSON-serializável
        for field in ("requests", "findings", "selected_checks", "by_severity", "by_status"):
            self.assertIn(field, payload["summary"])

    def test_finding_contract_fields_present(self) -> None:
        cfg = _generic_config()

        def make(cfg_, **kwargs):
            return FakeTransport(cfg_, responses=_happy_responses(cfg_), **kwargs)

        with patch("pentest_pipeline.pipeline.BoundedTransport", side_effect=make):
            result = run_campaign(cfg)
        for finding in result.findings:
            data = finding.to_dict()
            for field in ("id", "title", "severity", "status", "confidence", "check", "url"):
                self.assertIn(field, data)


if __name__ == "__main__":
    unittest.main()
