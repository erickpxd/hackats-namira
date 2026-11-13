# Fase 7 — auditoria dos contratos

Baseline confirmado em 13/11/2026: 255 testes aprovados com `PENTEST_DOCKER_IT=1`,
zero falhas/pulados. Auditoria Docker da Fase 6.5 preservada, sem reinstalação.

| Existente | Estado / lacuna relevante |
|---|---|
| `models.Finding` | ID, status, prova/limitações textuais; não tem evidência estruturada suficiente para revalidar toda categoria. Preservar registro original. |
| `VulnerabilityHypothesis` | candidate/potentially_affected/version_unknown/not_affected/inconclusive, referências e histórico de correlação; não equivale a classificação independente. |
| Evidência do laboratório | Metadados com SHA-256 e vínculos campanha/hipótese/tarefa/execução/worker; falta avaliação independente de suficiência, tempo e contradição. |
| `LaboratoryValidationResult` | Estado operacional separado de supported/contradicted/inconclusive/not_evaluated. Reutilizar sem promoção automática. |
| `TaskResult`, `AgentDecision` | Resultado de tarefa e decisão com origem/referências; faltam contratos específicos de validação/reflexão/revisão. |
| `TriageAgent` | Deduplica/ordena findings, não revalida suas conclusões. |
| `EvidenceReviewAgent` | Resume textos de provas/limites; não valida hashes nem altera estados. |
| `FollowupHypothesisAgent` | Perguntas derivadas de findings, `unverified_on_target`; preservar sem confundir com CVEs. |
| AdaptivePlanner / PlanValidator / ReplanningPolicy | Reordenam opcionais existentes, limitam revisões e repetição; DAG não adiciona tarefas dinamicamente. Novas recomendações ficam registradas para revisão posterior, sem reexecução automática. |
| Event Store / ExecutionHistory | Persistem eventos e projetam tentativas; ampliar somente os campos de revisão e a projeção de conclusões. |
| CheckpointStore | Eventos/resultados atômicos com hash e recuperação conservadora; incluir revisões nos mesmos eventos/resultados. |

Integração adotada: tarefa opt-in `independent_validation`, após dependências
terminais (inclusive falhas não críticas), no scheduler atual. Cancelamento do
operador e falhas críticas continuam interrompendo a campanha. Oito macrofases
preservadas. `PENTEST_INDEPENDENT_VALIDATION=enabled` ativa a camada no V2;
legado e V2 sem a flag mantêm comportamento anterior.

Classificação independente aditiva: suspected/potential/confirmed/rejected/
inconclusive. `confirmed` exige categoria suportada e observação direta com
critério explícito; CVE local nunca é promovida a finding confirmado. Texto livre,
hash ou status legado isolados não satisfazem confirmação. Respostas HTTP não
são repetidas: metadados mínimos das respostas já coletadas sustentam revisão de
cabeçalhos; outras categorias sem prova estruturada permanecem inconclusivas.

Revisões mantêm estado original, proposta, decisão determinística, origem,
evidências, fingerprint do conjunto revisado e versão. Evidência ausente não é
evidência contrária. Mesmos dados não provocam outra reflexão; limite por sujeito
e por campanha também impede ciclos com novos dados repetitivos.
