"""Demonstração E2E segura da PoC (Fase 8) — cenários A/B/C + MITRE ATT&CK.

Esta demonstração **reusa os componentes reais** do pipeline (OrchestratorV2,
CVE intelligence, LaboratoryManager sobre ``InProcessContainerManager``,
EvidenceValidator → ReflectionAgent → DecisionValidator e a contextualização
MITRE ATT&CK). Somente o transporte do alvo e a pesquisa de advisories públicos
são substituídos por *fixtures locais* — nenhuma rede, nenhum Docker real e
nenhuma execução de técnica de ataque.

Cenários (``subject_type == hypothesis``):
  * A — ``supported``     → hipótese sustentada (estado final ``potential``)
  * B — ``contradicted``  → hipótese contradita por evidência (``rejected``)
  * C — ``inconclusive``  → evidência insuficiente (``inconclusive``)

Uso:
    PYTHONPATH=.:tests python demo/poc_final_demo.py [diretório_de_saída]

Cada cenário imprime um resumo verificável e grava o relatório Markdown. O flag
``PENTEST_MITRE_ATTACK`` é ligado para anexar a camada de contextualização.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "tests"))

# Reuso explícito dos componentes reais + fixtures locais (offline, sem Docker).
from email.message import Message  # noqa: E402
from unittest.mock import patch  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402

from test_phase7_integration import campaign  # noqa: E402
from pentest_pipeline import run_scan  # noqa: E402
from pentest_pipeline.report import render_markdown  # noqa: E402
from pentest_pipeline.scope import ScopeConfig  # noqa: E402
from pentest_pipeline.transport import Response  # noqa: E402
from phase65_fixtures import ControlledReflection  # noqa: E402

SCENARIOS = (
    ("A", "supported", "hipótese sustentada", "potential"),
    ("B", "contradicted", "hipótese contradita por evidência", "rejected"),
    ("C", "inconclusive", "evidência insuficiente", "inconclusive"),
)


def _mitre_summary(data: dict) -> str:
    obs = next((o for o in data.get("observations", [])
                if o.get("type") == "mitre_contextualization"), None)
    if not obs:
        return "MITRE: não anexado"
    counts = obs.get("counts", {})
    return (f"MITRE: aplicáveis={counts.get('mapped', 0)} "
            f"candidatas={counts.get('candidate', 0)} "
            f"não-mapeadas={counts.get('unmapped', 0)}")


def _mitre_showcase() -> None:
    """Exercita os três estados MITRE (mapped/candidate/unmapped) via run_scan."""

    def _resp(url, status, body=b"", ct="text/html", **headers):
        msg = Message()
        msg["Content-Type"] = ct
        for name, value in headers.items():
            msg[name.replace("_", "-")] = value
        return Response(url, status, msg, body, False, 1)

    class _T:
        def __init__(self, cfg, **kw):
            self.config = cfg
            self.actions: list[dict] = []
            self.on_event = kw.get("on_event")
            self.request_count = 0

        def request(self, url, *, method="GET", phase="test"):
            self.config.assert_request(url, method)
            self.request_count += 1
            path = urlsplit(url).path
            if path == "/":
                return _resp(url, 200, b"<html>Home</html>", Set_Cookie="sid=abc123")
            return _resp(url, 404)

        def record(self, type_, phase, message, **details):
            event = {"type": type_, "phase": phase, "message": message, **details}
            self.actions.append(event)
            if self.on_event:
                self.on_event(event)

    cfg = ScopeConfig.for_target_url("https://fixture.example/#/")
    with patch("pentest_pipeline.pipeline.BoundedTransport", side_effect=lambda c, **k: _T(c, **k)), \
            patch("socket.create_connection",
                  side_effect=AssertionError("Sem rede na demonstração")):
        result = run_scan(cfg)
    obs = next((o for o in result.to_dict()["observations"]
                if o.get("type") == "mitre_contextualization"), None)
    print("[MITRE] Demonstração dos estados de mapeamento (via run_scan)")
    if obs:
        for m in obs["mappings"]:
            tech = m.get("technique_id") or "—"
            print(f"    {m['mapping_status']:<9} {tech:<10} {m['finding_id']}")
    print()


def run(out_dir: str | None = None) -> int:
    out = Path(out_dir or (_BACKEND / "demo" / "out"))
    out.mkdir(parents=True, exist_ok=True)
    os.environ["PENTEST_MITRE_ATTACK"] = "enabled"
    print(f"== PoC Na Mira — demonstração E2E segura (saída: {out}) ==\n")
    ok = True
    for label, scenario, descricao, esperado in SCENARIOS:
        result = campaign(scenario, provider=ControlledReflection())
        data = result.to_dict()
        conclusion = next((c for c in data.get("conclusions", [])
                           if c["subject_type"] == "hypothesis"), None)
        got = conclusion["current_status"] if conclusion else "ausente"
        status = "OK" if got == esperado else "DIVERGENTE"
        if got != esperado:
            ok = False
        md = render_markdown(data)
        report_path = out / f"cenario_{label}_{scenario}.md"
        report_path.write_text(md, encoding="utf-8")
        print(f"[{label}] {descricao}")
        print(f"    hipótese: {got} (esperado: {esperado}) -> {status}")
        print(f"    {_mitre_summary(data)}")
        print(f"    relatório: {report_path}")
        print(f"    contém seção MITRE: {'Contextualização MITRE ATT&CK' in md}")
        print()
    _mitre_showcase()
    print("Resultado geral:", "OK" if ok else "DIVERGENTE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1] if len(sys.argv) > 1 else None))
