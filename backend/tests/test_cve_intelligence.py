"""Testes de CVE Intelligence: inventário, pesquisa, correlação, hipóteses (Fase 4).

Totalmente offline: os providers recebem um ``fetch`` falso com fixtures.
"""

from __future__ import annotations

import unittest

from pentest_pipeline.contracts import (AffectedRange, CorrelationResult, CveRecord,
                                        TechnologyComponent)
from pentest_pipeline.intelligence import (CveCorrelationEngine, CveResearchService,
                                           HypothesisRegistry, build_components,
                                           compare_versions)
from pentest_pipeline.intelligence.cache import TTLCache
from pentest_pipeline.intelligence.http_client import (ControlledHttpClient,
                                                       IntelligenceHttpError, _assert_allowed)
from pentest_pipeline.intelligence.providers.nvd import NvdProvider
from pentest_pipeline.intelligence.providers.osv import OsvProvider


# --------------------------- 4.1 Inventário ------------------------------- #
class InventoryTests(unittest.TestCase):
    def test_exact_version_component(self) -> None:
        comps = build_components({"family": "Angular", "version": "12.0.0", "certainty": "exact"})
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].version, "12.0.0")
        self.assertEqual(comps[0].identification_status, "exact")
        self.assertEqual(comps[0].ecosystem, "npm")

    def test_family_only_has_no_exact_version(self) -> None:
        comps = build_components({"family": "Angular", "version": "12.0.0",
                                  "certainty": "family_only"})
        self.assertIsNone(comps[0].version)   # cabeçalho/HTML não vira versão exata
        self.assertEqual(comps[0].version_confidence, "partial")

    def test_unknown_family_invents_nothing(self) -> None:
        self.assertEqual(build_components({"family": "não identificada",
                                           "certainty": "not_detected"}), [])


# --------------------------- Segurança do cliente HTTP -------------------- #
class HttpClientSafetyTests(unittest.TestCase):
    def test_only_allowlisted_https_hosts(self) -> None:
        _assert_allowed("https://services.nvd.nist.gov/rest/json/cves/2.0")  # ok
        _assert_allowed("https://api.osv.dev/v1/query")                       # ok
        for bad in ("https://evil.example/x", "http://services.nvd.nist.gov/x",
                    "https://4.migbot.com.br/", "https://services.nvd.nist.gov.evil/x"):
            with self.subTest(url=bad), self.assertRaises(IntelligenceHttpError):
                _assert_allowed(bad)

    def test_target_name_cannot_redirect_destination(self) -> None:
        # Um "nome de tecnologia" malicioso não muda o host fixo do provider.
        with self.assertRaises(IntelligenceHttpError):
            ControlledHttpClient().get_json("https://attacker.test/collect")


# --------------------------- 4.2 Pesquisa --------------------------------- #
class _FakeProvider:
    def __init__(self, name, records=None, error=False):
        self.name = name
        self._records = records or []
        self._error = error
        self.calls = 0

    def query(self, component):
        self.calls += 1
        if self._error:
            raise IntelligenceHttpError("indisponível")
        return self._records


def _component():
    return TechnologyComponent(component_id="tech:@angular/core", name="Angular",
                               normalized_name="@angular/core", ecosystem="npm",
                               version="12.0.0", version_confidence="exact",
                               identification_status="exact")


class ResearchTests(unittest.TestCase):
    def test_aggregates_and_marks_full_coverage(self) -> None:
        rec = CveRecord(vulnerability_id="CVE-1", source="nvd")
        service = CveResearchService([_FakeProvider("nvd", [rec])])
        out = service.research([_component()])
        self.assertEqual(out["coverage"], "full")
        self.assertEqual(len(out["records"]["tech:@angular/core"]), 1)

    def test_provider_failure_is_isolated_and_partial(self) -> None:
        rec = CveRecord(vulnerability_id="CVE-1", source="osv")
        service = CveResearchService([_FakeProvider("nvd", error=True),
                                      _FakeProvider("osv", [rec])])
        out = service.research([_component()])
        self.assertEqual(out["coverage"], "partial")
        self.assertEqual(out["providers_failed"], ["nvd"])
        self.assertEqual(len(out["records"]["tech:@angular/core"]), 1)  # osv preservado
        self.assertEqual(len(out["failures"]), 1)

    def test_empty_results_is_success_not_failure(self) -> None:
        service = CveResearchService([_FakeProvider("nvd", [])])
        out = service.research([_component()])
        self.assertEqual(out["coverage"], "full")
        self.assertEqual(out["records"]["tech:@angular/core"], [])

    def test_no_components_is_not_applicable(self) -> None:
        self.assertEqual(CveResearchService([]).research([])["coverage"], "not_applicable")

    def test_cache_prevents_second_provider_call(self) -> None:
        provider = _FakeProvider("nvd", [CveRecord(vulnerability_id="CVE-1", source="nvd")])
        service = CveResearchService([provider], cache=TTLCache())
        service.research([_component()])
        service.research([_component()])
        self.assertEqual(provider.calls, 1)   # segundo veio do cache


# --------------------------- providers (normalização) --------------------- #
class ProviderNormalizationTests(unittest.TestCase):
    def test_osv_normalizes_ranges(self) -> None:
        payload = {"vulns": [{"id": "GHSA-x", "summary": "XSS", "details": "d",
            "affected": [{"package": {"ecosystem": "npm", "name": "@angular/core"},
                          "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"},
                                                                   {"fixed": "12.0.5"}]}]}],
            "references": [{"url": "https://example/x"}], "aliases": ["CVE-2"]}]}
        provider = OsvProvider(lambda *a, **k: payload)
        recs = provider.query(_component())
        self.assertEqual(recs[0].vulnerability_id, "GHSA-x")
        self.assertEqual(recs[0].affected[0].fixed, "12.0.5")
        self.assertIn("CVE-2", recs[0].aliases)

    def test_malformed_response_yields_no_records(self) -> None:
        provider = NvdProvider(lambda *a, **k: {"unexpected": True})
        self.assertEqual(provider.query(_component()), [])


# --------------------------- 4.3 Correlação ------------------------------- #
class CorrelationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = CveCorrelationEngine()

    def _record(self, introduced="0", fixed=None, product="@angular/core", **kw):
        return CveRecord(vulnerability_id="CVE-1", source="osv",
                         affected=(AffectedRange(ecosystem="npm", product=product,
                                                 introduced=introduced, fixed=fixed),), **kw)

    def test_version_in_range_is_potentially_affected(self) -> None:
        result = self.engine.correlate(_component(), self._record(fixed="12.0.5"))
        self.assertEqual(result.status, "potentially_affected")
        self.assertEqual(result.confidence, "strong")

    def test_version_at_or_after_fix_is_not_affected(self) -> None:
        result = self.engine.correlate(_component(), self._record(fixed="12.0.0"))
        self.assertEqual(result.status, "not_affected")

    def test_unknown_version_is_version_unknown(self) -> None:
        comp = TechnologyComponent(component_id="c", name="Angular",
                                   normalized_name="@angular/core", ecosystem="npm",
                                   version=None, version_confidence="unknown",
                                   identification_status="unknown")
        result = self.engine.correlate(comp, self._record(fixed="12.0.5"))
        self.assertEqual(result.status, "version_unknown")

    def test_name_only_match_is_not_potentially_affected(self) -> None:
        # produto diferente, sem range aplicável -> nunca potentially_affected
        record = CveRecord(vulnerability_id="CVE-9", source="nvd",
                           affected=(AffectedRange(product="other-lib", fixed="9.9.9"),))
        result = self.engine.correlate(_component(), record)
        self.assertEqual(result.status, "inconclusive")
        self.assertEqual(result.confidence, "none")

    def test_kev_adds_reason(self) -> None:
        record = self._record(fixed="12.0.5", known_exploited=True)
        result = self.engine.correlate(_component(), record)
        self.assertTrue(any("KEV" in r for r in result.reasons))

    def test_compare_versions(self) -> None:
        self.assertEqual(compare_versions("1.2.3", "1.2.3"), 0)
        self.assertEqual(compare_versions("1.2.0", "1.10.0"), -1)
        self.assertEqual(compare_versions("2.0.0", "1.9.9"), 1)


# --------------------------- 4.4 Hipóteses -------------------------------- #
class HypothesisRegistryTests(unittest.TestCase):
    def test_dedup_same_cve_from_two_sources(self) -> None:
        registry = HypothesisRegistry("camp-1")
        comp = _component()
        corr = CorrelationResult(comp.component_id, "CVE-1", "potentially_affected", "strong")
        registry.register(comp, CveRecord(vulnerability_id="CVE-1", source="nvd"), corr)
        registry.register(comp, CveRecord(vulnerability_id="CVE-1", source="osv"), corr)
        hyps = registry.all()
        self.assertEqual(len(hyps), 1)
        self.assertEqual(sorted(hyps[0].source_refs), ["nvd", "osv"])
        self.assertEqual(len(hyps[0].history), 2)

    def test_ghsa_alias_maps_to_cve_canonical(self) -> None:
        registry = HypothesisRegistry("camp-1")
        comp = _component()
        corr = CorrelationResult(comp.component_id, "GHSA-x", "candidate", "weak")
        registry.register(comp, CveRecord(vulnerability_id="GHSA-x", source="osv",
                                          aliases=("CVE-7",)), corr)
        self.assertEqual(registry.all()[0].vulnerability_id, "CVE-7")

    def test_hypothesis_is_not_a_finding(self) -> None:
        registry = HypothesisRegistry("camp-1")
        comp = _component()
        corr = CorrelationResult(comp.component_id, "CVE-1", "potentially_affected", "strong")
        hyp = registry.register(comp, CveRecord(vulnerability_id="CVE-1", source="nvd",
                                               known_exploited=True), corr)
        self.assertTrue(hyp.limitations)   # sempre registra limitação
        self.assertEqual(hyp.priority, "high")   # strong + KEV


# --------------------------- 4.5/4.7 Integração V2 ------------------------ #
from email.message import Message
from unittest.mock import patch
from urllib.parse import urlsplit

from pentest_pipeline.orchestration.orchestrator import OrchestratorV2
from pentest_pipeline.report import render_markdown
from pentest_pipeline.scope import ScopeConfig
from pentest_pipeline.transport import Response


def _resp(url, status, body=b"", ct="text/html"):
    m = Message()
    m["Content-Type"] = ct
    return Response(url, status, m, body, False, 1)


class _FT:
    def __init__(self, config, *, stop_event=None, on_event=None, responses=None):
        self.config = config
        self.responses = responses or {}
        self.request_count = 0
        self.actions = []
        self.on_event = on_event

    def request(self, url, *, method="GET", phase="test"):
        self.config.assert_request(url, method)
        self.request_count += 1
        key = (method, urlsplit(url).path)
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


def _mk(c, **kw):
    return _FT(c, responses={
        ("GET", "/"): _resp(c.target_url, 200, b"<html>Home</html>"),
        ("GET", "/robots.txt"): _resp(c.target_url, 404),
        ("GET", "/.well-known/security.txt"): _resp(c.target_url, 404)}, **kw)


_FRAMEWORK = {"type": "framework_inventory", "family": "Angular", "version": "12.0.0",
              "certainty": "exact", "advisories": []}


class _StubService:
    def __init__(self, coverage="full", failures=None, fail=False):
        self.coverage = coverage
        self.failures = failures or []
        self.fail = fail

    def research(self, components):
        records = {}
        for c in components:
            records[c.component_id] = [] if self.fail else [CveRecord(
                vulnerability_id="CVE-1", source="osv",
                affected=(AffectedRange(ecosystem="npm", product="@angular/core",
                                        introduced="0", fixed="99.0.0"),)).to_dict()]
        return {"records": records, "coverage": self.coverage, "failures": self.failures,
                "providers_ok": [] if self.fail else ["osv"],
                "providers_failed": ["nvd"] if self.failures else []}


def _intel_obs(result):
    return [o for o in result.observations if o.get("type") == "vulnerability_intelligence"]


class OrchestratorIntelligenceTests(unittest.TestCase):
    def test_disabled_adds_no_intelligence(self) -> None:
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            result = OrchestratorV2(cve_intelligence=False).run(_cfg())
        self.assertEqual(result.status, "completed")
        self.assertEqual(_intel_obs(result), [])

    def test_enabled_registers_hypotheses(self) -> None:
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk), \
             patch("pentest_pipeline.orchestration.executors.inspect_angular", return_value=_FRAMEWORK):
            result = OrchestratorV2(cve_intelligence=True, cve_service=_StubService()).run(_cfg())
        self.assertEqual(result.status, "completed")
        obs = _intel_obs(result)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["coverage"], "full")
        self.assertTrue(obs[0]["hypotheses"])
        self.assertEqual(obs[0]["hypotheses"][0]["vulnerability_id"], "CVE-1")

    def test_provider_failure_keeps_campaign_and_marks_partial(self) -> None:
        service = _StubService(coverage="partial", failures=[{"provider": "nvd", "error": "x"}])
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk), \
             patch("pentest_pipeline.orchestration.executors.inspect_angular", return_value=_FRAMEWORK):
            result = OrchestratorV2(cve_intelligence=True, cve_service=service).run(_cfg())
        self.assertEqual(result.status, "completed")  # local não comprometido
        self.assertEqual(_intel_obs(result)[0]["coverage"], "partial")
        self.assertEqual(_intel_obs(result)[0]["providers_failed"], ["nvd"])

    def test_report_markdown_has_intelligence_section(self) -> None:
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk), \
             patch("pentest_pipeline.orchestration.executors.inspect_angular", return_value=_FRAMEWORK):
            result = OrchestratorV2(cve_intelligence=True, cve_service=_StubService()).run(_cfg())
        md = render_markdown(result.to_dict())
        self.assertIn("Inteligência de vulnerabilidades conhecidas", md)
        self.assertIn("CVE-1", md)
        self.assertIn("não são achados confirmados", md.lower())


if __name__ == "__main__":
    unittest.main()
