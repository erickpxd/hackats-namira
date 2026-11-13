"""DAG/review/checkpoint/provider integration using local transport and model fixtures."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from contextlib import nullcontext

from pentest_pipeline.execution.container_manager import InProcessContainerManager, ContainerError
from pentest_pipeline.orchestration.orchestrator import OrchestratorV2, build_registry
from pentest_pipeline.orchestration.execution_history import execution_history
from pentest_pipeline.orchestration.event_store import EventStore
from pentest_pipeline.persistence import CheckpointStore
from pentest_pipeline.report import render_markdown
from pentest_pipeline.validation.history import conclusion_history
from pentest_pipeline.validation.providers import OpenAIReflectionProvider, BedrockReflectionProvider
from pentest_pipeline.validation.reflection_agent import ReflectionAgent
from test_orchestrator_v2_integration import FakeTransport, _cfg, _responses, resp
from test_independent_validation import fixture, validate
from phase65_fixtures import LocalAdvisories, ControlledReflection, FixturePriorCorrelation, generate_campaign


def campaign(scenario='contradicted', *, store=None, provider=None, manager=None, enabled=True, ai_planning=False, stop=None):
    def transport(cfg, **kwargs):
        responses = _responses(cfg)
        body = b'<html ng-app="fixture">Fixture</html>' if scenario == 'inconclusive' else b'<html ng-version="14.0.0">Fixture</html>'
        responses[('GET', '/')] = resp(cfg.target_url, 200, body)
        return FakeTransport(cfg, responses=responses, **kwargs)
    initial = patch('pentest_pipeline.orchestration.executors_intelligence.CveCorrelationEngine', FixturePriorCorrelation) if scenario == 'contradicted' else nullcontext()
    with patch.dict(os.environ, {'PENTEST_LABORATORY': 'enabled', 'PENTEST_REFLECTION_PROVIDER': ''}), initial, \
         patch('pentest_pipeline.orchestration.orchestrator.BoundedTransport', side_effect=transport), \
         patch('pentest_pipeline.orchestration.executors_laboratory.DockerContainerManager', return_value=manager or InProcessContainerManager()), \
         patch('socket.create_connection', side_effect=AssertionError('External traffic forbidden')):
        return OrchestratorV2(cve_intelligence=True, cve_service=LocalAdvisories(scenario), checkpoint_store=store,
            independent_validation=enabled, reflection_provider=provider, ai_planning=ai_planning).run(_cfg(), stop_event=stop)


class Phase7IntegrationTests(unittest.TestCase):
    def test_contradiction_revision_preserves_original_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CheckpointStore(directory)
            saves = []
            original = store.save
            def save(*args, **kwargs):
                saves.append(json.loads(json.dumps(kwargs)))
                return original(*args, **kwargs)
            with patch.object(store, 'save', side_effect=save):
                result = campaign(store=store, provider=ControlledReflection(), ai_planning=True)
            data = result.to_dict()
            c = next(c for c in data['conclusions'] if c['subject_type'] == 'hypothesis')
            self.assertEqual((c['initial_status'], c['current_status']), ('potential', 'rejected'))
            self.assertTrue(c['validation']['contradicting_evidence_refs'])
            self.assertEqual(c['reflection']['decision_source'], 'ai')
            original_hypothesis = next(o for o in data['observations'] if o.get('type') == 'vulnerability_intelligence')['hypotheses'][0]
            self.assertEqual(original_hypothesis['correlation_status'], 'potentially_affected')
            final = store.load(result.run_id)
            self.assertEqual(final['task_states']['independent_validation'], 'completed')
            self.assertEqual(conclusion_history(None, final['execution_events']), data['conclusions'])
            self.assertTrue(any(s['task_states'].get('independent_validation') == 'running' and
                any(e['event_type'] == 'conclusion_review_recorded' for e in s['execution_events']) for s in saves))
            executions = execution_history(data['execution_events'], data)
            self.assertEqual(len([e for e in executions if e['hypothesis_id']]), 1)
            events = [e['event_type'] for e in data['execution_events']]
            for name in ('evidence_validation_completed', 'reflection_completed', 'classification_change_approved', 'hypothesis_revised'):
                self.assertIn(name, events)

    def test_unjustified_ai_confirmation_rejected(self):
        result = campaign('inconclusive', provider=ControlledReflection()).to_dict()
        c = next(c for c in result['conclusions'] if c['subject_type'] == 'hypothesis')
        self.assertEqual(c['validation']['status'], 'insufficient_evidence')
        self.assertEqual(c['reflection']['suggested_status'], 'confirmed')
        self.assertFalse(c['revisions'][0]['revision']['accepted'])
        self.assertEqual(c['current_status'], 'inconclusive')
        self.assertTrue(any(e['event_type'] == 'classification_change_rejected' for e in result['execution_events']))

    def test_failed_lab_does_not_block_independent_review(self):
        manager = Mock(isolation_level='container', available=Mock(return_value=True), run=Mock(side_effect=ContainerError('failed')),
                       cleanup_status='completed')
        result = campaign(manager=manager).to_dict()
        c = next(c for c in result['conclusions'] if c['subject_type'] == 'hypothesis')
        self.assertEqual(c['current_status'], 'inconclusive')
        self.assertFalse(c['validation']['contradicting_evidence_refs'])
        self.assertEqual(c['revalidation']['status'], 'rejected_for_current_campaign')
        self.assertFalse(c['revalidation']['executed'])

    def test_stop_prevents_review_dispatch(self):
        from threading import Event
        stop = Event(); stop.set()
        data = campaign(stop=stop).to_dict()
        self.assertEqual(data['status'], 'stopped')
        self.assertNotIn('conclusions', data)

    def test_disabled_v2_preserves_baseline(self):
        data = campaign(enabled=False).to_dict()
        self.assertNotIn('conclusions', data)
        self.assertFalse(any(e.get('task_id') == 'independent_validation' for e in data['execution_events']))

    def test_legacy_dispatch_ignores_opt_in_without_changing_kwargs(self):
        from pentest_pipeline.orchestration.entry import run_campaign
        with patch('pentest_pipeline.pipeline.run_scan', return_value='legacy') as run:
            self.assertEqual(run_campaign(_cfg(), orchestrator='legacy', independent_validation=True,
                                          reflection_provider=ControlledReflection()), 'legacy')
            run.assert_called_once_with(_cfg())

    def test_json_markdown_and_restarted_projection(self):
        data = campaign(provider=ControlledReflection()).to_dict()
        reloaded = json.loads(json.dumps(data))
        self.assertEqual(conclusion_history(reloaded, reloaded['execution_events']), data['conclusions'])
        md = render_markdown(reloaded)
        for text in ('Findings confirmados por critérios explícitos', 'Hipóteses rejeitadas',
                     'Resultados inconclusivos', 'Reflexão registrada', 'Evidências contrárias'):
            self.assertIn(text, md)
        confirmed = [c for c in data['conclusions'] if c['current_status'] == 'confirmed']
        self.assertTrue(confirmed)
        self.assertTrue(all(c['subject_type'] == 'finding' and c['validation']['sufficient_for_confirmation'] for c in confirmed))

    def test_live_projection_and_secret_sanitization(self):
        data = campaign().to_dict()
        store = EventStore(data['run_id'])
        store.extend(data['execution_events'])
        self.assertEqual(conclusion_history(None, store.all()), data['conclusions'])
        store.append({'type': 'reflection_completed', 'timestamp': 'unique', 'reflection': {'api_key': 'secret', 'reason': 'safe'}})
        self.assertNotIn('secret', str(store.all()[-1]))
        from pentest_pipeline.orchestration.projection import project
        projected = project(data['execution_events'], campaign_state=data['status'])
        self.assertEqual(projected['mode'], 'v2')
        self.assertEqual(len(projected['macrophases']), 8)

    def test_terminal_mode_survives_plan_reprioritization_and_roundtrip(self):
        from pentest_pipeline.contracts import AdaptivePlanProposal, ExecutionPlan
        from pentest_pipeline.orchestration.legacy_plan import LegacyPlanBuilder
        from pentest_pipeline.planning.plan_validator import PlanValidator, apply_priorities
        plan = LegacyPlanBuilder().build(independent_validation=True)
        proposal = AdaptivePlanProposal('p', 'c', priority_order=('independent_validation',))
        changed = apply_priorities(plan, PlanValidator().validate(proposal, plan))
        task = ExecutionPlan.from_dict(changed.to_dict()).tasks[-1]
        self.assertEqual(task.dependency_policy, 'terminal')
        self.assertEqual(task.depends_on, plan.tasks[-1].depends_on)
        self.assertTrue(build_registry().has('independent_validation'))


class ReflectionProviderTests(unittest.TestCase):
    def test_existing_openai_client_and_schema_reused(self):
        s, c, e = fixture()
        provider = OpenAIReflectionProvider('fake-test-key', 'configured-model')
        with patch('pentest_pipeline.validation.providers._responses_json', return_value={}) as call:
            r = ReflectionAgent(provider).reflect(s, validate(s, c, e), current_status='suspected')
            self.assertEqual(r.decision_source, 'deterministic')
            self.assertEqual(call.call_args.args, ('fake-test-key', 'configured-model'))
            self.assertFalse(call.call_args.kwargs['schema']['additionalProperties'])
            self.assertNotIn('fake-test-key', str(call.call_args.kwargs['input_data']))

    def test_existing_bedrock_client_reused(self):
        s, c, e = fixture(); client = Mock()
        provider = BedrockReflectionProvider('configured-model', client=client)
        with patch('pentest_pipeline.validation.providers._bedrock_json', side_effect=TimeoutError()) as call:
            r = ReflectionAgent(provider).reflect(s, validate(s, c, e), current_status='suspected')
            self.assertEqual(r.fallback_reason, 'TimeoutError')
            self.assertEqual(call.call_args.args, (client, 'configured-model'))


@unittest.skipUnless(os.environ.get('PENTEST_DOCKER_IT') == '1', 'Requires real Docker opt-in')
class Phase7RealDockerTests(unittest.TestCase):
    def test_real_docker_contradiction_and_rejected_promotion(self):
        with tempfile.TemporaryDirectory() as directory:
            for scenario in ('contradicted', 'inconclusive'):
                with self.subTest(scenario=scenario):
                    manifest = generate_campaign(directory, scenario, phase7=True)
                    data = json.loads((Path(directory) / 'reports' / manifest['run_id'] / 'result.json').read_text())
                    conclusion = next(c for c in data['conclusions'] if c['subject_type'] == 'hypothesis')
                    self.assertEqual(conclusion['current_status'], manifest['current_status'])
                    self.assertEqual(conclusion['revisions'][0]['revision']['revision_id'], manifest['revision_id'])
