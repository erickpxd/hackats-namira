"""Regression: local computations cannot masquerade as reproduced vulnerabilities."""
from copy import deepcopy
from dataclasses import replace
import os
from unittest import TestCase
from unittest.mock import patch

from pentest_pipeline.contracts import AffectedRange, CveRecord, TechnologyComponent
from pentest_pipeline.intelligence.correlation import CveCorrelationEngine
from pentest_pipeline.execution.laboratory_operations import correlate_local_version
from pentest_pipeline.execution.container_manager import InProcessContainerManager
from pentest_pipeline.orchestration.orchestrator import OrchestratorV2
from pentest_pipeline.orchestration.execution_history import execution_history, hypothesis_history
from pentest_pipeline.orchestration.verification_summary import present_execution, verification_summary
from pentest_pipeline.validation.evidence_validator import EvidenceValidator
from pentest_pipeline.report import render_markdown
from test_phase65_acceptance import fixture_transport, _cfg


class ProductIdentityTests(TestCase):
    component = TechnologyComponent('tech:angular', 'Angular', '@angular/core', 'npm',
                                    version='22.2.2', version_confidence='exact', identification_status='exact')

    def check(self, ranges):
        record = CveRecord('CVE-2099-1001', 'fixture', affected=tuple(ranges))
        return (CveCorrelationEngine().correlate(self.component, record),
                correlate_local_version({'component': self.component.to_dict(), 'record': record.to_dict()}))

    def test_other_product_cannot_confirm_or_reject_a_cve_by_version(self):
        for fixed in ('1.6.32', '99.0.0'):
            with self.subTest(fixed=fixed):
                correlation, local = self.check([AffectedRange(product='cloud_foundry_elastic_runtime', fixed=fixed)])
                self.assertEqual(correlation.status, 'inconclusive')
                self.assertEqual(local['validation_status'], 'inconclusive')
                self.assertEqual(local['reason_code'], 'product_mismatch')

    def test_substring_is_not_package_identity(self):
        for name in ('@angular/core-utils', 'angular'):
            correlation, local = self.check([AffectedRange(product=name, ecosystem='npm', fixed='99.0.0')])
            self.assertEqual(correlation.status, 'inconclusive')
            self.assertEqual(local['reason_code'], 'product_mismatch')

    def test_ecosystem_must_match(self):
        for ecosystem, reason in ((None, 'ecosystem_unknown'), ('PyPI', 'ecosystem_mismatch')):
            correlation, local = self.check([AffectedRange(product='@angular/core', ecosystem=ecosystem, fixed='99.0.0')])
            self.assertEqual(correlation.status, 'inconclusive')
            self.assertEqual(local['reason_code'], reason)
        component = replace(self.component, ecosystem=None)
        record = CveRecord('CVE-2099-1001', 'fixture', affected=(AffectedRange(product='@angular/core', fixed='99.0.0'),))
        self.assertEqual(CveCorrelationEngine().correlate(component, record).status, 'inconclusive')
        local = correlate_local_version({'component': component.to_dict(), 'record': record.to_dict()})
        self.assertEqual(local['reason_code'], 'ecosystem_unknown')

    def test_mixed_advisory_uses_only_matching_package_ranges(self):
        correlation, local = self.check([
            AffectedRange(product='unrelated', ecosystem='npm', fixed='99.0.0'),
            AffectedRange(product='@angular/core', ecosystem='npm', fixed='22.0.0')])
        self.assertEqual(correlation.status, 'not_affected')
        self.assertEqual(local['validation_status'], 'contradicted')


class ProjectionTests(TestCase):
    def row(self, **kw):
        return dict(execution_id='exec', operation_id='correlate_local_version', execution_status='completed',
                    worker_responded=True, execution_backend='docker', hypothesis_id='h',
                    validation_status='inconclusive', output_evidence_refs=['e'], **kw)

    def test_historical_mismatch_is_explained_without_mutating_evidence(self):
        catalog = [{'evidence_id': 'e', 'normalized_name': '@angular/core', 'technology': 'Angular',
                    'version': '22.2.2', 'criteria': [{'product': 'cloud_foundry_elastic_runtime'}]}]
        original = deepcopy(catalog)
        presentation = present_execution(self.row(), catalog)
        self.assertEqual(presentation['headline'], 'Comparação local concluída')
        self.assertEqual(presentation['outcome'], 'O aviso descreve outro produto')
        self.assertIn('Angular 22.2.2', presentation['explanation'])
        self.assertEqual(catalog, original)

    def test_completed_stage_is_internal_processing_not_local_check(self):
        row = present_execution({'operation_id': 'triage', 'execution_status': 'completed'}, [])
        self.assertEqual(row['kind'], 'internal_step')
        self.assertFalse(row['local_result_received'])

    def test_no_response_and_no_start_do_not_claim_completed_checks(self):
        row = self.row()
        row['worker_responded'] = False
        self.assertFalse(present_execution(row, [])['local_result_received'])
        for status in ('skipped', 'planned', 'cancelled'):
            row['execution_status'] = status
            self.assertEqual(present_execution(row, [])['headline'], 'Não realizada')

    def test_summary_separates_http_simulations_and_completed_data_checks(self):
        data = {'actions': [{'type': 'request'}, {'type': 'response'}],
                'observations': [{'type': 'vulnerability_intelligence', 'hypotheses': [{}, {}]}]}
        rows = [self.row(), {**self.row(), 'execution_backend': 'simulated'},
                {**self.row(), 'worker_responded': False}]
        for row in rows:
            row['presentation'] = present_execution(row, [])
        summary = verification_summary(data, rows)
        self.assertEqual(summary['target_responses'], 1)
        self.assertEqual(summary['local_checks_completed'], 1)
        self.assertEqual(summary['hypotheses_compared'], 1)
        self.assertEqual(summary['hypotheses_total'], 2)
        self.assertEqual(summary['kali_execution'], 'not_recorded')
        self.assertEqual(summary['vulnerability_reproductions'], 0)

    def test_wording_does_not_change_evidence_fingerprint(self):
        validator = EvidenceValidator()
        subject, catalog, rows = {'evidence_refs': ['e']}, [{'evidence_id': 'e', 'execution_id': 'exec'}], [self.row()]
        before = validator.fingerprint(subject, catalog, rows)
        rows[0]['presentation'] = present_execution(rows[0], catalog)
        self.assertEqual(before, validator.fingerprint(subject, catalog, rows))

    def test_markdown_distinguishes_activity_and_hides_audit(self):
        md = render_markdown({'actions': [{'type': 'request'}, {'type': 'response'}]})
        self.assertIn('Respostas HTTP do alvo: 1', md)
        self.assertIn('Execução de ferramentas no Kali: não registrada', md)
        self.assertIn('<summary>Eventos, requisições e hashes</summary>', md)
        self.assertEqual(md.count('<details>'), md.count('</details>'))


class SelectionTests(TestCase):
    def test_unrelated_hits_do_not_consume_the_three_comparison_budget(self):
        class Research:
            def research(self, components):
                return {'coverage': 'full', 'providers_ok': ['fixture'], 'providers_failed': [], 'failures': [],
                    'records': {c.component_id: [{'vulnerability_id': f'CVE-2099-100{i}', 'source': 'fixture',
                        'affected': [{'product': 'other' if i < 3 else c.normalized_name,
                                     'ecosystem': c.ecosystem, 'fixed': '99.0.0'}]} for i in range(7)] for c in components}}
        with patch.dict(os.environ, {'PENTEST_LABORATORY': 'enabled'}), patch(
                'pentest_pipeline.orchestration.orchestrator.BoundedTransport', side_effect=fixture_transport), patch(
                'pentest_pipeline.orchestration.executors_laboratory.DockerContainerManager', return_value=InProcessContainerManager()):
            data = OrchestratorV2(cve_intelligence=True, cve_service=Research()).run(_cfg()).to_dict()
        rows = [e for e in execution_history(data['execution_events'], data) if e['hypothesis_id']]
        self.assertEqual(len(rows), 3)
        compared = {r['hypothesis_id'] for r in rows}
        hypotheses = hypothesis_history(data, data['execution_events'])
        self.assertEqual({h['vulnerability_id'] for h in hypotheses if h['hypothesis_id'] in compared},
                         {'CVE-2099-1003', 'CVE-2099-1004', 'CVE-2099-1005'})
        skipped = [e for e in data['execution_events'] if e['event_type'] == 'laboratory_hypothesis_skipped']
        self.assertEqual([e['reason'] for e in skipped].count('product_mismatch'), 3)
        self.assertEqual([e['reason'] for e in skipped].count('campaign_validation_limit'), 1)
        self.assertTrue(all(h.get('verification_note') for h in hypotheses if h['hypothesis_id'] not in compared))
