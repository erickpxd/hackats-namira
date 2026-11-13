"""Testes da Fase 5 — planejamento adaptativo (planner, validador, scheduler,
replanejamento, segurança e observabilidade). Nenhuma requisição externa."""

from __future__ import annotations

from email.message import Message
from urllib.parse import urlsplit
import unittest
from unittest.mock import patch

from pentest_pipeline.contracts import (
    AdaptivePlanProposal, CampaignContext, ExecutionPlan, TaskDefinition, TaskResult)
from pentest_pipeline.models import ScanResult
from pentest_pipeline.scope import ScopeConfig
from pentest_pipeline.orchestration.context import ExecutionContext
from pentest_pipeline.orchestration.orchestrator import OrchestratorV2
from pentest_pipeline.orchestration.scheduler import TaskScheduler
from pentest_pipeline.orchestration.task_registry import TaskRegistry
from pentest_pipeline.planning import (
    AdaptivePlanner, CampaignMemory, PlanValidator)
from pentest_pipeline.planning.plan_validator import apply_priorities
from pentest_pipeline.planning.replanning_policy import ReplanningPolicy, ReplanTrigger
from pentest_pipeline.transport import Response


# ---------------------------- fixtures ------------------------------------ #
class _Exec:
    def __init__(self, task_type, sink=None, state="completed"):
        self.task_type = task_type
        self.requires_approval = False
        self._sink = sink
        self._state = state

    def execute(self, task, context):
        if self._sink is not None:
            self._sink.append(task.task_id)
        return TaskResult(task_id=task.task_id, state=self._state)


def _ctx():
    scope = ScopeConfig(target_url="https://example.com/", allowed_hosts=("example.com",))
    campaign = CampaignContext("c1", "corr1", scope)
    result = ScanResult(run_id="c1", target="https://example.com/", campaign_name="t",
                        started_at="now")
    return ExecutionContext(campaign=campaign, transport=None, result=result)


def _opt(tid, deps=(), optional=True):
    return TaskDefinition(task_id=tid, task_type=tid, executor=tid,
                          depends_on=deps, optional=optional)


def _catalog():
    # root (obrigatória) + duas opcionais independentes.
    return [_opt("root", optional=False), _opt("opt_a", ("root",)), _opt("opt_b", ("root",))]


def _memory_with_findings():
    mem = CampaignMemory(campaign_id="c1")
    mem.findings_by_severity = {"medium": 1}
    return mem


class StubProvider:
    def __init__(self, response):
        self.response = response
        self.calls: list = []

    def propose(self, payload, allowed_task_ids):
        self.calls.append((payload, list(allowed_task_ids)))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


# ======================= AdaptivePlanner ================================== #
class PlannerTests(unittest.TestCase):
    def test_valid_provider_proposal(self):
        provider = StubProvider({"priority_order": ["opt_b", "opt_a"],
                                 "selected_task_ids": ["opt_b", "opt_a"],
                                 "decision_reasons": {"opt_b": "mais relevante"}})
        proposal = AdaptivePlanner(provider).propose(_memory_with_findings(), _catalog())
        self.assertEqual(proposal.priority_order, ("opt_b", "opt_a"))
        self.assertEqual(proposal.origin, "ai")

    def test_provider_unknown_ids_are_filtered(self):
        # IDs fora do catálogo / obrigatórios são descartados; sobra opt_a.
        provider = StubProvider({"priority_order": ["root", "ghost", "opt_a"],
                                 "selected_task_ids": ["opt_a"]})
        proposal = AdaptivePlanner(provider).propose(_memory_with_findings(), _catalog())
        self.assertEqual(proposal.priority_order, ("opt_a",))

    def test_provider_timeout_falls_back_to_deterministic(self):
        provider = StubProvider(TimeoutError("slow"))
        proposal = AdaptivePlanner(provider).propose(_memory_with_findings(), _catalog())
        self.assertEqual(proposal.origin, "deterministic")
        self.assertTrue(proposal.priority_order)

    def test_malformed_response_falls_back(self):
        proposal = AdaptivePlanner(StubProvider("not-a-dict")).propose(
            _memory_with_findings(), _catalog())
        self.assertEqual(proposal.origin, "deterministic")

    def test_no_evidence_yields_empty_proposal(self):
        proposal = AdaptivePlanner().propose(CampaignMemory(campaign_id="c1"), _catalog())
        self.assertEqual(proposal.priority_order, ())
        self.assertEqual(proposal.selected_task_ids, ())

    def test_deterministic_prioritizes_hypothesis_tasks(self):
        catalog = [_opt("root", optional=False),
                   _opt("cve_research", ("root",)), _opt("remediation", ("root",))]
        mem = CampaignMemory(campaign_id="c1")
        mem.open_hypotheses = [{"id": "CVE-1", "correlation_status": "potentially_affected"}]
        # retipa os task_types para casar com a afinidade determinística
        catalog[1] = TaskDefinition("cve_research", "cve_research", "cve_research",
                                    ("root",), optional=True)
        catalog[2] = TaskDefinition("remediation", "remediation", "remediation",
                                    ("root",), optional=True)
        proposal = AdaptivePlanner().propose(mem, catalog)
        self.assertEqual(proposal.priority_order[0], "cve_research")


# ======================= PlanValidator =================================== #
class ValidatorTests(unittest.TestCase):
    def _plan(self):
        return ExecutionPlan("p", 1, tasks=tuple(_catalog()))

    def test_valid_proposal_produces_priorities(self):
        proposal = AdaptivePlanProposal("pr", "c1", priority_order=("opt_b", "opt_a"))
        res = PlanValidator().validate(proposal, self._plan())
        self.assertTrue(res.valid)
        self.assertGreater(res.accepted_priorities["opt_b"], res.accepted_priorities["opt_a"])

    def test_unknown_id_rejected(self):
        proposal = AdaptivePlanProposal("pr", "c1", priority_order=("ghost",))
        res = PlanValidator().validate(proposal, self._plan())
        self.assertFalse(res.valid)
        self.assertIn("ghost", [r[0] for r in res.rejections])

    def test_mandatory_task_not_reprioritizable(self):
        proposal = AdaptivePlanProposal("pr", "c1", priority_order=("root",))
        res = PlanValidator(mandatory_task_types=frozenset({"root"})).validate(
            proposal, self._plan())
        self.assertFalse(res.valid)
        self.assertIn(("root", "tarefa_obrigatoria_nao_repriorizavel"), res.rejections)

    def test_completed_task_not_repeated(self):
        proposal = AdaptivePlanProposal("pr", "c1", priority_order=("opt_a", "opt_b"))
        res = PlanValidator().validate(proposal, self._plan(),
                                       completed_task_ids={"opt_a"})
        self.assertIn(("opt_a", "ja_concluida"), res.rejections)
        self.assertIn("opt_b", res.accepted_priorities)

    def test_budget_exhausted_blocks_network_task(self):
        proposal = AdaptivePlanProposal("pr", "c1", priority_order=("opt_a",))
        res = PlanValidator(network_task_types=frozenset({"opt_a"})).validate(
            proposal, self._plan(), remaining_budget=0)
        self.assertIn(("opt_a", "orcamento_esgotado_para_rede"), res.rejections)

    def test_dependency_cycle_rejected(self):
        # sugerir opt_a depende de opt_b e opt_b depende de opt_a -> ciclo
        proposal = AdaptivePlanProposal(
            "pr", "c1", priority_order=("opt_a", "opt_b"),
            dependency_suggestions=(("opt_a", "opt_b"), ("opt_b", "opt_a")))
        res = PlanValidator().validate(proposal, self._plan())
        reasons = [r[1] for r in res.rejections]
        self.assertIn("dependencia_criaria_ciclo", reasons)

    def test_apply_priorities_preserves_approval_and_mandatory(self):
        plan = ExecutionPlan("p", 1, tasks=(
            TaskDefinition("root", "root", "root", optional=False, requires_approval=True),
            _opt("opt_a", ("root",)), _opt("opt_b", ("root",))))
        proposal = AdaptivePlanProposal("pr", "c1", priority_order=("opt_b",))
        res = PlanValidator().validate(proposal, plan)
        new_plan = apply_priorities(plan, res)
        by_id = {t.task_id: t for t in new_plan.tasks}
        self.assertTrue(by_id["root"].requires_approval)       # aprovação preservada
        self.assertFalse(by_id["root"].optional)               # obrigatória preservada
        self.assertGreater(by_id["opt_b"].priority, by_id["opt_a"].priority)


# ===================== Scheduler: prioridade real ======================== #
class SchedulerPriorityTests(unittest.TestCase):
    def _run_with_priority(self, first):
        order: list[str] = []
        reg = TaskRegistry()
        for name in ("root", "opt_a", "opt_b"):
            reg.register(_Exec(name, sink=order))
        plan = ExecutionPlan("p", 1, tasks=tuple(_catalog()))
        proposal = AdaptivePlanProposal("pr", "c1", priority_order=(first,))
        res = PlanValidator().validate(proposal, plan)
        prioritized = apply_priorities(plan, res)
        TaskScheduler(reg).run(prioritized, _ctx())
        return [t for t in order if t != "root"]

    def test_priorities_change_real_execution_order(self):
        # Critério de aceite: duas propostas -> ordem real observa mudança.
        self.assertEqual(self._run_with_priority("opt_a"), ["opt_a", "opt_b"])
        self.assertEqual(self._run_with_priority("opt_b"), ["opt_b", "opt_a"])

    def test_dependencies_still_respected_under_priority(self):
        order: list[str] = []
        reg = TaskRegistry()
        for name in ("root", "opt_a", "opt_b"):
            reg.register(_Exec(name, sink=order))
        # opt_b priorizada, mas depende de opt_a -> opt_a continua antes.
        plan = ExecutionPlan("p", 1, tasks=(
            _opt("root", optional=False), _opt("opt_a", ("root",)),
            TaskDefinition("opt_b", "opt_b", "opt_b", ("root", "opt_a"),
                           optional=True, priority=99)))
        TaskScheduler(reg).run(plan, _ctx())
        self.assertLess(order.index("opt_a"), order.index("opt_b"))


# ===================== Replanejamento controlado ========================= #
class ReplanningTests(unittest.TestCase):
    def test_unknown_trigger_rejected(self):
        self.assertFalse(ReplanningPolicy().should_replan("qualquer_coisa"))

    def test_no_justification_rejected(self):
        self.assertFalse(ReplanningPolicy().should_replan(
            ReplanTrigger.NEW_EVIDENCE, has_justification=False))

    def test_non_idempotent_not_repeated(self):
        self.assertFalse(ReplanningPolicy().should_replan(
            ReplanTrigger.NEW_EVIDENCE, idempotent=False))

    def test_revision_limit_enforced(self):
        policy = ReplanningPolicy(max_revisions=1)
        p1 = AdaptivePlanProposal("a", "c1", priority_order=("opt_a",))
        self.assertTrue(policy.register(ReplanTrigger.NEW_EVIDENCE, proposal=p1))
        self.assertTrue(policy.exhausted())
        self.assertFalse(policy.should_replan(ReplanTrigger.NEW_EVIDENCE))

    def test_cycle_protection_same_proposal(self):
        policy = ReplanningPolicy(max_revisions=5)
        p = AdaptivePlanProposal("a", "c1", priority_order=("opt_a",))
        self.assertTrue(policy.register(ReplanTrigger.NEW_EVIDENCE, proposal=p))
        self.assertFalse(policy.register(ReplanTrigger.NEW_EVIDENCE, proposal=p))  # repetida

    def test_added_tasks_limit(self):
        policy = ReplanningPolicy(max_additional_tasks=1)
        p = AdaptivePlanProposal("a", "c1", priority_order=("opt_a",))
        self.assertFalse(policy.register(ReplanTrigger.NEW_EVIDENCE, proposal=p, added=5))

    def test_history_is_preserved(self):
        policy = ReplanningPolicy()
        policy.should_replan("inexistente")          # rejected
        p = AdaptivePlanProposal("a", "c1", priority_order=("opt_a",))
        policy.register(ReplanTrigger.NEW_EVIDENCE, proposal=p)
        outcomes = [h["outcome"] for h in policy.history]
        self.assertIn("rejected", outcomes)
        self.assertIn("accepted", outcomes)


# ===================== Segurança ========================================= #
class SecurityTests(unittest.TestCase):
    def test_injection_in_external_data_cannot_add_tasks(self):
        # provider "comprometido" tenta nomear ferramenta não autorizada.
        provider = StubProvider({"priority_order": ["run_exploit", "exfiltrate"],
                                 "selected_task_ids": ["run_exploit"]})
        proposal = AdaptivePlanner(provider).propose(_memory_with_findings(), _catalog())
        # nenhuma tarefa desconhecida sobrevive -> cai no determinístico seguro
        for tid in proposal.priority_order:
            self.assertIn(tid, {"opt_a", "opt_b"})

    def test_validator_rejects_scope_expansion(self):
        proposal = AdaptivePlanProposal("pr", "c1", priority_order=("rce_task",))
        res = PlanValidator().validate(proposal, ExecutionPlan("p", 1, tasks=tuple(_catalog())))
        self.assertFalse(res.valid)

    def test_proposal_validation_rejects_self_dependency(self):
        with self.assertRaises(Exception):
            AdaptivePlanProposal("pr", "c1",
                                 dependency_suggestions=(("x", "x"),)).validate()


# ===================== Orquestração + observabilidade ==================== #
def _resp(url, status, body=b"", ct="text/html", **h):
    m = Message()
    m["Content-Type"] = ct
    for k, v in h.items():
        m[k.replace("_", "-")] = v
    return Response(url, status, m, body, False, 1)


class _FakeTransport:
    def __init__(self, config, *, stop_event=None, on_event=None):
        self.config = config
        self.request_count = 0
        self.on_event = on_event
        self.actions: list[dict] = []
        self._responses = {
            ("GET", "/"): _resp(config.target_url, 200, b"<html>Home</html>"),
            ("GET", "/robots.txt"): _resp(config.target_url, 404),
            ("GET", "/.well-known/security.txt"): _resp(config.target_url, 404)}

    def request(self, url, *, method="GET", phase="test"):
        self.config.assert_request(url, method)
        key = (method, urlsplit(url).path)
        self.request_count += 1
        if key not in self._responses:
            raise AssertionError(f"unexpected {key}")
        i = self._responses[key]
        return Response(url, i.status, i.headers, i.body, i.truncated, i.elapsed_ms)

    def record(self, t, p, m, **d):
        e = {"type": t, "phase": p, "message": m, **d}
        self.actions.append(e)
        if self.on_event:
            self.on_event(e)


def _mk(c, **kw):
    return _FakeTransport(c, **kw)


class OrchestrationPlanningTests(unittest.TestCase):
    def _cfg(self):
        return ScopeConfig.for_target_url("https://example.com/#/")

    def test_ai_planning_records_decision_and_preserves_findings(self):
        cfg = self._cfg()
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            base = OrchestratorV2().run(cfg)
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            planned = OrchestratorV2(ai_planning=True).run(cfg)
        # Planejamento não altera achados (só a ordem de tarefas opcionais).
        self.assertEqual([f.to_dict() for f in planned.findings],
                         [f.to_dict() for f in base.findings])
        self.assertEqual(planned.status, base.status)
        # Decisão de planejamento adaptativo registrada (evidência presente).
        kinds = [o.get("type") for o in planned.observations]
        self.assertIn("adaptive_plan", kinds)

    def test_ai_planning_falls_back_when_provider_fails(self):
        cfg = self._cfg()
        provider = StubProvider(RuntimeError("down"))
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            result = OrchestratorV2(ai_planning=True, planning_provider=provider).run(cfg)
        # Falha da IA não derruba a campanha: plano determinístico segue.
        self.assertIn(result.status, ("completed", "inconclusive"))


if __name__ == "__main__":
    unittest.main()
