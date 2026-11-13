// Painel contextual (o que está acontecendo) + XAI (por que aconteceu).
// Lê apenas dados reais do backend: planos de etapa (stage_plan), decisões
// registradas (com origem) e estados de tarefa. Não inventa justificativas.
import ConclusionReview from "./conclusion-review";
import { assessmentLabel, executionLabel } from "./assessment-status";

const MACRO_TITLES = {
  scope: "Guardião do escopo", discovery: "Descoberta", planning: "Plano do agente",
  safe_tests: "Testes seguros", triage: "Triagem", remediation: "Correção",
  multiagent: "Análise multiagente", monitoring: "Monitoramento",
};
const MACRO_ORDER = ["scope", "discovery", "planning", "safe_tests", "triage",
  "remediation", "multiagent", "monitoring"];

// phase (dos eventos) -> macrofase
const PHASE_TO_MACRO = {
  scope: "scope", discovery: "discovery", planning: "planning",
  surface_checks: "safe_tests", checks: "safe_tests", approval: "safe_tests",
  triage: "triage", archive: "triage", remediation: "remediation",
  target_analysis: "multiagent", ai: "multiagent", monitor: "monitoring",
  complete: "monitoring",
};

const DECISION_SOURCE = {
  ai: { label: "Decisão de IA", tone: "ai" },
  deterministic: { label: "Decisão determinística", tone: "rule" },
  operator: { label: "Decisão do operador", tone: "operator" },
};

const AGENT_LABELS = {
  scope: "Guardião do escopo", discovery: "Descoberta", asset_fetch: "Coleta de assets",
  framework_inventory: "Inventário de framework", check_selection: "Plano do agente",
  surface_checks: "Testes de superfície", header_cookie_checks: "Headers e cookies",
  triage: "Triagem", remediation: "Correção", target_analysis: "Análise do alvo",
  ai_target_review: "Revisão de IA", ai_advisor: "Consultor de IA",
  technology_normalization: "Inventário de tecnologias", cve_research: "Pesquisa de CVEs",
  cve_correlation: "Correlação de CVEs", hypothesis_registration: "Registro de hipóteses",
  adaptive_planner: "Planejador adaptativo",
  independent_validation: "Validação independente",
  laboratory_validation: "Comparações locais no laboratório", demo_environment: "Diagnóstico do Docker",
  demo_policy_control: "Controle de autorização",
};

function intelligenceFrom(result) {
  return (result?.observations || []).find((o) => o?.type === "vulnerability_intelligence") || null;
}

function mitreFrom(result) {
  return (result?.observations || []).find((o) => o?.type === "mitre_contextualization") || null;
}

function adaptivePlansFrom(result) {
  return (result?.observations || []).filter((o) => o?.type === "adaptive_plan");
}

// Fase 6: resume a execução isolada (workers) a partir dos eventos estruturados.
function workerSummaryFrom(events) {
  const workers = (events || []).filter((e) => typeof e?.type === "string"
    && e.type.startsWith("worker_"));
  if (workers.length === 0) return null;
  const done = workers.filter((e) => e.type === "worker_completed");
  const failed = workers.filter((e) => e.type === "worker_failed"
    || e.type === "worker_timeout");
  const last = done[done.length - 1] || workers[workers.length - 1];
  return {
    count: new Set(workers.map((e) => e.worker_id)).size,
    completed: done.length, failed: failed.length,
    lastStatus: last?.status || last?.type?.replace("worker_", "") || "—",
    lastDurationMs: last?.duration_ms ?? null,
    lastTask: last?.task_type || "",
  };
}

function stagePlansFor(macroId, events, result) {
  // stage_plan vem dos eventos ao vivo ou de result.observations (agent_plan).
  const fromEvents = (events || []).filter((e) => e.type === "stage_plan");
  const planObs = (result?.observations || []).find((o) => o?.type === "agent_plan");
  const fromResult = planObs?.steps || [];
  const all = [...fromResult, ...fromEvents];
  const seen = new Set();
  return all.filter((step) => {
    const macro = PHASE_TO_MACRO[step.phase];
    if (macro !== macroId) return false;
    const key = step.step_id || step.check_id;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function decisionsFor(macroId, events) {
  return (events || [])
    .filter((e) => e.type === "decision" && PHASE_TO_MACRO[e.phase] === macroId)
    .map((e) => ({
      source: e.source || e.decision_source || "deterministic",
      message: e.message, checks: e.check_ids,
    }));
}

export default function XaiPanel({ observability, events = [], result = null,
  selectedPhase = null, onSelect = null, running = false, conclusions = [] }) {
  const macrophases = observability?.macrophases || [];
  const activeTasks = observability?.active_tasks || [];
  const byId = Object.fromEntries(macrophases.map((m) => [m.id, m]));
  const selected = selectedPhase && byId[selectedPhase];

  // Painel contextual: agentes/tarefas ativos agora.
  const adaptivePlans = adaptivePlansFrom(result);
  const lastPlan = adaptivePlans[adaptivePlans.length - 1] || null;
  const planner = activeTasks.find((t) => t.task_type === "adaptive_planner");
  const workers = workerSummaryFrom(events);

  const context = (
    <div className="xai-context" aria-label="O que está acontecendo agora">
      <p className="eyebrow">Contexto da execução</p>
      {conclusions.length > 0 && <details className="xai-revisions">
        <summary>Revisões de conclusões ({conclusions.length})</summary>
        {conclusions.map(c => <div key={`${c.subject_type}:${c.subject_id}`}><h3>{c.title}</h3><ConclusionReview conclusion={c} /></div>)}
      </details>}
      {events.some(e => e.validation_id) && <p className="xai-muted">
        Há validações locais registradas. <a href="#executions">Consultar operações, evidências e limitações</a>.
      </p>}
      {(planner || lastPlan) && (
        <p className="xai-plan-pill">
          Planejador adaptativo · {lastPlan ? `${(lastPlan.accepted || []).length} aprovadas` : "ativo"}
          {lastPlan && (lastPlan.rejected || []).length ? ` · ${lastPlan.rejected.length} rejeitadas` : ""}
          {lastPlan && lastPlan.replan_revision ? ` · replanejamento #${lastPlan.replan_revision}` : ""}
        </p>
      )}
      {workers && (
        <p className="xai-plan-pill xai-worker-pill">
          Execução de workers · {workers.count} worker{workers.count > 1 ? "s" : ""}
          {" · "}{workers.completed} ok{workers.failed ? ` · ${workers.failed} falha(s)` : ""}
          {workers.lastDurationMs != null ? ` · ${workers.lastDurationMs}ms` : ""}
        </p>
      )}
      {activeTasks.length === 0 ? (
        <p className="xai-muted">{running ? "Aguardando próxima tarefa executável…"
          : "Nenhum agente em execução."}</p>
      ) : (
        <ul className="xai-active-list">
          {activeTasks.map((task) => (
            <li key={task.task_id}>
              <span className="xai-dot" aria-hidden="true" />
              <strong>{AGENT_LABELS[task.task_type] || task.task_type}</strong>
              <small>{task.state === "running" ? "executando" : task.state}</small>
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  if (!selected) {
    return (
      <section className="xai-panel" aria-label="Explicabilidade">
        {context}
        <p className="xai-muted">Selecione um cartão da pipeline para ver o que foi
          executado, por quê, e com quais evidências.</p>
      </section>
    );
  }

  const plans = stagePlansFor(selected.id, events, result);
  const decisions = decisionsFor(selected.id, events);
  const nextIndex = MACRO_ORDER.indexOf(selected.id) + 1;
  const nextMacro = nextIndex < MACRO_ORDER.length ? MACRO_ORDER[nextIndex] : null;

  return (
    <section className="xai-panel" aria-label="Explicabilidade">
      {context}
      <div className="xai-detail">
        <header className="xai-detail-head">
          <h3>{MACRO_TITLES[selected.id] || selected.title}</h3>
          <span className={`xai-badge xai-${selected.status}`}>{selected.status}</span>
          {onSelect && (
            <button type="button" className="xai-close" onClick={() => onSelect(null)}
              aria-label="Fechar detalhes">×</button>
          )}
        </header>

        <dl className="xai-fields">
          <dt>O que foi executado</dt>
          <dd>
            {plans.length === 0 ? <span className="xai-muted">Ainda não registrado.</span> : (
              <ul>{plans.map((p, i) => <li key={i}>{p.action}</li>)}</ul>
            )}
          </dd>

          <dt>Por que esta etapa</dt>
          <dd>
            {decisions.length === 0 ? (
              <span className="xai-muted">Sem decisão registrada para esta etapa.</span>
            ) : (
              <ul className="xai-decisions">
                {decisions.map((d, i) => {
                  const meta = DECISION_SOURCE[d.source] || DECISION_SOURCE.deterministic;
                  return (
                    <li key={i}>
                      <span className={`xai-source xai-source-${meta.tone}`}>{meta.label}</span>
                      <span>{d.message}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </dd>

          <dt>Evidências consideradas</dt>
          <dd>
            {selected.tasks && selected.tasks.length > 0 ? (
              <ul>{selected.tasks.map((t) => (
                <li key={t.task_id}><strong>{AGENT_LABELS[t.task_type] || t.task_type}</strong> — {executionLabel(t.execution_status || t.state)}
                  {" · Análise: "}{assessmentLabel(t.assessment_status)}
                  {t.reason && <p className="xai-muted">{t.reason}</p>}
                  {t.reason_code && <details><summary>Critérios e dependências</summary>
                    <p>Motivo registrado: {t.reason_code}. Tarefa {t.optional ? "opcional" : "obrigatória no plano"}.</p>
                    <p>Depende de: {t.depends_on?.map(x => AGENT_LABELS[x] || x).join(", ") || "sem dependências"}.</p>
                    {t.output_summary?.skip_reasons && <p>Hipóteses não verificadas: {Object.entries(t.output_summary.skip_reasons).map(([r, n]) => `${r}: ${n}`).join("; ")}</p>}
                  </details>}
                </li>
              ))}</ul>
            ) : <span className="xai-muted">Sem tarefas vinculadas a esta macrofase.</span>}
          </dd>

          <dt>Resultado</dt>
          <dd>Execução: <strong>{executionLabel(selected.execution_status || selected.status)}</strong>.
            {" "}Completude da análise: <strong>{assessmentLabel(selected.assessment_status)}</strong>.</dd>

          <dt>Limitações</dt>
          <dd>
            {plans.find((p) => p.stop_condition)
              ? plans.find((p) => p.stop_condition).stop_condition
              : <span className="xai-muted">Hipóteses não são confirmação de vulnerabilidade;
                evidências seguem as regras de sanitização.</span>}
          </dd>

          {nextMacro && (
            <>
              <dt>Próxima etapa</dt>
              <dd>{MACRO_TITLES[nextMacro]}</dd>
            </>
          )}
        </dl>

        {selected.id === "planning" && <PlanningBlock plans={adaptivePlans} />}
        {selected.id === "multiagent" && <IntelligenceBlock intel={intelligenceFrom(result)} />}
        {selected.id === "multiagent" && <MitreBlock mitre={mitreFrom(result)} />}
      </div>
    </section>
  );
}

function PlanningBlock({ plans }) {
  if (!plans || plans.length === 0) return null;
  return (
    <div className="xai-intel" aria-label="Planejamento adaptativo">
      <p className="eyebrow">Planejamento adaptativo (hipóteses → prioridades)</p>
      <ul className="xai-hyps">
        {plans.map((plan, i) => (
          <li key={i}>
            <div className="xai-hyp-head">
              <strong>Revisão #{plan.replan_revision || i + 1}</strong>
              <span className="xai-badge">{plan.origin || "deterministic"}</span>
              <span className="xai-hyp-prio">{plan.trigger || "—"}</span>
            </div>
            <small>Priorizadas: {(plan.accepted || []).join(", ") || "nenhuma"}</small>
            {(plan.rejected || []).length > 0 && (
              <small>Rejeitadas: {plan.rejected.join(", ")}</small>
            )}
            {plan.reasons && Object.keys(plan.reasons).length > 0 && (
              <small className="xai-muted">
                {Object.entries(plan.reasons).map(([k, v]) => `${k}: ${v}`).join(" · ")}
              </small>
            )}
          </li>
        ))}
      </ul>
      <p className="xai-muted">Prioridade reordena apenas tarefas opcionais elegíveis;
        dependências, escopo e aprovações são preservados.</p>
    </div>
  );
}

function MitreBlock({ mitre }) {
  if (!mitre) return null;
  const counts = mitre.counts || {};
  const attributed = (mitre.mappings || []).filter((m) => m.mapping_status !== "unmapped");
  return (
    <div className="xai-intel" aria-label="Contextualização MITRE ATT&CK">
      <p className="eyebrow">MITRE ATT&CK (contextualização)</p>
      <p className="xai-muted">
        Fonte: {mitre.source} · aplicáveis: {counts.mapped || 0} · candidatas: {counts.candidate || 0} · não mapeadas: {counts.unmapped || 0}
      </p>
      {attributed.length === 0 ? (
        <p className="xai-muted">Nenhuma técnica atribuível com evidência. Classificação e contextualização — não é execução de técnicas nem prova de exploração.</p>
      ) : (
        <ul className="xai-hyps">
          {attributed.map((m) => (
            <li key={m.mapping_id}>
              <div className="xai-hyp-head">
                <strong>{m.technique_id}</strong>
                <span className={`xai-badge xai-${m.mapping_status}`}>
                  {m.mapping_status === "mapped" ? "aplicável" : "candidata"}
                </span>
                <span className="xai-hyp-prio">{(m.tactic_ids || []).join(", ")}</span>
              </div>
              <small>{m.technique_name} · achado: {m.finding_id}</small>
              <small className="xai-muted">{m.rationale}</small>
            </li>
          ))}
        </ul>
      )}
      <p className="xai-muted">Contextualização de findings existentes. Não executa técnicas nem comprova exploração.</p>
    </div>
  );
}

function isDismissed(h) {
  // "Deixou de ser hipótese": versão/produto conhecidos e não casam -> descartada.
  return h.correlation_status === "inconclusive" && h.confidence === "none";
}

function IntelligenceBlock({ intel }) {
  if (!intel) return null;
  const allHyps = intel.hypotheses || [];
  const hyps = allHyps.filter((h) => !isDismissed(h));
  const dismissed = allHyps.filter(isDismissed);
  return (
    <div className="xai-intel" aria-label="Inteligência de vulnerabilidades conhecidas">
      <p className="eyebrow">Vulnerabilidades conhecidas (hipóteses)</p>
      <p className="xai-muted">
        Cobertura: {intel.coverage} · fontes: {(intel.providers_ok || []).join(", ") || "nenhuma"}
        {intel.providers_failed?.length ? ` · indisponíveis: ${intel.providers_failed.join(", ")}` : ""}
        {dismissed.length ? ` · sem vínculo comprovado: ${dismissed.length}` : ""}
      </p>
      {hyps.length === 0 ? (
        <p className="xai-muted">Nenhuma hipótese ativa. {dismissed.length ? `${dismissed.length} aviso(s) sem identidade ou critérios suficientes para correlação.` : "Hipóteses não são achados confirmados no alvo."}</p>
      ) : (
        <ul className="xai-hyps">
          {hyps.map((h) => (
            <li key={h.hypothesis_id}>
              <div className="xai-hyp-head">
                <strong>{h.vulnerability_id}</strong>
                <span className={`xai-badge xai-${h.correlation_status}`}>{h.correlation_status}</span>
                <span className="xai-hyp-prio">{h.priority}</span>
              </div>
              <small>Componente: {h.component_id} · fontes: {(h.source_refs || []).join(", ")}</small>
              {(h.applicability_conditions || []).length > 0 && (
                <small>Motivo: {h.applicability_conditions.join("; ")}</small>
              )}
              <small className="xai-muted">{(h.limitations || []).join(" ")}</small>
            </li>
          ))}
        </ul>
      )}
      {dismissed.length > 0 && (
        <details className="xai-dismissed">
          <summary className="xai-muted">
            {dismissed.length} aviso(s) sem vínculo comprovado — não significa ausência de vulnerabilidades
          </summary>
          <ul className="xai-hyps">
            {dismissed.map((h) => (
              <li key={h.hypothesis_id}>
                <span className="xai-muted">{h.vulnerability_id} · {h.component_id} · {h.correlation_status}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
