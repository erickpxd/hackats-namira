"""Testes da contextualização MITRE ATT&CK (Fase 8).

Totalmente offline e determinístico. Cobre o contrato ``MitreMapping``, o
catálogo curado e o mapeador conservador (mapped/candidate/unmapped), além da
integração flag-gated em ``finalize_result``.
"""

from __future__ import annotations

import os
import unittest
from email.message import Message
from unittest.mock import patch

from pentest_pipeline import run_scan
from pentest_pipeline.contracts import MitreMapping, MitreError, is_valid_technique_id
from pentest_pipeline.contracts.mitre import MAPPING_STATUS, SUBJECT_NATURE
from pentest_pipeline.mitre import (DEFAULT_CATALOG, MitreMapper, build_mitre_observation,
                                    normalize_check_category)
from pentest_pipeline.report import render_markdown
from pentest_pipeline.scope import ScopeConfig
from pentest_pipeline.transport import Response


def _response(url, status, body=b"", content_type="text/html", **headers):
    message = Message()
    message["Content-Type"] = content_type
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    return Response(url, status, message, body, False, 1)


class _FakeTransport:
    def __init__(self, config, *, stop_event=None, on_event=None, responses=None, **_):
        self.config = config
        self.responses = responses or {}
        self.actions: list[dict] = []
        self.on_event = on_event
        self.request_count = 0

    def request(self, url, *, method="GET", phase="test"):
        self.config.assert_request(url, method)
        from urllib.parse import urlsplit
        key = (method, urlsplit(url).path)
        self.request_count += 1
        item = self.responses.get(key)
        if item is None:
            return _response(url, 404)
        return item

    def record(self, type_, phase, message, **details):
        event = {"type": type_, "phase": phase, "message": message, **details}
        self.actions.append(event)
        if self.on_event:
            self.on_event(event)


def _finding(**kw):
    base = dict(id="chk-abc123", title="Achado", severity="low",
                check="sql_error_exposure", status="completed",
                confidence="high", proof="", evidence="evid", url="http://x")
    base.update(kw)
    return base


# ------------------------------ Contrato ---------------------------------- #
class ContractTests(unittest.TestCase):
    def test_valid_technique_ids(self):
        self.assertTrue(is_valid_technique_id("T1190"))
        self.assertTrue(is_valid_technique_id("T1592.002"))
        self.assertFalse(is_valid_technique_id("1190"))
        self.assertFalse(is_valid_technique_id("T119"))
        self.assertFalse(is_valid_technique_id("TA0001"))
        self.assertFalse(is_valid_technique_id("CVE-2021-1234"))

    def test_mapped_requires_valid_technique_and_evidence(self):
        with self.assertRaises(MitreError):
            MitreMapping("m1", "f1", "NOPE", "x", "r", "mapped",
                         evidence_refs=("finding:f1",)).validate()
        with self.assertRaises(MitreError):
            MitreMapping("m1", "f1", "T1190", "x", "r", "mapped",
                         evidence_refs=()).validate()

    def test_unmapped_cannot_carry_technique(self):
        with self.assertRaises(MitreError):
            MitreMapping("m1", "f1", "T1190", "x", "r", "unmapped").validate()
        ok = MitreMapping("m1", "f1", None, None, "r", "unmapped").validate()
        self.assertEqual(ok.mapping_status, "unmapped")

    def test_roundtrip(self):
        m = MitreMapping("m1", "f1", "T1539", "Steal Web Session Cookie",
                         "porque sim", "candidate", tactic_ids=("TA0006",),
                         evidence_refs=("finding:f1",)).validate()
        self.assertEqual(MitreMapping.from_dict(m.to_dict()).to_dict(), m.to_dict())

    def test_vocabularies_closed(self):
        self.assertEqual(MAPPING_STATUS, frozenset({"mapped", "candidate", "unmapped"}))
        self.assertIn("known_vulnerability", SUBJECT_NATURE)
        self.assertIn("observed_behavior", SUBJECT_NATURE)


# ------------------------------ Catálogo ---------------------------------- #
class CatalogTests(unittest.TestCase):
    def test_all_catalog_ids_valid(self):
        for category, entry in DEFAULT_CATALOG.items():
            self.assertTrue(is_valid_technique_id(entry.technique_id),
                            f"{category} -> {entry.technique_id}")
            self.assertTrue(all(t.startswith("TA") for t in entry.tactic_ids))

    def test_normalize_collapses_suffixes(self):
        self.assertEqual(normalize_check_category("cookie_flags_session"), "cookie_flags")
        self.assertEqual(normalize_check_category("ftp_file_head_readme"), "ftp_file_head")
        self.assertEqual(normalize_check_category("missing_csp"), "missing_csp")


# ------------------------------ Mapeador ---------------------------------- #
class MapperTests(unittest.TestCase):
    def setUp(self):
        self.mapper = MitreMapper()

    def test_confirmed_weakness_is_mapped(self):
        r = self.mapper.map_finding(_finding(check="cookie_flags_sess",
                                             status="confirmed", confidence="high"))
        self.assertEqual(r.mapping_status, "mapped")
        self.assertEqual(r.technique_id, "T1539")
        self.assertTrue(r.evidence_refs)
        self.assertEqual(r.subject_nature, "known_vulnerability")

    def test_unconfirmed_is_candidate(self):
        r = self.mapper.map_finding(_finding(check="source_map_reference",
                                             status="inconclusive", confidence="high"))
        self.assertEqual(r.mapping_status, "candidate")
        self.assertEqual(r.technique_id, "T1592.002")

    def test_missing_control_is_unmapped(self):
        for check in ("missing_csp", "missing_hsts", "missing_frame_protection",
                      "unexpected_status"):
            r = self.mapper.map_finding(_finding(check=check, status="confirmed"))
            self.assertEqual(r.mapping_status, "unmapped", check)
            self.assertIsNone(r.technique_id)

    def test_no_evidence_no_technique(self):
        # Finding sem id -> sem evidência -> ignorado por map_findings.
        self.assertEqual(self.mapper.map_findings([dict(check="sql_error_exposure")]), [])

    def test_cve_text_does_not_drive_mapping(self):
        # Mesmo com um nome de CVE no título, mapeia pela categoria de check.
        r = self.mapper.map_finding(_finding(check="missing_csp",
                                             title="CVE-2021-44228 Log4Shell RCE",
                                             status="confirmed", confidence="high"))
        self.assertEqual(r.mapping_status, "unmapped")

    def test_deterministic_mapping_id(self):
        a = self.mapper.map_finding(_finding())
        b = self.mapper.map_finding(_finding())
        self.assertEqual(a.mapping_id, b.mapping_id)


# --------------------------- Observação / flag ----------------------------- #
class ObservationTests(unittest.TestCase):
    def test_observation_counts(self):
        findings = [
            _finding(id="a", check="cookie_flags_s", status="confirmed", confidence="high"),
            _finding(id="b", check="source_map_reference", status="inconclusive"),
            _finding(id="c", check="missing_csp", status="confirmed"),
        ]
        obs = build_mitre_observation(findings)
        self.assertEqual(obs["type"], "mitre_contextualization")
        self.assertEqual(obs["counts"], {"mapped": 1, "candidate": 1, "unmapped": 1})
        self.assertEqual(len(obs["mappings"]), 3)

    def test_flag_off_adds_no_observation(self):
        from pentest_pipeline import pipeline
        self.assertEqual(os.environ.get("PENTEST_MITRE_ATTACK"), None)
        # A ausência do flag é o default; finalize_result não deve adicionar MITRE.
        self.assertTrue(hasattr(pipeline, "finalize_result"))

    def test_report_renders_mitre_section(self):
        from pentest_pipeline.report import render_markdown
        from pentest_pipeline.models import Finding
        finding = Finding(id="a", title="Cookie sem flags", severity="low",
                          status="confirmed", confidence="high",
                          check="cookie_flags_s", url="http://x", evidence="e",
                          impact="i").to_dict()
        findings = [finding]
        data = {"campaign_name": "demo", "target": "http://x", "findings": findings,
                "summary": {}, "observations": [build_mitre_observation(findings)]}
        md = render_markdown(data)
        self.assertIn("Contextualização MITRE ATT&CK", md)
        self.assertIn("T1539", md)
        self.assertIn("não é execução de técnicas nem prova de exploração",
                      md.lower())


class EndToEndFlagTests(unittest.TestCase):
    """Caminho público run_scan com o flag ligado/desligado (P6)."""

    def _run(self, flag):
        cfg = ScopeConfig.for_target_url("https://example.com/#/")

        def make(cfg_, **kwargs):
            responses = {
                ("GET", "/"): _response(cfg_.target_url, 200, b"<html>Home</html>",
                                        Set_Cookie="sid=abc123"),
            }
            return _FakeTransport(cfg_, responses=responses, **kwargs)

        env = dict(os.environ)
        if flag:
            env["PENTEST_MITRE_ATTACK"] = "enabled"
        else:
            env.pop("PENTEST_MITRE_ATTACK", None)
        with patch.dict(os.environ, env, clear=True), \
                patch("pentest_pipeline.pipeline.BoundedTransport", side_effect=make):
            return run_scan(cfg)

    def test_flag_on_attaches_mitre_and_report(self):
        result = self._run(flag=True)
        obs = [o for o in result.observations if o.get("type") == "mitre_contextualization"]
        self.assertEqual(len(obs), 1)
        self.assertIn("counts", obs[0])
        md = render_markdown(result)
        self.assertIn("Contextualização MITRE ATT&CK", md)

    def test_flag_off_attaches_nothing(self):
        result = self._run(flag=False)
        obs = [o for o in result.observations if o.get("type") == "mitre_contextualization"]
        self.assertEqual(obs, [])
        self.assertNotIn("Contextualização MITRE ATT&CK", render_markdown(result))


if __name__ == "__main__":
    unittest.main()
