export default function Evidence({ refs = [], catalog = [] }) {
  if (!refs.length) return <p className="execution-muted">Nenhuma evidência vinculada.</p>;
  return <div className="execution-evidence">{refs.map(ref => {
    const item = catalog.find(e => e.evidence_id === ref);
    return <details key={ref}><summary>{item?.title || 'Evidência registrada'}</summary>
      {item ? <>
        <p>{item.summary}</p>
        {item.technology && <p>Componente observado: {item.technology} · Versão: {item.version || 'Não identificada'}</p>}
        {item.vulnerability_id && <p>Aviso: {item.vulnerability_id} · Fonte: {item.source_refs?.join(', ') || 'Não registrada'}</p>}
        {item.criteria?.length > 0 && <ul>{item.criteria.map((r, i) => <li key={i}>
          {r.product} ({r.ecosystem || 'Ecossistema não registrado'}):
          {r.introduced ? ` a partir de ${r.introduced};` : ' início não informado;'}
          {r.fixed ? ` corrigido em ${r.fixed}.` : ' correção não informada.'}
          {r.versions?.length > 0 && ` Versões enumeradas: ${r.versions.join(', ')}.`}
        </li>)}</ul>}
      </> : <p>Os metadados desta referência não estão disponíveis no relatório.</p>}
      <details className="technical-record"><summary>Identificação e integridade do registro</summary>
        <p>Referência: {ref}</p>
        {item && <><p>Origem: {item.source} · Certeza: {item.certainty || 'Não registrada'}</p>
          {item.sha256 && <p>SHA-256: {item.sha256}</p>}</>}
      </details>
    </details>;
  })}</div>;
}
