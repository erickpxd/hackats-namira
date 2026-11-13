"""Independent validation tests: no network, credentials or external providers."""
import copy
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pentest_pipeline.contracts import ContractError, TaskDefinition, ExecutionPlan
from pentest_pipeline.contracts.validation import ReflectionResult
from pentest_pipeline.validation.evidence_validator import EvidenceValidator, seal
from pentest_pipeline.validation.finding_classifier import FindingClassifier
from pentest_pipeline.validation.reflection_agent import ReflectionAgent
from pentest_pipeline.validation.decision_validator import DecisionValidator
from pentest_pipeline.validation.service import ReviewService
from pentest_pipeline.validation.history import conclusion_history
from pentest_pipeline.validation.revalidation import consider_revalidation
from pentest_pipeline.planning.replanning_policy import ReplanningPolicy
from pentest_pipeline.orchestration.orchestrator import build_registry

T0, T1, T2 = ('2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00', '2026-01-01T00:00:02+00:00')


def fixture(verdict='supported', *, finding=False):
    subject = {'subject_id': 'h', 'subject_type': 'hypothesis', 'campaign_id': 'c',
               'component_id': 'tech:@angular/core', 'vulnerability_id': 'CVE-FIXTURE',
               'original_status': 'candidate', 'created_at': T0, 'evidence_refs': ['e']}
    evidence = {'evidence_id': 'e', 'source': 'laboratory', 'campaign_id': 'c', 'hypothesis_id': 'h',
        'task_id': 'laboratory_validation', 'execution_id': 'exec', 'worker_id': 'lab',
        'created_at': T1, 'operation_id': 'correlate_local_version', 'technology': 'Angular',
        'normalized_name': '@angular/core', 'ecosystem': 'npm', 'version': '14.0.0', 'certainty': 'exact',
        'vulnerability_id': 'CVE-FIXTURE', 'source_refs': ['fixture'], 'validation_status': verdict,
        'criteria': [{'product': '@angular/core', 'ecosystem': 'npm', 'introduced': '13.0.0',
                      'fixed': '14.0.0' if verdict == 'contradicted' else '15.0.0'}]}
    if verdict == 'inconclusive':
        evidence['version'], evidence['certainty'] = None, 'unknown'
    execution = {'campaign_id': 'c', 'task_id': 'laboratory_validation', 'execution_id': 'exec',
        'worker_id': 'lab', 'hypothesis_id': 'h', 'operation_id': 'correlate_local_version',
        'execution_status': 'completed', 'validation_status': verdict, 'worker_responded': True,
        'authorization_status': 'approved', 'output_evidence_refs': ['e'], 'started_at': T0, 'finished_at': T1}
    if finding:
        subject.update(subject_type='finding', original_status='inconclusive', check='missing_csp')
        evidence = {'evidence_id': 'e', 'source': 'response_metadata', 'campaign_id': 'c', 'finding_id': 'h',
            'task_id': 'header_cookie_checks', 'execution_id': 'exec', 'created_at': T1, 'check': 'missing_csp',
            'observation': {'status': 200, 'mime': 'text/html', 'headers': {'Content-Security-Policy':
                'present' if verdict == 'contradicted' else 'empty' if verdict == 'inconclusive' else 'absent'}}}
        execution.update(task_id='header_cookie_checks')
    return subject, [seal(evidence)], [execution]


def validate(subject, catalog, executions):
    return EvidenceValidator().validate(subject, campaign_id='c', catalog=catalog, executions=executions, as_of=T2)


def proposal(subject, validation, status='potential', **changes):
    return replace(ReflectionResult('r', subject['subject_id'], 'suspected', status, 'Resumo controlado.',
                   validation.valid_evidence_refs, decision_source='ai'), **changes)


class EvidenceValidatorTests(unittest.TestCase):
    def test_valid_integrity_is_distinct_from_sufficiency(self):
        s, c, e = fixture('inconclusive')
        v = validate(s, c, e)
        self.assertEqual(v.integrity_status, 'valid')
        self.assertEqual(v.status, 'insufficient_evidence')
        self.assertFalse(v.sufficient_for_confirmation)

    def test_supported_local_cve_cannot_confirm_target(self):
        v = validate(*fixture())
        self.assertEqual(v.status, 'supported')
        self.assertFalse(v.sufficient_for_confirmation)

    def test_hash_mismatch(self):
        s, c, e = fixture(); c[0]['version'] = '99.0.0'
        v = validate(s, c, e)
        self.assertEqual(v.status, 'unsupported')
        self.assertIn('sha256_mismatch', v.validation_rules)

    def test_missing_is_not_contradiction(self):
        s, c, e = fixture(); s['evidence_refs'] = ['missing']
        v = validate(s, c, e)
        self.assertEqual(v.status, 'insufficient_evidence')
        self.assertEqual(v.missing_evidence_refs, ('missing',))
        self.assertFalse(v.contradicting_evidence_refs)

    def test_cross_campaign_subject_execution_and_source_rejected(self):
        for field, value in [('campaign_id', 'other'), ('hypothesis_id', 'other'),
                             ('execution_id', 'other'), ('source', 'untrusted'), ('worker_id', 'other')]:
            with self.subTest(field=field):
                s, c, e = fixture(); raw = {k:v for k,v in c[0].items() if k != 'sha256'}
                raw[field] = value; c[0] = seal(raw)
                self.assertEqual(validate(s, c, e).status, 'unsupported')

    def test_duplicates_do_not_inflate_support(self):
        s, c, e = fixture(); s['evidence_refs'] *= 2; c *= 2
        v = validate(s, c, e)
        self.assertEqual(v.supporting_evidence_refs, ('e',))
        self.assertIn('duplicate_evidence_deduplicated', v.validation_rules)

    def test_conflicting_duplicate_invalid(self):
        s, c, e = fixture(); c.append({**c[0], 'version': '12.0.0'})
        self.assertEqual(validate(s, c, e).status, 'unsupported')

    def test_documented_contradiction(self):
        v = validate(*fixture('contradicted'))
        self.assertEqual(v.status, 'contradicted')
        self.assertEqual(v.contradicting_evidence_refs, ('e',))

    def test_criterion_does_not_match_claim(self):
        s, c, e = fixture(); raw = {k:v for k,v in c[0].items() if k != 'sha256'}
        raw['version'] = '16.0.0'; c[0] = seal(raw)
        self.assertIn('criterion_observation_mismatch', validate(s, c, e).validation_rules)

    def test_valid_hash_does_not_validate_provenance_or_criteria(self):
        s, c, e = fixture(); raw = {k:v for k,v in c[0].items() if k != 'sha256'}
        raw['campaign_id'] = 'other'; c[0] = seal(raw)
        v = validate(s, c, e)
        self.assertEqual(v.integrity_status, 'valid')
        self.assertEqual(v.status, 'unsupported')
        self.assertFalse(v.valid_evidence_refs)

    def test_future_missing_or_naive_timestamp(self):
        for value in ['2099-01-01T00:00:00+00:00', 'bad', T0.removesuffix('+00:00')]:
            with self.subTest(value=value):
                s, c, e = fixture(); raw = {k:v for k,v in c[0].items() if k != 'sha256'}
                raw['created_at'] = value; c[0] = seal(raw)
                self.assertIn('temporal_mismatch', validate(s, c, e).validation_rules)

    def test_completed_worker_without_authorization_rejected(self):
        s, c, e = fixture(); e[0]['authorization_status'] = 'denied'
        self.assertEqual(validate(s, c, e).status, 'unsupported')

    def test_opposing_observations_remain_conflicted(self):
        s, c, e = fixture(); _, opposite, second_exec = fixture('contradicted')
        raw = {k:v for k,v in opposite[0].items() if k != 'sha256'}
        raw.update(evidence_id='opposite', execution_id='exec2')
        second_exec[0].update(execution_id='exec2', output_evidence_refs=['opposite'])
        s['evidence_refs'].append('opposite')
        v = validate(s, c + [seal(raw)], e + second_exec)
        self.assertEqual(v.status, 'partially_supported')
        self.assertEqual(FindingClassifier().classify(s, v), 'inconclusive')


class ClassificationTests(unittest.TestCase):
    def test_explicit_legacy_mapping(self):
        for before, after in [('candidate', 'suspected'), ('potentially_affected', 'potential'),
                              ('discarded', 'rejected'), ('version_unknown', 'inconclusive')]:
            self.assertEqual(FindingClassifier().initial({'original_status': before}), after)

    def test_partial_evidence_potential(self):
        s, c, e = fixture(); s['evidence_refs'].append('missing')
        self.assertEqual(FindingClassifier().classify(s, validate(s, c, e)), 'potential')

    def test_header_criterion_confirmed_but_unknown_category_not(self):
        s, c, e = fixture(finding=True)
        self.assertEqual(FindingClassifier().classify(s, validate(s, c, e)), 'confirmed')
        s['check'] = 'source_map_reference'
        self.assertEqual(FindingClassifier().classify(s, validate(s, c, e)), 'inconclusive')

    def test_absence_and_opposite_header(self):
        for verdict, expected in [('contradicted', 'rejected'), ('inconclusive', 'inconclusive')]:
            s, c, e = fixture(verdict, finding=True)
            self.assertEqual(FindingClassifier().classify(s, validate(s, c, e)), expected)


class ReflectionTests(unittest.TestCase):
    def reflect(self, provider=None, verdict='supported'):
        s, c, e = fixture(verdict)
        return ReflectionAgent(provider).reflect(s, validate(s, c, e), current_status='suspected',
                                                  allowed_task_ids=['laboratory_validation'])

    def test_deterministic_supported_and_false_positive(self):
        self.assertEqual(self.reflect().suggested_status, 'potential')
        r = self.reflect(verdict='contradicted')
        self.assertEqual(r.suggested_status, 'rejected')
        self.assertIn('falso positivo', r.reasoning_summary)

    def test_insufficient_recommends_allowed_local_task(self):
        r = self.reflect(verdict='inconclusive')
        self.assertEqual(r.recommended_task_id, 'laboratory_validation')
        self.assertEqual(r.suggested_status, 'inconclusive')

    def test_provider_failure_fallback_hides_error_message(self):
        r = self.reflect(Mock(reflect=Mock(side_effect=RuntimeError('secret-token'))))
        self.assertEqual(r.decision_source, 'deterministic')
        self.assertEqual(r.fallback_reason, 'RuntimeError')
        self.assertNotIn('secret-token', str(r.to_dict()))

    def test_malformed_unknown_task_fabrication_fall_back(self):
        base = {'subject_id': 'h', 'suggested_status': 'potential', 'reasoning_summary': 'Resumo',
                'evidence_refs': ['e'], 'contradictions': [], 'missing_information': [],
                'recommended_action': 'none', 'recommended_task_id': None}
        for extra in [{'unexpected': 'command'}, {'evidence_refs': ['fabricated']},
                      {'recommended_action': 'request_local_verification', 'recommended_task_id': 'shell'},
                      {'contradictions': ['e']}, {'suggested_status': 'super-confirmed'}]:
            with self.subTest(extra=extra):
                result = self.reflect(Mock(reflect=Mock(return_value={**base, **extra})))
                self.assertEqual(result.decision_source, 'deterministic')
                self.assertEqual(result.fallback_reason, 'ContractError')

    def test_model_call_budget_is_bounded(self):
        provider = Mock(reflect=Mock(side_effect=TimeoutError()))
        agent = ReflectionAgent(provider, max_calls=1)
        s, c, e = fixture()
        for _ in range(3):
            agent.reflect(s, validate(s, c, e), current_status='suspected')
        self.assertEqual(provider.reflect.call_count, 1)


class DecisionTests(unittest.TestCase):
    def decide(self, verdict='supported', status='potential', **changes):
        s, c, e = fixture(verdict); v = validate(s, c, e)
        return DecisionValidator().validate(s, v, proposal(s, v, status, **changes), current_status='suspected')

    def test_valid_transition(self):
        decision = self.decide()
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.decision_source, 'deterministic')
        self.assertEqual(decision.proposal_source, 'ai')

    def test_hypothesis_never_confirmed_even_with_supported_worker(self):
        result = self.decide(status='confirmed')
        self.assertFalse(result.accepted)
        self.assertEqual(result.approved_status, 'suspected')

    def test_insufficient_ai_confirmation_rejected(self):
        self.assertFalse(self.decide('inconclusive', 'confirmed').accepted)

    def test_missing_or_invented_reference_rejected(self):
        self.assertFalse(self.decide(evidence_refs=()).accepted)
        self.assertFalse(self.decide(evidence_refs=('invented',)).accepted)

    def test_stale_or_invalid_transition_rejected(self):
        self.assertFalse(self.decide(original_status='confirmed').accepted)
        self.assertFalse(self.decide(status='invalid').accepted)

    def test_empty_justification_rejected(self):
        self.assertFalse(self.decide(reasoning_summary='').accepted)

    def test_duplicate_or_excessive_revision_rejected(self):
        s, c, e = fixture(); v = validate(s, c, e); r = proposal(s, v)
        first = DecisionValidator().validate(s, v, r, current_status='suspected')
        second = DecisionValidator().validate(s, v, r, current_status='suspected', history=[first.to_dict()])
        self.assertFalse(second.accepted)
        self.assertIn('repetição', second.reason)
        limited = DecisionValidator().validate(s, v, r, current_status='suspected', history=[first.to_dict()] * 3)
        self.assertFalse(limited.accepted)

    def test_contradiction_can_reject(self):
        self.assertEqual(self.decide('contradicted', 'rejected').approved_status, 'rejected')


class ReviewCycleTests(unittest.TestCase):
    def test_repeat_is_skipped_before_model_and_original_is_unchanged(self):
        s, c, e = fixture('contradicted'); original = copy.deepcopy((s, c, e))
        service = ReviewService(); records, events = [], []
        record = service.review(s, catalog=c, executions=e, records=records, emit=events.append, task_id='review')
        records.append(record)
        with patch.object(service.reflection, 'reflect', side_effect=AssertionError('Must not reflect twice')):
            self.assertIsNone(service.review(s, catalog=c, executions=e, records=records, emit=events.append, task_id='review'))
        self.assertEqual((s, c, e), original)
        projected = conclusion_history({'observations': records})[0]
        self.assertEqual(projected['initial_status'], 'suspected')
        self.assertEqual(projected['current_status'], 'rejected')
        self.assertEqual(len(projected['revisions']), 1)
        self.assertTrue(any(x['type'] == 'hypothesis_revised' for x in events))

    def test_new_data_creates_second_version_without_erasing_first(self):
        s, c, e = fixture('inconclusive'); service = ReviewService(); records = []
        records.append(service.review(s, catalog=c, executions=e, records=records, emit=lambda _: None, task_id='review'))
        s2, c2, e2 = fixture('contradicted')
        records.append(service.review(s2, catalog=c2, executions=e2, records=records, emit=lambda _: None, task_id='review'))
        conclusion = conclusion_history({'observations': records})[0]
        self.assertEqual([r['revision']['version'] for r in conclusion['revisions']], [1, 2])
        self.assertEqual(conclusion['revisions'][0]['revision']['approved_status'], 'inconclusive')
        self.assertEqual(conclusion['current_status'], 'rejected')

    def test_legacy_has_no_fabricated_review(self):
        self.assertEqual(conclusion_history({'findings': [{'id': 'old', 'status': 'confirmed'}]}), [])


class RevalidationTests(unittest.TestCase):
    def request(self, **kwargs):
        from test_orchestrator_v2_integration import _cfg
        task = TaskDefinition('laboratory_validation', 'laboratory_validation', 'laboratory_validation', optional=True,
                              requires_approval=kwargs.get('approval', False))
        states = {'laboratory_validation': kwargs.get('state', 'completed')}
        ctx = SimpleNamespace(config=_cfg(), campaign=SimpleNamespace(campaign_id='c'),
            transport=SimpleNamespace(request_count=kwargs.get('requests', 0)), is_cancelled=kwargs.get('cancelled', False),
            get=lambda key, default=None: states if key == 'task_states' else default)
        return consider_revalidation(kwargs.get('task', task.task_id), subject_id='h', context=ctx,
            plan=ExecutionPlan('p', 1, (task,)), registry=build_registry(), policy=ReplanningPolicy())

    def test_finished_task_not_reexecuted(self):
        result = self.request()
        self.assertFalse(result['executed'])
        self.assertIn('ja_concluida', result['reasons'])

    def test_pending_local_task_is_only_deferred(self):
        self.assertEqual(self.request(state='pending')['status'], 'deferred')

    def test_scope_budget_stop_approvals_and_catalog_gates(self):
        for kwargs in [{'requests': 999}, {'cancelled': True}, {'approval': True}, {'task': 'shell'}]:
            with self.subTest(kwargs=kwargs):
                result = self.request(state='pending', **kwargs)
                self.assertEqual(result['status'], 'rejected_for_current_campaign')
                self.assertFalse(result['executed'])

    def test_terminal_dependencies_restricted_to_reviewer(self):
        with self.assertRaises(ContractError):
            TaskDefinition('x', 'surface_checks', 'surface_checks', dependency_policy='terminal').validate()
