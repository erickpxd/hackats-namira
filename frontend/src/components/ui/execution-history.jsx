import { useState } from "react";
import ConclusionReview, { conclusionLabel } from "./conclusion-review";
import Evidence from "./verification-evidence";

const states = {planned: "Planejada", ready: "Planejada", running: "Em andamento",
  completed: "Concluída", failed: "Falhou", cancelled: "Cancelada",
  inconclusive: "Sem conclusão", skipped: "Não realizada", timeout: "Tempo esgotado",
  not_evaluated: "Não avaliada", supported: "Correspondência nos dados", contradicted: "Fora do intervalo afetado"};
const names = {scope: "Validação do escopo", discovery: "Descoberta da aplicação",
  check_selection: "Seleção de verificações", asset_fetch: "Coleta de recursos públicos",
  framework_inventory: "Inventário de framework", surface_checks: "Verificações de superfície",
  header_cookie_checks: "Cabeçalhos e cookies", triage: "Triagem das evidências",
  remediation: "Recomendações de correção", target_analysis: "Análise complementar",
  ai_target_review: "Revisão da análise por IA", ai_advisor: "Revisão dos achados por IA",
  technology_normalization: "Normalização das tecnologias", cve_research: "Consulta de avisos de segurança",
  cve_correlation: "Correlação de CVEs", hypothesis_registration: "Registro de hipóteses",
  laboratory_validation: "Comparações locais", independent_validation: "Validação independente",
  normalize_technology_inventory: "Consistência do inventário",
  correlate_local_version: "Comparação de versão com um aviso", validate_result_structure: "Estrutura das evidências",
  verify_integrity: "Integridade dos dados", compare_local_results: "Comparação de resultados locais",
  analyze_local_metadata: "Análise dos metadados"};
Object.assign(names, {correlate_fixture_version: "Comparação da fixture local", inspect_demo_environment: "Diagnóstico real do Docker",
  demo_environment: "Diagnóstico do worker", demo_policy_control: "Controle de autorização"});
const label = value => names[value] || value || "Não registrado";
const date = value => value ? new Date(value).toLocaleString("pt-BR") : "Não registrado";
const duration = value => value == null ? "Duração não registrada" : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} s`;
const describe = e => e.presentation || {
  kind: e.worker_id || e.hypothesis_id ? "local_check" : "internal_step",
  category: e.worker_id || e.hypothesis_id ? "Verificação de dados" : "Processamento dos agentes",
  headline: states[e.execution_status] || "Estado não registrado",
  outcome: "Consulte as evidências desta atividade",
  explanation: "A conclusão de uma atividade não significa que uma vulnerabilidade foi reproduzida.",
};

function ExecutionCard({ e, hypotheses, catalog, onHypothesis }) {
  const p = describe(e);
  const hypothesis = hypotheses.find(h => h.hypothesis_id === e.hypothesis_id);
  return <details className="execution-card" data-status={e.execution_status} data-kind={p.kind} data-execution-id={e.execution_id}>
    <summary><span><strong>{hypothesis?.vulnerability_id && `${hypothesis.vulnerability_id} · `}{label(e.operation_id)}</strong>
      <small>{p.category} · {duration(e.duration_ms)}</small></span>
      <span className={`execution-state state-${e.execution_status}`}>{p.headline}</span></summary>
    <div className="execution-detail">
      <h3 className="verification-outcome">{p.outcome}</h3><p>{p.explanation}</p>
      {p.kind === "local_check" && <p className="execution-muted">{e.execution_backend === "docker"
        ? "Ambiente: worker Python no Docker." : e.execution_backend === "simulated" ? "Ambiente: simulação local." : "Ambiente: executor local."}
        {" "}Esta operação não é um teste no Kali.</p>}
      {e.hypothesis_id && <button type="button" className="review-link" onClick={() => onHypothesis(e.hypothesis_id)}>Ver hipótese e revisões</button>}
      {e.cleanup_status === "failed" && <p className="execution-cleanup-error">O runtime não confirmou a remoção do worker. É necessária revisão manual.</p>}
      {e.reason_code && <p><strong>Motivo:</strong> {e.result_summary}</p>}
      {e.authorization_status === "denied" && <p>Controle operacional: autorização negada antes de iniciar a operação solicitada. Isso não é um achado no alvo.</p>}
      {e.terminal_capture && <TerminalCapture capture={e.terminal_capture} />}
      <details className="evidence-section"><summary>Dados usados e resultado da comparação</summary>
        <h3>Evidências consultadas</h3><Evidence refs={e.evidence_refs?.filter(ref => !e.output_evidence_refs?.includes(ref))} catalog={catalog} />
        <h3>Evidências produzidas</h3><Evidence refs={e.output_evidence_refs} catalog={catalog} />
      </details>
      <details className="execution-audit technical-record"><summary>Detalhes técnicos e auditoria</summary>
        <p>Resposta original: {e.result_summary}</p>
        <p>Resultado estruturado: {states[e.validation_status] || e.validation_status || "Não avaliado"}</p>
        {e.worker_responded != null && <p>{e.worker_responded ? "O worker devolveu uma resposta estruturada vinculada a esta execução." : "O worker não confirmou uma resposta."}</p>}
        <dl className="execution-facts">
          <div><dt>Agente responsável</dt><dd>{label(e.agent_id)}</dd></div>
          <div><dt>Operação</dt><dd>{e.operation_id}</dd></div>
          <div><dt>Início</dt><dd>{date(e.started_at)}</dd></div><div><dt>Fim</dt><dd>{date(e.finished_at)}</dd></div>
          <div><dt>Identificador da execução</dt><dd>{e.execution_id}</dd></div><div><dt>Worker</dt><dd>{e.worker_id || "Não utilizado ou não registrado"}</dd></div>
          <div><dt>Campanha / tarefa</dt><dd>{e.campaign_id} / {e.task_id}</dd></div>
        </dl>
        <p><strong>Por que foi selecionada?</strong> {e.selection_reason || "Motivo não registrado."}</p>
        {e.authorization_status && <p>Autorização: {e.authorization_status === "approved" ? "Permitida" : "Negada"} · Motivo registrado: {e.decision_reason}</p>}
        {e.error_code && <p>Falha registrada: {e.error_code}</p>}
        <p className="execution-muted">{e.limitations?.join(" ") || "Limitações não registradas."}</p>
      </details>
    </div>
  </details>;
}

function TerminalCapture({ capture: c }) {
  return <details className="terminal-capture"><summary>Saída real do processo · somente leitura</summary>
    <p>Docker · código de saída {c.exit_code ?? "não registrado"} · {duration(c.duration_ms)} · limpeza: {c.cleanup_status}</p>
    {c.capture_available ? <><h4>stdout</h4><pre>{c.stdout_excerpt || "(sem saída)"}</pre>
      <h4>stderr</h4><pre>{c.stderr_excerpt || "(sem saída)"}</pre>
      <p>{c.output_truncated ? "Saída limitada por tamanho." : "Saída dentro do limite de captura."} Dados sensíveis são removidos antes de salvar.</p></>
      : <p>{c.capture_expired ? "Retenção encerrada; saída removida. Metadados e hash permanecem no histórico." : "Saída indisponível ou integridade não verificada."}</p>}
    <details><summary>Auditoria da captura</summary><dl className="execution-facts">
      <div><dt>Execução</dt><dd>{c.execution_id}</dd></div><div><dt>Worker</dt><dd>{c.worker_id}</dd></div>
      <div><dt>Imagem</dt><dd>{c.container_image}</dd></div><div><dt>Comando do worker</dt><dd>{c.command?.join(" ")}</dd></div>
      <div><dt>Início</dt><dd>{date(c.started_at)}</dd></div><div><dt>Fim</dt><dd>{date(c.finished_at)}</dd></div>
      <div><dt>SHA-256 da captura sanitizada</dt><dd>{c.evidence_hash}</dd></div><div><dt>Retenção até</dt><dd>{date(c.expires_at)}</dd></div>
    </dl></details>
  </details>;
}

export default function ExecutionHistory({ executions = [], hypotheses = [], evidenceCatalog = [], conclusions = [], verificationSummary }) {
  const [tab, setTab] = useState("executions");
  const [filter, setFilter] = useState("all");
  const [selectedHypothesis, setSelectedHypothesis] = useState(null);
  const visible = executions.filter(e => filter === "all" || e.execution_status === filter);
  const local = visible.filter(e => describe(e).kind === "local_check");
  const showHypothesis = id => {setSelectedHypothesis(id); setTab("hypotheses");};
  const card = e => <ExecutionCard key={e.execution_id} e={e} hypotheses={hypotheses} catalog={evidenceCatalog} onHypothesis={showHypothesis} />;
  return <section className="execution-history" aria-label="Verificações e hipóteses"
    data-campaign-id={executions[0]?.campaign_id || hypotheses[0]?.campaign_id}>
    <p className="eyebrow">Evidências da campanha</p>
    <h1>O que foi verificado.</h1>
    <p className="execution-intro">Veja o que recebeu resposta do alvo, o que foi comparado localmente e quais hipóteses ainda precisam de evidência.</p>
    {verificationSummary && <div className="verification-overview">
      <div><strong>{verificationSummary.target_responses}</strong><span>respostas HTTP do alvo</span><small>{verificationSummary.target_requests} requisições registradas</small></div>
      <div><strong>{verificationSummary.local_checks_completed}</strong><span>comparações locais concluídas</span><small>{verificationSummary.hypotheses_compared} de {verificationSummary.hypotheses_total} hipóteses comparadas</small></div>
      <div><strong>Não registrada</strong><span>execução no Kali</span><small>Sem reprodução de vulnerabilidade registrada</small></div>
    </div>}
    <div className="execution-tabs" aria-label="Visualizações">
      <button type="button" aria-pressed={tab === "executions"} onClick={() => setTab("executions")}>Verificações</button>
      <button type="button" aria-pressed={tab === "hypotheses"} onClick={() => setTab("hypotheses")}>Hipóteses <span>{hypotheses.length}</span></button>
    </div>
    {tab === "executions" ? <>
      <div className="execution-toolbar"><h2>Comparações de dados já coletados</h2>
        <label>Estado <select value={filter} onChange={e => setFilter(e.target.value)}>
          <option value="all">Todos</option>{["planned", "running", "completed", "failed", "cancelled", "inconclusive", "skipped"].map(s => <option key={s} value={s}>{states[s]}</option>)}
        </select></label></div>
      {!local.length && <p className="execution-empty">{executions.length ? "Nenhuma comparação local neste estado." : "Nenhuma verificação estruturada registrada nesta campanha."}</p>}
      {local.map(card)}
      {[["target_step", "Coleta e checagens HTTP"], ["internal_step", "Processamento dos agentes"]].map(([kind, title]) => {
        const group = visible.filter(e => describe(e).kind === kind);
        return group.length > 0 && <details className="workflow-group" key={kind}><summary>{title} <span>({group.length} etapas)</span></summary>
          <p className="execution-muted">Estas são etapas do fluxo. Seus estados indicam o andamento do trabalho.</p>{group.map(card)}
        </details>;
      })}
      {conclusions.some(c => c.subject_type === "finding") && <details className="finding-reviews">
        <summary>Revisão independente dos achados</summary>
        {conclusions.filter(c => c.subject_type === "finding").map(c => <div key={c.subject_id}><h3>{c.title}</h3><ConclusionReview conclusion={c} /></div>)}
      </details>}
    </> : <>
      <h2>Hipóteses pesquisadas</h2>
      <p className="execution-intro">Encontrar um aviso de segurança não confirma que o sistema seja afetado. Veja a comparação disponível para cada hipótese.</p>
      {!hypotheses.length && <p className="execution-empty">Nenhuma hipótese registrada.</p>}
      {hypotheses.map(h => {
        const related = executions.filter(e => e.hypothesis_id === h.hypothesis_id);
        const latest = related.at(-1);
        const conclusion = conclusions.find(c => c.subject_type === "hypothesis" && c.subject_id === h.hypothesis_id);
        const p = latest ? describe(latest) : null;
        return <details key={h.hypothesis_id} className="hypothesis-card" data-hypothesis-id={h.hypothesis_id}
          open={selectedHypothesis === h.hypothesis_id} onToggle={event => {if (event.currentTarget.open) setSelectedHypothesis(h.hypothesis_id); else setSelectedHypothesis(id => id === h.hypothesis_id ? null : id);}}>
          <summary><strong>{h.vulnerability_id || "Hipótese registrada"}</strong>
            <span className="execution-state hypothesis">{conclusionLabel(conclusion?.current_status || h.correlation_status)}</span></summary>
          <div className="hypothesis-detail">
            <h3>{p?.outcome || "Sem comparação local registrada"}</h3>
            <p>{p?.explanation || h.verification_note || "A pesquisa encontrou este aviso, mas não há verificação local vinculada a ele."}</p>
            <ConclusionReview conclusion={conclusion} />
            <details className="evidence-section"><summary>Evidências e histórico da hipótese</summary>
              <p>Motivos registrados: {h.applicability_conditions?.join(" ") || "Não registrados"}</p>
              <p>Limitações: {h.limitations?.join(" ") || "Uma hipótese não equivale a uma vulnerabilidade reproduzida."}</p>
              <h3>Verificações vinculadas</h3>
              {related.length ? related.map(e => <p key={e.execution_id}>{label(e.operation_id)} · {describe(e).headline}</p>) : <p>Nenhuma verificação vinculada.</p>}
              <Evidence refs={h.evidence_refs} catalog={evidenceCatalog} />
              <details className="technical-record"><summary>Identificação da hipótese</summary><p>{h.hypothesis_id}</p><p>Estado original: {h.correlation_status}</p></details>
            </details>
          </div>
        </details>;
      })}
    </>}
  </section>;
}
