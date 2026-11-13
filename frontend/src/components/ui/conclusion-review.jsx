const labels = {suspected: 'Suspeita', potential: 'Possível correspondência', confirmed: 'Observação sustentada',
  rejected: 'Hipótese não sustentada', inconclusive: 'Sem conclusão', supported: 'Sustentada pelos dados',
  partially_supported: 'Parcialmente sustentada', contradicted: 'Contradita pelos dados',
  unsupported: 'Sem sustentação válida', insufficient_evidence: 'Evidência insuficiente',
  valid: 'Válida', invalid: 'Inválida', partial: 'Parcial', unavailable: 'Indisponível',
  not_affected: 'Fora do intervalo afetado', potentially_affected: 'Possível correspondência',
  version_unknown: 'Versão não identificada', candidate: 'Candidata'};
export const conclusionLabel = value => labels[value] || value || 'Não revisada';

export default function ConclusionReview({ conclusion, compact = false }) {
  if (!conclusion) return null;
  return <div className="conclusion-review" data-subject-id={conclusion.subject_id}>
    <p><strong>Resultado da revisão:</strong> {conclusionLabel(conclusion.current_status)}</p>
    {!compact && <details className="conclusion-history">
      <summary>Como chegamos a este resultado ({conclusion.revisions?.length || 0} revisões)</summary>
      <p>Avaliação inicial: {conclusionLabel(conclusion.initial_status)} · Correlação original: {conclusionLabel(conclusion.original_status)}</p>
      {(conclusion.revisions || []).map(record => {
        const r = record.revision;
        return <details className="conclusion-revision" key={r.revision_id} data-revision-id={r.revision_id}>
          <summary>Revisão {r.version} · {r.accepted ? 'Proposta aprovada' : 'Proposta rejeitada'}</summary>
          <p>{conclusionLabel(r.previous_status)} → proposta: {conclusionLabel(r.proposed_status)} → resultado: {conclusionLabel(r.approved_status)}</p>
          <p>{r.reason}</p>
          <p>Reflexão registrada: {record.reflection.reasoning_summary}</p>
          <p>Evidências favoráveis: {record.validation.supporting_evidence_refs?.length || 0} · Evidências contrárias: {record.validation.contradicting_evidence_refs?.length || 0}</p>
          <p>{record.validation.limitations?.join(' ')}</p>
          <details className="technical-record"><summary>Detalhes técnicos da revisão</summary>
            <p>Estado anterior: {r.previous_status} · Proposto: {r.proposed_status} · Aprovado: {r.approved_status}</p>
            <p>Integridade: {conclusionLabel(record.validation.integrity_status)} · Sustentação: {conclusionLabel(record.validation.status)}</p>
            <p>Origem da reflexão: {record.reflection.decision_source}</p>
            {record.reflection.fallback_reason && <p>Análise determinística utilizada: {record.reflection.fallback_reason}</p>}
            <p>Evidências utilizadas: {r.evidence_refs?.join(', ') || 'Nenhuma; sem promoção da conclusão'}</p>
            <p>Regras observadas: {record.validation.validation_rules?.join(', ') || 'Vínculos e critérios conferidos'}</p>
            <p>Data: {new Date(r.created_at).toLocaleString('pt-BR')} · ID: {r.revision_id}</p>
            <p>Conjunto revisado (SHA-256): {r.evidence_fingerprint}</p>
            {record.revalidation && <p>Nova verificação: {record.revalidation.task_id} · {record.revalidation.status}.
              {' '}{record.revalidation.limitation} {record.revalidation.reasons?.join(', ')}</p>}
          </details>
        </details>;
      })}
    </details>}
  </div>;
}
