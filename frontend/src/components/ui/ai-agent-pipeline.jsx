import {
  GitCompareArrows, ListChecks, Network, Radar, ShieldCheck,
  Sparkles, TestTubeDiagonal, Wrench,
} from "lucide-react";

// Cada cartão tem um `id` que casa com as macrofases do backend (projection.py).
const PIPELINE_STAGES = [
  {
    id: "scope", number: "01", title: "Guardião do escopo",
    description: "Valida origem, método, orçamento e condição de parada antes de qualquer ação.",
    phases: ["scope"], icon: ShieldCheck,
  },
  {
    id: "discovery", number: "02", title: "Descoberta",
    description: "Identifica a aplicação, tecnologias e rotas públicas incluídas na campanha.",
    phases: ["discovery"], icon: Radar,
  },
  {
    id: "planning", number: "03", title: "Plano do agente",
    description: "Seleciona verificações declaradas e registra a origem de cada decisão.",
    phases: ["planning"], icon: Sparkles,
  },
  {
    id: "safe_tests", number: "04", title: "Testes seguros",
    description: "Executa verificações de leitura com cadência, aprovação e volume limitados.",
    phases: ["checks", "surface_checks", "approval"], icon: TestTubeDiagonal,
  },
  {
    id: "triage", number: "05", title: "Triagem",
    description: "Classifica evidência, severidade e confiança sem inferir exploração.",
    phases: ["triage"], icon: ListChecks,
  },
  {
    id: "remediation", number: "06", title: "Correção",
    description: "Relaciona os achados a orientações de código e testes de regressão.",
    phases: ["remediation"], icon: Wrench,
  },
  {
    id: "multiagent", number: "07", title: "Análise multiagente",
    description: "Cruza inventário, evidências e hipóteses sobre a URL em agentes paralelos.",
    phases: ["target_analysis", "ai"], icon: Network,
  },
  {
    id: "monitoring", number: "08", title: "Monitoramento",
    description: "Consolida a execução e destaca mudanças em relação a campanhas comparáveis.",
    phases: ["monitor", "complete"], icon: GitCompareArrows,
  },
];

const STATUS_LABELS = {
  complete: "Concluído",
  active: "Em curso",
  pending: "Aguardando",
  error: "Com erro",
  stopped: "Interrompido",
  inconclusive: "Inconclusivo",
  approval: "Aprovação",
  skipped: "Não realizada", partial: "Análise parcial",
};

// Estados reais do backend -> classe visual + rótulo preservados.
const V2_VISUAL = {
  running: "active", ready: "active", waiting_approval: "approval",
  completed: "complete", skipped: "skipped", pending: "pending",
  failed: "error", cancelled: "stopped", inconclusive: "inconclusive",
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
};

function targetHost(target) {
  try {
    return new URL(target).host || "Alvo autorizado";
  } catch {
    return "Alvo autorizado";
  }
}

export default function AgentPipeline({
  events, running, state, target = "", maxRequests, reportAvailable = false,
  observability = null, selectedPhase = null, onSelectPhase = null,
}) {
  const hasProjection = observability && observability.mode === "v2"
    && Array.isArray(observability.macrophases) && observability.macrophases.length === 8;

  // ---- Caminho V2: estados reais das macrofases (múltiplos agentes) -------
  const macroById = {};
  if (observability && Array.isArray(observability.macrophases)) {
    for (const macro of observability.macrophases) macroById[macro.id] = macro;
  }

  // ---- Caminho legado: inferência por evento (campanhas antigas) ----------
  const eventStageIndexes = events
    .map((event) => PIPELINE_STAGES.findIndex((stage) => stage.phases.includes(event.phase)))
    .filter((index) => index >= 0);
  const reachedStages = new Set(eventStageIndexes);
  const legacyCurrent = eventStageIndexes.length
    ? eventStageIndexes[eventStageIndexes.length - 1]
    : running ? 0 : -1;
  const finished = state === "completed";
  const failedStage = [...events].reverse().find((event) =>
    ["error", "agent_error"].includes(event.type) &&
    PIPELINE_STAGES.some((stage) => stage.phases.includes(event.phase)));
  const failedIndex = failedStage
    ? PIPELINE_STAGES.findIndex((stage) => stage.phases.includes(failedStage.phase))
    : -1;

  const legacyStatus = (index) => {
    if (finished) return "complete";
    if (index === legacyCurrent) {
      if (index === failedIndex || state === "failed") return "error";
      if (!running && state === "stopped") return "stopped";
      if (!running && state === "inconclusive") return "inconclusive";
      return running ? "active" : "complete";
    }
    if (reachedStages.has(index) || (legacyCurrent >= 0 && index < legacyCurrent)) return "complete";
    return "pending";
  };

  const cardVisual = (stage, index) => {
    if (hasProjection) {
      const macro = macroById[stage.id];
      if (macro?.status === "completed" && macro.assessment_status && macro.assessment_status !== "complete") return "partial";
      return V2_VISUAL[macro?.status] || "pending";
    }
    return legacyStatus(index);
  };

  const activeIndexes = PIPELINE_STAGES
    .map((stage, index) => (cardVisual(stage, index) === "active"
      || cardVisual(stage, index) === "approval" ? index : -1))
    .filter((i) => i >= 0);
  const headerIndex = activeIndexes.length
    ? activeIndexes[0]
    : Math.max(0, hasProjection
      ? PIPELINE_STAGES.map((s, i) => (cardVisual(s, i) === "complete" ? i : -1)).filter(i => i >= 0).pop() ?? 0
      : legacyCurrent);
  const activeStage = PIPELINE_STAGES[Math.max(0, headerIndex)];

  // Agentes ativos em paralelo (projeção real) ou mensagem textual (legado).
  const activeTasks = (hasProjection && observability.active_tasks) || [];
  const activeAgents = activeTasks.map((t) => AGENT_LABELS[t.task_type] || t.task_type);
  const latestEvent = [...events].reverse().find((event) => event.message);
  const latestMessage = latestEvent?.message || "Preparando o escopo da próxima varredura…";

  const progress = hasProjection
    ? observability.progress?.global_estimate ?? 0
    : finished ? 100
      : legacyCurrent < 0 ? 0
        : Math.min(96, ((reachedStages.size - (running ? 0.5 : 0)) / PIPELINE_STAGES.length) * 100);
  const errorCount = events.filter((event) =>
    ["error", "agent_error", "denied"].includes(event.type)).length;
  const requestCount = events.filter((event) => event.type === "request").length;

  const selectStage = (stage) => { if (onSelectPhase) onSelectPhase(stage.id); };

  return (
    <section className="pipeline-section" aria-labelledby="pipeline-title">
      <div className="pipeline-flow-board">
        <header className="pipeline-flow-header">
          <div>
            <p className="eyebrow">Fluxo operacional</p>
            <h2 id="pipeline-title">{activeStage.number} · {activeStage.title}</h2>
            <p>{targetHost(target)} · os cartões avançam somente com eventos reais da API.</p>
          </div>
          <div className={`pipeline-flow-state flow-state-${running ? "active" : finished ? "complete" : state}`}>
            <span aria-hidden="true" />
            {running ? "Em execução" : finished ? (observability?.assessment_status === "partial" ? "Encerrada · análise parcial" : "Execução encerrada") : STATUS_LABELS[cardVisual(activeStage, Math.max(0, headerIndex))] || "Pronta"}
          </div>
        </header>

        <div className="pipeline-flow-message" key={`${latestEvent?.timestamp || "idle"}-${latestMessage}`}>
          <span className={running ? "pipeline-message-pulse" : "pipeline-message-pulse is-idle"} aria-hidden="true" />
          {activeAgents.length > 0 ? (
            <p>{activeAgents.length} agente{activeAgents.length > 1 ? "s" : ""} em execução: {activeAgents.join(" · ")}</p>
          ) : (
            <p>{latestMessage}</p>
          )}
          <small>{requestCount}/{maxRequests || "—"} requisições</small>
        </div>

        <div className="pipeline-grid pipeline-connected-grid">
        {PIPELINE_STAGES.map((stage, index) => {
          const status = cardVisual(stage, index);
          const Icon = stage.icon;
          const macro = macroById[stage.id];
          const isSelected = selectedPhase === stage.id;
          return (
            <article
              className={`pipeline-card pipeline-${status} pipeline-position-${index + 1}${isSelected ? " is-selected" : ""}`}
              key={stage.number}
              aria-current={status === "active" ? "step" : undefined}
              role={onSelectPhase ? "button" : undefined}
              tabIndex={onSelectPhase ? 0 : undefined}
              aria-pressed={onSelectPhase ? isSelected : undefined}
              onClick={onSelectPhase ? () => selectStage(stage) : undefined}
              onKeyDown={onSelectPhase ? (e) => {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectStage(stage); }
              } : undefined}
            >
              <div className="pipeline-card-top">
                <span className="pipeline-number">{stage.number}</span>
                <span className="pipeline-status"><span aria-hidden="true" />{STATUS_LABELS[status]}</span>
              </div>
              <Icon className="pipeline-icon" size={19} strokeWidth={1.7} aria-hidden="true" />
              <h3>{stage.title}</h3>
              <p>{stage.description}</p>
              {macro && macro.active_count > 0 && (
                <span className="pipeline-agent-count">{macro.active_count} ativo{macro.active_count > 1 ? "s" : ""}</span>
              )}
              {status === "active" && <span className="pipeline-card-pulse" aria-hidden="true" />}
              {index < PIPELINE_STAGES.length - 1 && (
                <span className={`pipeline-link ${running && activeIndexes.some((i) => index < i) ? "is-moving" : ""}`} aria-hidden="true" />
              )}
            </article>
          );
        })}
        </div>

        <footer className="pipeline-flow-footer">
          <span><small>ETAPAS ENCERRADAS</small><strong>{Math.round(progress)}%</strong></span>
          <span><small>REQUISIÇÕES</small><strong>{requestCount}/{maxRequests || "—"}</strong></span>
          <span><small>EVENTOS</small><strong>{events.length}</strong></span>
          <span><small>ERROS</small><strong>{errorCount}</strong></span>
          <span><small>RELATÓRIO</small><strong>{reportAvailable ? "Pronto" : "Pendente"}</strong></span>
        </footer>
      </div>
    </section>
  );
}
