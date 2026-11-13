"""Testes da Fase 6 — execução isolada (workers/containers).

Maioria com mocks/fixtures e sem Docker. Um teste real de isolamento roda só
quando Docker + imagem do worker estão disponíveis (senão é pulado e registrado
como não validado). Nenhuma requisição a alvo externo ocorre.
"""

from __future__ import annotations

import os
import shutil
import unittest
from email.message import Message
from unittest.mock import patch
from urllib.parse import urlsplit

from pentest_pipeline.contracts import CampaignContext, ExecutionPlan, TaskDefinition, TaskResult
from pentest_pipeline.models import ScanResult
from pentest_pipeline.scope import ScopeConfig
from pentest_pipeline.transport import Response
from pentest_pipeline.orchestration.context import ExecutionContext
from pentest_pipeline.orchestration.orchestrator import OrchestratorV2
from pentest_pipeline.orchestration.scheduler import TaskScheduler
from pentest_pipeline.orchestration.task_registry import TaskRegistry
from pentest_pipeline.persistence.checkpoint_store import plan_recovery

from pentest_pipeline.execution.config import (
    ContainerConfigError, ContainerExecutionMode, resolve_container_mode)
from pentest_pipeline.execution.container_manager import (
    ContainerConfig, ContainerError, ContainerTimeout, DockerContainerManager,
    InProcessContainerManager, ResourceLimits)
from pentest_pipeline.execution.executor import (
    CONTAINER_ELIGIBLE_TYPES, ContainerExecutionBackend, LocalExecutionBackend,
    RoutingExecutionBackend, TechnologyNormalizationAdapter, build_execution_backend)
from pentest_pipeline.execution.policy import ExecutionDecision, PolicyEngine, PolicyError
from pentest_pipeline.execution.worker_protocol import (
    MAX_MESSAGE_BYTES, WorkerProtocolError, WorkerRequest, WorkerResponse,
    decode_response)
from pentest_pipeline.execution.workers import ALLOWED_OPERATIONS, run_operation


# ----------------------------- fixtures ----------------------------------- #
def _ctx(**kw):
    scope = ScopeConfig(target_url="https://example.com/", allowed_hosts=("example.com",))
    campaign = CampaignContext("c1", "corr1", scope)
    result = ScanResult(run_id="c1", target="https://example.com/", campaign_name="t",
                        started_at="now")
    events: list = []
    ctx = ExecutionContext(campaign=campaign, transport=_RecTransport(), result=result,
                           on_event=events.append, **kw)
    ctx._events = events
    return ctx


class _RecTransport:
    def __init__(self):
        self.request_count = 0
        self.records: list = []

    def record(self, t, p, m, **d):
        self.records.append({"type": t, "phase": p, "message": m, **d})


def _framework(family="angular", version="15.0.0"):
    return {"family": family, "version": version}


# ============================ Worker protocol ============================= #
class WorkerProtocolTests(unittest.TestCase):
    def test_rejects_unknown_operation(self):
        resp = run_operation(WorkerRequest("t", "rm_rf", {}))
        self.assertEqual(resp.status, "failed")
        self.assertIn("não registrada", resp.error)

    def test_allowed_operations_set(self):
        self.assertEqual(set(ALLOWED_OPERATIONS),
                         {"normalize_technology_inventory", "analyze_local_metadata",
                      "validate_result_structure", "compare_local_results",
                  "verify_integrity", "correlate_local_version", "inspect_demo_environment", "correlate_fixture_version"})

    def test_input_validation(self):
        with self.assertRaises(WorkerProtocolError):
            WorkerRequest("", "op", {}).validate()
        with self.assertRaises(WorkerProtocolError):
            WorkerRequest("t", "op", {}).validate(allowed_operations=["other"])

    def test_output_size_limit_enforced(self):
        big = "x" * (MAX_MESSAGE_BYTES + 10)
        resp = WorkerResponse("t", "completed", {"blob": big})
        with self.assertRaises(WorkerProtocolError):
            resp.encode()

    def test_decode_response_rejects_oversize(self):
        with self.assertRaises(WorkerProtocolError):
            decode_response(b"x" * (MAX_MESSAGE_BYTES + 1))

    def test_normalize_operation_roundtrip(self):
        resp = run_operation(WorkerRequest("t", "normalize_technology_inventory",
                                           {"framework": _framework()}))
        self.assertEqual(resp.status, "completed")
        self.assertIn("normalized_components", resp.output)

    def test_validate_structure_operation(self):
        resp = run_operation(WorkerRequest("t", "validate_result_structure",
                             {"findings": [{"id": "a", "severity": "high"},
                                           {"id": "a", "severity": "nope"}]}))
        self.assertFalse(resp.output["valid"])
        self.assertTrue(resp.output["issues"])


# ============================ Resource limits ============================= #
class LimitsTests(unittest.TestCase):
    def test_resource_limits_validation(self):
        with self.assertRaises(ContainerError):
            ResourceLimits(cpus=0).validate()
        with self.assertRaises(ContainerError):
            ResourceLimits(memory_mb=8).validate()
        with self.assertRaises(ContainerError):
            ResourceLimits(network="bridge").validate()  # rede proibida na Fase 6

    def test_container_config_rejects_insecure(self):
        allowed = frozenset({"namira/worker:local"})
        with self.assertRaises(ContainerError):
            ContainerConfig(read_only=False).validate(allowed_images=allowed)
        with self.assertRaises(ContainerError):
            ContainerConfig(user="root").validate(allowed_images=allowed)
        with self.assertRaises(ContainerError):
            ContainerConfig(image="evil/image").validate(allowed_images=allowed)

    def test_docker_argv_hardening(self):
        argv = DockerContainerManager()._argv(ContainerConfig())
        for flag in ("--network", "none", "--user", "65534:65534", "--read-only",
                     "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                     "--pids-limit", "--memory", "--cpus"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[-4:], ["python", "-I", "-m",
                                     "pentest_pipeline.execution.worker_entry"])
        self.assertNotIn("-v", argv)          # nenhum volume/socket montado
        self.assertNotIn("/var/run/docker.sock", " ".join(argv))


# ============================ ContainerManager =========================== #
class ManagerTests(unittest.TestCase):
    def test_inprocess_runs_and_reports_duration(self):
        resp = InProcessContainerManager().run(
            WorkerRequest("t", "normalize_technology_inventory", {"framework": _framework()}),
            ContainerConfig())
        self.assertEqual(resp.status, "completed")
        self.assertIsNotNone(resp.duration_ms)

    def test_inprocess_timeout(self):
        slow = WorkerRequest("t", "normalize_technology_inventory",
                             {"framework": _framework()}, {"timeout_seconds": 0.001})

        def _slow(_req):
            import time
            time.sleep(0.3)
            return WorkerResponse("t", "completed")
        with patch("pentest_pipeline.execution.workers.run_operation", side_effect=_slow):
            with self.assertRaises(ContainerTimeout):
                InProcessContainerManager().run(slow, ContainerConfig())

    def test_docker_unknown_image_rejected(self):
        mgr = DockerContainerManager(allowed_images=frozenset({"namira/worker:local"}))
        with self.assertRaises(ContainerError):
            mgr.run(WorkerRequest("t", "normalize_technology_inventory", {}),
                    ContainerConfig(image="evil/x"))

    def test_docker_runtime_failure_via_runner(self):
        def _boom(argv, payload, timeout):
            raise ContainerError("runtime down")
        mgr = DockerContainerManager(runner=_boom)
        with self.assertRaises(ContainerError):
            mgr.run(WorkerRequest("t", "normalize_technology_inventory",
                                  {"framework": _framework()}), ContainerConfig())

    def test_docker_happy_path_with_fake_runner(self):
        def _runner(argv, payload, timeout):
            # simula o container executando o entrypoint real sobre o payload
            from pentest_pipeline.execution.worker_protocol import decode_request
            return run_operation(decode_request(payload)).encode()
        mgr = DockerContainerManager(runner=_runner)
        resp = mgr.run(WorkerRequest("t", "normalize_technology_inventory",
                                     {"framework": _framework()}), ContainerConfig())
        self.assertEqual(resp.status, "completed")


# ============================ PolicyEngine =============================== #
class PolicyTests(unittest.TestCase):
    def _reg(self):
        reg = TaskRegistry()

        class _E:
            task_type = "technology_normalization"
            requires_approval = False
            def execute(self, task, context):
                return TaskResult(task_id=task.task_id, state="completed")
        reg.register(_E())
        return reg

    def test_disabled_always_local(self):
        pol = PolicyEngine(mode=ContainerExecutionMode.DISABLED,
                           container_eligible_types=CONTAINER_ELIGIBLE_TYPES)
        d = pol.decide(TaskDefinition("x", "technology_normalization", "x"),
                       self._reg().metadata("technology_normalization"))
        self.assertEqual(d.backend, "local")

    def test_eligible_goes_to_container(self):
        pol = PolicyEngine(mode=ContainerExecutionMode.ENABLED,
                           container_eligible_types=CONTAINER_ELIGIBLE_TYPES)
        d = pol.decide(TaskDefinition("x", "technology_normalization", "x"),
                       self._reg().metadata("technology_normalization"))
        self.assertEqual(d.backend, "container")

    def test_network_task_stays_local(self):
        reg = TaskRegistry()

        class _N:
            task_type = "technology_normalization"
            requires_approval = False
            def execute(self, t, c): return TaskResult(task_id=t.task_id, state="completed")
        reg.register(_N(), touches_network=True)
        pol = PolicyEngine(mode=ContainerExecutionMode.ENABLED,
                           container_eligible_types=CONTAINER_ELIGIBLE_TYPES)
        d = pol.decide(TaskDefinition("x", "technology_normalization", "x"),
                       reg.metadata("technology_normalization"))
        self.assertEqual(d.backend, "local")
        self.assertEqual(d.reason, "network_bound_stays_local")

    def test_non_eligible_stays_local(self):
        pol = PolicyEngine(mode=ContainerExecutionMode.ENABLED,
                           container_eligible_types=CONTAINER_ELIGIBLE_TYPES)
        reg = self._reg()
        d = pol.decide(TaskDefinition("x", "surface_checks", "x"),
                       reg.metadata("technology_normalization"))
        self.assertEqual(d.backend, "local")

    def test_critical_has_no_fallback(self):
        pol = PolicyEngine(mode=ContainerExecutionMode.ENABLED,
                           container_eligible_types=CONTAINER_ELIGIBLE_TYPES,
                           critical_types=frozenset({"technology_normalization"}))
        self.assertFalse(pol.authorize_fallback(
            TaskDefinition("x", "technology_normalization", "x")))

    def test_validate_runtime_rejects_unavailable(self):
        class _Down:
            isolation_level = "container"
            def available(self): return False
            def run(self, r, c): raise AssertionError
        pol = PolicyEngine(mode=ContainerExecutionMode.ENABLED,
                           container_eligible_types=CONTAINER_ELIGIBLE_TYPES)
        with self.assertRaises(PolicyError):
            pol.validate_runtime(_Down(), ContainerConfig(),
                                 allowed_images=frozenset({"namira/worker:local"}))


# ============================ Backend / scheduler ======================== #
class _StubManager:
    isolation_level = "container"

    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = 0

    def available(self):
        return True

    def run(self, request, config):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.response or run_operation(request)


def _routing(registry, manager, *, critical=frozenset()):
    pol = PolicyEngine(mode=ContainerExecutionMode.ENABLED,
                       container_eligible_types=CONTAINER_ELIGIBLE_TYPES,
                       critical_types=critical)
    local = LocalExecutionBackend(registry)
    container = ContainerExecutionBackend(manager=manager, policy=pol, local_backend=local)
    return RoutingExecutionBackend(registry=registry, policy=pol,
                                   local_backend=local, container_backend=container)


class BackendTests(unittest.TestCase):
    def _registry(self):
        from pentest_pipeline.orchestration.executors_intelligence import (
            TechnologyNormalizationExecutor)
        reg = TaskRegistry()
        reg.register(TechnologyNormalizationExecutor())
        return reg

    def test_container_executes_eligible_and_writes_blackboard(self):
        reg = self._registry()
        ctx = _ctx()
        ctx.put("framework", _framework())
        backend = _routing(reg, InProcessContainerManager())
        task = TaskDefinition("technology_normalization", "technology_normalization",
                              "technology_normalization", optional=True)
        result = backend.execute(task, ctx)
        self.assertEqual(result.state, "completed")
        self.assertEqual(result.outputs.get("execution"), "simulated")
        self.assertTrue(ctx.get("tech_components"))
        types = [e["type"] for e in ctx._events]
        self.assertIn("worker_requested", types)
        self.assertIn("worker_completed", types)
        self.assertIn("worker_cleanup_completed", types)

    def test_container_equivalence_with_local(self):
        # Mesmo input -> mesmos componentes no blackboard (operação determinística).
        reg = self._registry()
        local_ctx, cont_ctx = _ctx(), _ctx()
        local_ctx.put("framework", _framework()); cont_ctx.put("framework", _framework())
        task = TaskDefinition("technology_normalization", "technology_normalization",
                              "technology_normalization", optional=True)
        LocalExecutionBackend(reg).execute(task, local_ctx)
        _routing(reg, InProcessContainerManager()).execute(task, cont_ctx)
        local_comp = [c.to_dict() for c in local_ctx.get("tech_components")]
        cont_comp = [c.to_dict() for c in cont_ctx.get("tech_components")]
        self.assertEqual(local_comp, cont_comp)

    def test_optional_fallback_on_worker_failure(self):
        reg = self._registry()
        ctx = _ctx(); ctx.put("framework", _framework())
        backend = _routing(reg, _StubManager(exc=ContainerError("boom")))  # optional => fallback
        task = TaskDefinition("technology_normalization", "technology_normalization",
                              "technology_normalization", optional=True)
        result = backend.execute(task, ctx)
        self.assertEqual(result.state, "completed")   # fallback local concluiu
        self.assertTrue(any(e.get("decision") == "authorized_fallback" for e in ctx._events))

    def test_critical_failure_has_no_silent_fallback(self):
        reg = self._registry()
        ctx = _ctx(); ctx.put("framework", _framework())
        backend = _routing(reg, _StubManager(exc=ContainerError("boom")),
                           critical=frozenset({"technology_normalization"}))
        task = TaskDefinition("technology_normalization", "technology_normalization",
                              "technology_normalization", optional=True)
        result = backend.execute(task, ctx)
        self.assertEqual(result.state, "failed")

    def test_cancellation_before_run(self):
        reg = self._registry()
        import threading
        stop = threading.Event(); stop.set()
        ctx = _ctx(stop_event=stop); ctx.put("framework", _framework())
        backend = _routing(reg, InProcessContainerManager())
        task = TaskDefinition("technology_normalization", "technology_normalization",
                              "technology_normalization", optional=True)
        result = backend.execute(task, ctx)
        self.assertEqual(result.state, "cancelled")
        self.assertTrue(any(e["type"] == "worker_cancelled" for e in ctx._events))

    def test_scheduler_uses_backend_without_reordering(self):
        reg = self._registry()
        order: list = []

        class _Sink:
            task_type = "other"
            requires_approval = False
            def execute(self, task, context):
                order.append(task.task_id)
                return TaskResult(task_id=task.task_id, state="completed")
        reg.register(_Sink())
        ctx = _ctx(); ctx.put("framework", _framework())
        plan = ExecutionPlan("p", 1, tasks=(
            TaskDefinition("other", "other", "other"),
            TaskDefinition("technology_normalization", "technology_normalization",
                           "technology_normalization", ("other",), optional=True)))
        backend = _routing(reg, InProcessContainerManager())
        # inclui o executor local para a tarefa "technology_normalization"
        TaskScheduler(reg, backend=backend).run(plan, ctx)
        self.assertEqual(order, ["other"])            # ordem do DAG preservada
        self.assertTrue(ctx.get("tech_components") is not None)


# ============================ Config / flag ============================== #
class ConfigTests(unittest.TestCase):
    def test_modes(self):
        self.assertIs(resolve_container_mode("enabled"), ContainerExecutionMode.ENABLED)
        self.assertIs(resolve_container_mode(""), ContainerExecutionMode.DISABLED)
        self.assertIs(resolve_container_mode("disabled"), ContainerExecutionMode.DISABLED)
        with self.assertRaises(ContainerConfigError):
            resolve_container_mode("maybe")

    def test_build_backend_none_when_disabled(self):
        reg = TaskRegistry()
        self.assertIsNone(build_execution_backend(
            reg, mode=ContainerExecutionMode.DISABLED))


# ============================ Checkpoints =============================== #
class CheckpointRecoveryTests(unittest.TestCase):
    def test_interrupted_container_task_needs_manual_review(self):
        checkpoint = {
            "task_states": {"technology_normalization": "running"},
            "plan": {"tasks": [{"task_id": "technology_normalization",
                                "task_type": "technology_normalization"}]}}
        recovery = plan_recovery(checkpoint, container_types=CONTAINER_ELIGIBLE_TYPES)
        self.assertIn("technology_normalization", recovery.needs_manual_review)
        self.assertNotIn("technology_normalization", recovery.reschedulable)


# ============================ Orquestração V2 =========================== #
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
        self.actions: list = []
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


class OrchestrationContainerTests(unittest.TestCase):
    def _cfg(self):
        return ScopeConfig.for_target_url("https://example.com/#/")

    def test_v2_container_enabled_preserves_results_and_emits_worker_events(self):
        cfg = self._cfg()
        events: list = []
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            base = OrchestratorV2(cve_intelligence=True).run(cfg)
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            containerized = OrchestratorV2(
                cve_intelligence=True,
                container_execution=ContainerExecutionMode.ENABLED).run(
                cfg, on_event=events.append)
        self.assertEqual(containerized.status, base.status)
        self.assertEqual([f.to_dict() for f in containerized.findings],
                         [f.to_dict() for f in base.findings])
        types = [e.get("type") for e in events]
        self.assertIn("worker_requested", types)
        self.assertIn("worker_cleanup_completed", types)

    def test_v2_default_has_no_worker_events(self):
        cfg = self._cfg()
        events: list = []
        with patch("pentest_pipeline.orchestration.orchestrator.BoundedTransport", side_effect=_mk):
            OrchestratorV2(cve_intelligence=True).run(cfg, on_event=events.append)
        self.assertFalse(any(str(e.get("type", "")).startswith("worker_") for e in events))


# ============================ Isolamento real =========================== #
class RealIsolationTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("docker") and os.environ.get("PENTEST_DOCKER_IT") == "1",
        "Docker indisponível ou PENTEST_DOCKER_IT!=1: isolamento real NÃO validado (mocks apenas).")
    def test_real_worker_isolation(self):  # pragma: no cover - requer Docker
        mgr = DockerContainerManager()
        self.assertTrue(mgr.available())
        resp = mgr.run(WorkerRequest("it", "normalize_technology_inventory",
                                     {"framework": _framework()}), ContainerConfig())
        self.assertEqual(resp.status, "completed")


if __name__ == "__main__":
    unittest.main()
