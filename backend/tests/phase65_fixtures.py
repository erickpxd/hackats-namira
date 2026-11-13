"""Local data fixtures for the real Docker/API/browser acceptance flow.

Only target transport and public advisory research are replaced. Registry,
policy, scheduler, Docker, events, checkpoint and console persistence are real.
"""
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch
from contextlib import nullcontext

from pentest_pipeline.orchestration.entry import run_campaign
from pentest_pipeline.scope import ScopeConfig
from pentest_pipeline.web_server import CampaignConsole
from test_orchestrator_v2_integration import FakeTransport, _responses, resp

SCENARIOS = ("supported", "contradicted", "inconclusive", "failed", "unverified")


class FixturePriorCorrelation:
    """Deliberately weak initial conclusion; independent worker/matcher stay real."""
    def correlate(self, component, record):
        from pentest_pipeline.contracts import CorrelationResult
        return CorrelationResult(component.component_id, record.vulnerability_id,
            'potentially_affected', 'weak', ('Conclusão inicial de fixture; exige verificação independente.',))


class ControlledReflection:
    """Structured model fixture; includes an intentionally unjustified promotion."""
    def reflect(self, payload):
        v = payload['validation']
        status = {'supported': 'potential', 'contradicted': 'rejected'}.get(v['status'], 'inconclusive')
        if payload['subject_type'] == 'finding' and v['sufficient_for_confirmation']:
            status = 'confirmed'
        if payload['subject_type'] == 'hypothesis' and v['status'] == 'insufficient_evidence' and v['valid_evidence_refs']:
            status = 'confirmed'  # DecisionValidator must reject, despite valid JSON and a real worker.
        return {'subject_id': payload['subject_id'], 'suggested_status': status,
                'reasoning_summary': 'Proposta controlada da fixture, sujeita aos critérios independentes.',
                'evidence_refs': list(v['valid_evidence_refs']),
                'contradictions': list(v['contradicting_evidence_refs']), 'missing_information': [],
                'recommended_action': 'none', 'recommended_task_id': None}


class LocalAdvisories:
    def __init__(self, scenario):
        self.scenario = scenario

    def research(self, components):
        records = {}
        for c in components:
            affected = {"product": c.normalized_name, "ecosystem": c.ecosystem,
                        "introduced": "13.0.0", "fixed": "14.0.0" if self.scenario == "contradicted" else "15.0.0"}
            if self.scenario == "failed":
                # Malformed local advisory: the registered worker returns a
                # structured operation failure. Docker itself is never mocked.
                affected["versions"] = [123]
            records[c.component_id] = [{"vulnerability_id": "CVE-2099-6501", "source": "fixture-local",
                                        "title": "Aviso fictício para aceite local", "affected": [affected]}]
        return {"coverage": "complete", "providers_ok": ["fixture-local"],
                "providers_failed": [], "failures": [], "records": records}


def generate_campaign(directory, scenario, *, phase7=False):
    assert scenario in SCENARIOS
    # Fail explicitly if the image is absent; never pull a substitute image.
    subprocess.run(["docker", "image", "inspect", "namira/worker:local"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    config_path = directory / "scope.json"
    config_path.write_text(json.dumps({"target_url": "https://fixture.example/",
                                       "allowed_hosts": ["fixture.example"]}))
    config = ScopeConfig.from_file(config_path)

    def transport(cfg, **kw):
        responses = _responses(cfg)
        body = (b'<html ng-app="fixture">Fixture</html>' if scenario == "inconclusive" else
                b'<html ng-version="14.0.0">Fixture</html>')
        responses[("GET", "/")] = resp(cfg.target_url, 200, body)
        return FakeTransport(cfg, responses=responses, **kw)

    def run(cfg, **kwargs):
        return run_campaign(cfg, orchestrator="v2", cve_service=LocalAdvisories(scenario),
                            independent_validation=phase7,
                            reflection_provider=ControlledReflection() if phase7 else None, **kwargs)

    environment = {"PENTEST_ORCHESTRATOR": "v2", "PENTEST_CVE_INTELLIGENCE": "1",
                   "PENTEST_LABORATORY": "disabled" if scenario == "unverified" else "enabled",
                   "PENTEST_AI_PLANNING": "disabled", "PENTEST_CONTAINER_EXECUTION": "disabled",
                   "PENTEST_REFLECTION_PROVIDER": ""}
    initial_correlation = (patch('pentest_pipeline.orchestration.executors_intelligence.CveCorrelationEngine',
                                FixturePriorCorrelation) if phase7 and scenario == 'contradicted' else nullcontext())
    with patch.dict(os.environ, environment), patch("pentest_pipeline.web_server.REPORTS", directory / "reports"), \
         patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=transport), \
         patch("pentest_pipeline.web_server.run_campaign", side_effect=run), \
         patch("socket.create_connection", side_effect=AssertionError("External connections forbidden in fixture campaign")), initial_correlation:
        console = CampaignConsole(config_path)
        started, message = console.start(config=config)
        assert started, message
        console.worker.join(40)
        if console.worker.is_alive():
            console.stop()
            console.worker.join(15)
            raise AssertionError("Fixture campaign exceeded its deadline")
        assert console.error is None, console.error
        payload = console.snapshot()
        assert payload["hypotheses"], "Fixture must register a hypothesis"
        validations = [e for e in payload["executions"] if e["hypothesis_id"]]
        if scenario == "unverified":
            assert not validations
        else:
            assert len(validations) == 1, validations
            row = validations[0]
            assert row["execution_backend"] == "docker", row
            assert row["worker_responded"] is True, row
            assert row["authorization_status"] == "approved", row
            assert row["execution_status"] == ("failed" if scenario == "failed" else "completed"), row
            assert row["validation_status"] == ("not_evaluated" if scenario == "failed" else scenario), row
        review = {}
        if phase7:
            conclusion = next(c for c in payload['conclusions'] if c['subject_type'] == 'hypothesis')
            revision = conclusion['revisions'][0]['revision']
            assert conclusion['current_status'] == {'supported': 'potential', 'contradicted': 'rejected',
                'inconclusive': 'inconclusive', 'failed': 'inconclusive', 'unverified': 'inconclusive'}[scenario], conclusion
            if scenario == 'contradicted':
                assert conclusion['initial_status'] == 'potential'
                assert revision['accepted'] is True
            if scenario == 'inconclusive':
                assert revision['proposed_status'] == 'confirmed' and revision['accepted'] is False
            review = {'revision_id': revision['revision_id'], 'current_status': conclusion['current_status']}
        return {"scenario": scenario, "run_id": payload["result"]["run_id"], **review,
                "execution_id": validations[0]["execution_id"] if validations else None,
                "hypothesis_id": payload["hypotheses"][0]["hypothesis_id"]}
