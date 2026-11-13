export const assessmentLabel = value => ({complete: "Completa no escopo selecionado", partial: "Parcial",
  inconclusive: "Inconclusiva", blocked: "Bloqueada"}[value] || "Ainda não avaliada");
export const executionLabel = value => ({completed: "Encerrada", failed: "Falhou", cancelled: "Cancelada",
  skipped: "Não realizada", running: "Em andamento", pending: "Pendente", ready: "Pronta",
  inconclusive: "Encerrada sem conclusão"}[value] || value);

export default function AssessmentStatus({ execution, assessment, demo }) {
  return <div className={`assessment-summary assessment-${assessment || "pending"}`} role="status">
    {demo && <strong>DEMONSTRAÇÃO · Fixtures locais, processos Docker reais</strong>}
    <span>Execução: <strong>{executionLabel(execution)}</strong> · Análise: <strong>{assessmentLabel(assessment)}</strong></span>
    {assessment && assessment !== "complete" && <small>Há dados ausentes, etapas inconclusivas ou verificações não realizadas. Consulte os motivos na pipeline.</small>}
    {demo && <small>Nenhum alvo externo consultado. Avisos fictícios; nenhuma vulnerabilidade reproduzida.</small>}
  </div>;
}
