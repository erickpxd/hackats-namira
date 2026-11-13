"""Testes unitários dos contratos introduzidos na Fase 1 (orquestrador v2).

Cobrem construção, validação, serialização round-trip e a guarda que impede
texto de IA de nomear tipos/executores fora de uma allowlist.
"""

from __future__ import annotations

import json
import unittest

from pentest_pipeline.contracts import (AgentDecision, AIConfig, CampaignContext,
                                        ContractError, ExecutionLimits, ExecutionPlan,
                                        NormalizedError, RetryPolicy, TaskDefinition,
                                        TaskResult)
from pentest_pipeline.scope import ScopeConfig


def _scope() -> ScopeConfig:
    return ScopeConfig(target_url="https://4.migbot.com.br/",
                       allowed_hosts=("4.migbot.com.br",))


class CampaignContextTests(unittest.TestCase):
    def test_valid_context_references_scope_without_duplicating_budget(self) -> None:
        ctx = CampaignContext(campaign_id="c1", correlation_id="corr-1", scope=_scope(),
                              ai=AIConfig(enabled=True, provider="openai", model="gpt"),
                              metadata={"operator": "qa"}).validate()
        data = ctx.to_dict()
        # O orçamento continua sendo propriedade do ScopeConfig referenciado.
        self.assertEqual(data["scope"]["max_requests"], 24)
        self.assertEqual(data["ai"]["provider"], "openai")
        self.assertEqual(data["orchestrator"], "legacy")
        json.dumps(data)  # precisa ser serializável

    def test_rejects_empty_ids_and_bad_provider_and_orchestrator(self) -> None:
        with self.assertRaises(ContractError):
            CampaignContext("", "corr", _scope()).validate()
        with self.assertRaises(ContractError):
            CampaignContext("c1", "corr", _scope(), ai=AIConfig(provider="hal")).validate()
        with self.assertRaises(ContractError):
            CampaignContext("c1", "corr", _scope(), orchestrator="v3").validate()

    def test_ai_config_never_carries_secrets(self) -> None:
        # O contrato não tem campo de chave; garante que não exista por engano.
        self.assertNotIn("api_key", AIConfig().to_dict())


class TaskDefinitionTests(unittest.TestCase):
    def test_roundtrip_serialization(self) -> None:
        task = TaskDefinition(
            task_id="t1", task_type="recon", executor="discovery_agent",
            depends_on=("t0",), input={"url": "https://x/"},
            completion_criteria=("status_registrado",), requires_approval=True,
            limits=ExecutionLimits(max_requests=3, timeout_seconds=5.0),
            retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=1.0))
        restored = TaskDefinition.from_dict(task.to_dict())
        self.assertEqual(restored.to_dict(), task.to_dict())
        self.assertEqual(restored.limits.max_requests, 3)

    def test_self_dependency_and_empty_fields_rejected(self) -> None:
        with self.assertRaises(ContractError):
            TaskDefinition("t1", "recon", "agent", depends_on=("t1",)).validate()
        with self.assertRaises(ContractError):
            TaskDefinition("", "recon", "agent").validate()

    def test_allowlist_blocks_ai_proposed_type_or_executor(self) -> None:
        task = TaskDefinition("t1", "exploit", "shell_runner")
        # Sem allowlist, a estrutura é válida (mas inerte: é apenas dado).
        task.validate()
        # Com allowlist, tipo/executor desconhecidos são recusados.
        with self.assertRaises(ContractError):
            task.validate(allowed_types={"recon", "headers"})
        with self.assertRaises(ContractError):
            task.validate(allowed_types={"exploit"}, allowed_executors={"discovery_agent"})

    def test_invalid_limits_and_retry_rejected(self) -> None:
        with self.assertRaises(ContractError):
            ExecutionLimits(max_requests=0).validate()
        with self.assertRaises(ContractError):
            RetryPolicy(max_attempts=0).validate()


class TaskResultTests(unittest.TestCase):
    def test_roundtrip_and_state_validation(self) -> None:
        result = TaskResult(task_id="t1", state="completed",
                            outputs={"finding_ids": ["F-1"]}, evidence_refs=("ev-1",))
        self.assertEqual(TaskResult.from_dict(result.to_dict()).to_dict(), result.to_dict())
        with self.assertRaises(ContractError):
            TaskResult(task_id="t1", state="exploded").validate()

    def test_failed_state_requires_normalized_error(self) -> None:
        with self.assertRaises(ContractError):
            TaskResult(task_id="t1", state="failed").validate()
        TaskResult(task_id="t1", state="failed",
                   error=NormalizedError(code="network", retryable=True)).validate()


class ExecutionPlanTests(unittest.TestCase):
    def _task(self, tid: str, deps: tuple[str, ...] = ()) -> TaskDefinition:
        return TaskDefinition(tid, "recon", "discovery_agent", depends_on=deps)

    def test_valid_plan_roundtrip(self) -> None:
        plan = ExecutionPlan("p1", 1, tasks=(self._task("a"), self._task("b", ("a",))),
                            origin="deterministic", rationale=("ordem segura",))
        plan.validate()
        self.assertEqual(ExecutionPlan.from_dict(plan.to_dict()).to_dict(), plan.to_dict())

    def test_duplicate_ids_missing_dep_and_cycles_rejected(self) -> None:
        with self.assertRaises(ContractError):
            ExecutionPlan("p", 1, tasks=(self._task("a"), self._task("a"))).validate()
        with self.assertRaises(ContractError):
            ExecutionPlan("p", 1, tasks=(self._task("a", ("ghost",)),)).validate()
        with self.assertRaises(ContractError):
            ExecutionPlan("p", 1, tasks=(self._task("a", ("b",)),
                                         self._task("b", ("a",)))).validate()

    def test_bad_version_and_origin_rejected(self) -> None:
        with self.assertRaises(ContractError):
            ExecutionPlan("p", 0, tasks=()).validate()
        with self.assertRaises(ContractError):
            ExecutionPlan("p", 1, tasks=(), origin="oracle").validate()

    def test_allowlist_propagates_to_tasks(self) -> None:
        plan = ExecutionPlan("p", 1, tasks=(TaskDefinition("a", "exploit", "shell"),))
        with self.assertRaises(ContractError):
            plan.validate(allowed_types={"recon"})


class AgentDecisionTests(unittest.TestCase):
    def test_roundtrip_and_origin_validation(self) -> None:
        decision = AgentDecision(agent="triage", decision="priorizar headers",
                                rationale="maior sinal", evidence_refs=("ev-1",),
                                alternatives=("adiar",), origin="deterministic")
        self.assertEqual(AgentDecision.from_dict(decision.to_dict()).to_dict(),
                         decision.to_dict())
        with self.assertRaises(ContractError):
            AgentDecision(agent="triage", decision="x", origin="magic").validate()

    def test_empty_agent_or_decision_rejected(self) -> None:
        with self.assertRaises(ContractError):
            AgentDecision(agent="", decision="x").validate()


if __name__ == "__main__":
    unittest.main()
