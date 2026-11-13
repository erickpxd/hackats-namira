# Migração Arquitetural — Progresso

> Registro compacto. Detalhes em `migration-baseline.md` e `orchestrator-v2-plan.md`.

## Fase atual
**Correção da orquestração e demonstração auditável validadas em 13/11/2026.**
Baseline medido antes da correção: 333 testes com Docker real, sem skips.
Resultado atual: **348 testes aprovados, zero falhas e zero pulados** com
`PENTEST_DOCKER_IT=1`; build React aprovado; 15 verificações de navegador da demo
e 18 de regressão da Fase 7 aprovadas. Fases 1–7 e contextualização MITRE da Fase 8
preservadas. Não houve execução ofensiva nem implementação de técnicas no Kali.

Veja [diagnóstico, evidências e reprodução da demonstração](orchestration-auditable-demo.md),
[manifesto](auditable-demo-manifest.json) e [relatório](auditable-demo-report.md).
Execução concluída e análise parcial são estados independentes. Skips preservam
motivos e dependências; avisos locais percorrem correlação/registro/laboratório;
saídas reais de quatro workers Docker podem ser consultadas em modo somente leitura.
O backend local foi reiniciado apenas após verificar que estava ocioso, mantendo
campanhas salvas. O baseline histórico de 315 corresponde às fases anteriores.

Entregas da Fase 8:
- **Contextualização MITRE ATT&CK (P1):** contrato `MitreMapping`, catálogo curado
  (IDs ATT&CK válidos por categoria de verificação, nunca por texto de CVE), mapeador
  conservador (`mapped`/`candidate`/`unmapped`), exige evidência, distingue
  vulnerabilidade conhecida de comportamento adversário observado, flag
  `PENTEST_MITRE_ATTACK` (padrão desligado). Seção no relatório e bloco na view
  Inteligência. **Classificação/contextualização — não executa técnicas de ataque.**
- **Worker Docker especializado (P2):** reusa `ContainerManager`/`LaboratoryManager`/
  `PolicyEngine` já existentes (imagem allowlisted, comando fixo, não-root, FS somente
  leitura, `--network none`, `no-new-privileges`, `--cap-drop ALL`, limites e tmpfs
  noexec/nosuid). Nenhuma reconstrução.
- **Cenário A/B/C demonstrável (P3):** `backend/demo/poc_final_demo.py` dirige os
  componentes reais com fixtures locais (offline, sem Docker): A hipótese sustentada
  (`potential`), B contradita (`rejected`), C evidência insuficiente (`inconclusive`),
  com a camada MITRE anexada.
- **Relatório (P5) e demo E2E (P6):** seção MITRE no Markdown, demonstração a partir
  da API pública `run_scan`/OrchestratorV2. Comparação local de versão permanece
  hipótese, nunca confirmação de exploração.
- **Qualidade (P7):** `tests/test_mitre_mapping.py` (18 testes) cobre contrato,
  catálogo, mapeador, observação, gate de flag e E2E.

Marcos anteriores abaixo são históricos. Aceite e limites da Fase 8 em
`poc-final-validation.md`.

## Etapas concluídas
- **Fase 8:** contextualização MITRE ATT&CK (`MitreMapping`, catálogo curado, mapeador
  conservador), reuso do worker Docker/laboratório, demo A/B/C via componentes reais +
  fixtures locais, seção MITRE no relatório e na view Inteligência, flag
  `PENTEST_MITRE_ATTACK`. (333 testes)
- **Fase 7:** EvidenceValidator, FindingClassifier, ReflectionAgent, DecisionValidator,
  revisões versionadas, controles de repetição, propostas de revalidação sem
  execução automática, API/relatórios/React/XAI persistentes. (304 testes)
- **Fase 1:** contratos, feature flag `PENTEST_ORCHESTRATOR`, dispatcher `run_campaign`, baseline. (104 testes)
- **Fase 2 (marcos 1–8):** máquina de estados, TaskRegistry, TaskScheduler (DAG + concorrência),
  ExecutionContext, OrchestratorV2, adaptadores dos agentes, checkpoints, ativação do V2. (131 testes)
- **Fase 3:** Event Store, projeção de macrofases (8 cartões), API `observability` no `/api/status`
  + endpoint paginado `/api/observability/events`, checkpoints no worker, pipeline visual multi-agente,
  painel contextual e XAI no frontend. (144 testes)
- **Fase 4:** CVE Intelligence passiva — inventário de tecnologias, pesquisa em bases públicas
  (NVD/OSV/CISA KEV) via cliente HTTP com allowlist, correlação por versão, registro de hipóteses
  (separadas de achados), 4 executores no DAG, flag `PENTEST_CVE_INTELLIGENCE`, seção no relatório
  e bloco XAI no frontend. (169 testes)
- **Fase 5:** planejamento adaptativo orientado por evidência — `AdaptivePlanProposal`,
  `AdaptivePlanner` (IA opcional + fallback determinístico), `PlanValidator` determinístico,
  prioridade no scheduler (ordena tarefas elegíveis), replanejamento controlado com limites e
  histórico, memória operacional compacta, flag `PENTEST_AI_PLANNING`, XAI do planejador. (196 testes)
- **Fase 6:** execução isolada — `ExecutionBackend` (local/containerizado), `ContainerManager`
  (in-process + Docker endurecido), protocolo de worker + 3 operações allowlisted, `PolicyEngine`
  (autorização de backend/fallback), integração ao scheduler sem reordenar, eventos `worker_*`,
  recuperação de tarefas interrompidas, flag `PENTEST_CONTAINER_EXECUTION`. (229 testes)

### Fase 6 — arquivos
| Arquivo | Papel |
|---|---|
| `execution/worker_protocol.py` | `WorkerRequest`/`WorkerResponse` (JSON validado, limite de tamanho). |
| `execution/workers.py` | Operações allowlisted (normalização/análise/validação) + `run_operation`. |
| `execution/worker_entry.py` | Entrypoint do worker no container (`python -I -m …`, só stdin/stdout). |
| `execution/container_manager.py` | Ciclo de vida: `InProcessContainerManager` (sem isolamento real) + `DockerContainerManager` (endurecido). |
| `execution/policy.py` | `PolicyEngine`: decide backend, valida runtime/imagem, autoriza fallback. |
| `execution/executor.py` | `Local`/`Container`/`RoutingExecutionBackend` + adaptadores de operação. |
| `execution/config.py` | Flag `PENTEST_CONTAINER_EXECUTION` (disabled|enabled). |
| `orchestration/scheduler.py` | Parâmetro `backend` (ONDE executar; não muda ordem/seleção). |
| `orchestration/orchestrator.py` | Monta o backend por flag; emite `worker_backend_*`. |
| `persistence/checkpoint_store.py` | `plan_recovery(container_types=…)`: interrompidas em container → revisão manual. |
| `frontend/.../xai-panel.jsx` | Pill de execução isolada (workers: contagem/estado/duração). |

### Fase 6 — decisões
- **Separação de responsabilidades:** planejamento (AdaptivePlanner) ≠ autorização (PolicyEngine)
  ≠ agendamento (TaskScheduler) ≠ execução (ExecutionBackend); a IA não contorna isso.
- **Destino fixo:** imagem (allowlist explícita) e comando do worker são FIXOS; resposta/alvo/IA
  nunca definem imagem, volumes ou comando. Só operações allowlisted; sem shell/PoC/rede.
- **Isolamento (Docker):** não-root, filesystem read-only, `--network none`, `--cap-drop ALL`,
  `no-new-privileges`, limites de CPU/memória/pids, timeout, tmpfs; socket Docker nunca montado.
  Documentado que container não é fronteira absoluta — a defesa principal é a allowlist.
- **Sem fallback silencioso:** tarefas críticas que falham no worker não caem para local; opcionais
  só com autorização da política e evento registrado.
- **Elegibilidade restrita:** apenas `technology_normalization` (local, determinística) nesta fase;
  rede/aprovação permanecem locais. Infra validada sem aumentar verificações.
- **Interrupção = desconhecido:** tarefa em container interrompida em `running` vai para revisão
  manual (não se repete operação possivelmente não idempotente sem reconciliação).
- **Isolamento real:** validado só com Docker + `PENTEST_DOCKER_IT=1`; caso contrário o teste é
  pulado e registra-se que o isolamento real NÃO foi validado (apenas mocks).

### Fase 5 — arquivos
| Arquivo | Papel |
|---|---|
| `contracts/planning.py` | `AdaptivePlanProposal`, `PlanValidationResult` (dado, não comando). |
| `contracts/models.py` | `TaskDefinition.priority`/`optional` (aditivo; padrão preserva o legado). |
| `planning/campaign_memory.py` | Memória operacional compacta (inclui/omite evidência explicitamente). |
| `planning/adaptive_planner.py` | Propõe prioridades para tarefas opcionais; só IDs do catálogo. |
| `planning/providers.py` | Adaptadores OpenAI/Bedrock (reusam `ai.py`; esquema restrito à allowlist). |
| `planning/plan_validator.py` | Gate determinístico + `apply_priorities` (reconstrói o plano). |
| `planning/replanning_policy.py` | Gatilhos fechados, limites, proteção de ciclo, histórico. |
| `orchestration/scheduler.py` | Ordena elegíveis por prioridade; hook `replan` entre ondas; `planned/executed_order`. |
| `orchestration/orchestrator.py` | Monta planner→validador→política e aplica prioridades na execução real. |
| `frontend/.../xai-panel.jsx` | Bloco de planejamento adaptativo + pill de replanejamento. |

### Fase 5 — decisões
- **Prioridade ≠ permissão:** prioridade só reordena tarefas ELEGÍVEIS; dependências continuam
  sendo o gate e tarefa prioritária ainda exige sua autorização/aprovação.
- **Influência real:** o scheduler ordena por prioridade (critério de aceite: duas propostas →
  ordem de execução observa mudança nos testes).
- **IA nunca executa direto:** toda proposta passa pelo `PlanValidator`; IA só prioriza tarefas
  opcionais do catálogo — não cria tipos, comandos ou payloads; saída tratada como dado.
- **Orientado por evidência:** replanejamento só sob gatilhos explícitos, com limites de revisões/
  tarefas/orçamento e proteção contra ciclos; histórico preservado.
- **Fallback determinístico:** sem IA, com IA falhando, expirando ou malformada → plano base seguro.
- **Legado preservado:** `PENTEST_AI_PLANNING` desligado por padrão; equivalência legado↔V2 intacta.

### Fase 4 — arquivos
| Arquivo | Papel |
|---|---|
| `contracts/intelligence.py` | Contratos (TechnologyComponent, CveRecord, CorrelationResult, VulnerabilityHypothesis). |
| `intelligence/http_client.py` | `ControlledHttpClient` + `_assert_allowed` (só https e hosts oficiais). |
| `intelligence/cache.py` | `TTLCache` para respostas das bases públicas. |
| `intelligence/providers/{nvd,osv,cisa_kev}.py` | Normalizam cada base para `CveRecord`. |
| `intelligence/cve_research.py` | `CveResearchService` (cobertura, cache, isolamento de falha). |
| `intelligence/correlation.py` | Correlação por versão → estado + confiança categórica. |
| `intelligence/inventory.py` | `build_components` (nunca inventa tecnologia desconhecida). |
| `intelligence/hypothesis_registry.py` | Dedup por (componente, CVE), prioridade, histórico. |
| `orchestration/executors_intelligence.py` | 4 executores não-críticos no DAG. |
| `report.py` / `frontend/.../xai-panel.jsx` | Seção/bloco "vulnerabilidades conhecidas (hipóteses)". |

### Fase 4 — decisões
- **Destino fixo:** nomes de tecnologia/URL do alvo/respostas de IA **não** definem destino de
  requisição — `_assert_allowed` só aceita https + `{services.nvd.nist.gov, api.osv.dev, www.cisa.gov}`.
- **Passivo:** zero exploração/PoC; consultas vão a bases públicas, nunca ao alvo.
- **Hipóteses ≠ achados:** CVEs candidatas nunca viram falha confirmada; disclaimer no relatório e na UI.
- **Isolado:** executores não-críticos; falha de base pública não derruba a campanha.
- **Testes offline:** `fetch` injetável/stubs; nenhuma requisição externa na suíte.
- **Legado preservado:** desligado por padrão; só ativa com `PENTEST_CVE_INTELLIGENCE`.

### Fase 3 — arquivos
| Arquivo | Papel |
|---|---|
| `orchestration/event_store.py` | Trilha oficial de eventos (normaliza, dedup, pagina, sanitiza). |
| `orchestration/projection.py` | Mapa único tarefas→8 macrofases; multi-agente; fallback legado. |
| `web_server.py` | `observability` no snapshot, endpoint de eventos, `checkpoint_store` no worker. |
| `frontend/.../ai-agent-pipeline.jsx` | Consome estados reais; múltiplos cartões ativos; cartões clicáveis. |
| `frontend/.../xai-panel.jsx` | Painel contextual + XAI (decisão IA/determinística/operador; sem inventar). |
| `frontend/src/styles.css` | Estilos dos estados novos + painel XAI (respeita movimento reduzido). |

### Fase 3 — decisões
- Projeção **derivada de eventos** (não da última mensagem); suporta N agentes ativos.
- Macrofase 08 (Monitoramento) segue o estado da campanha; demais seguem os estados das tarefas.
- Frontend: live usa `observability` (v2); histórico/legado cai no fallback por `phase` — design preservado.
- XAI usa só dados reais (stage plans, eventos `decision` com `source`, estados de tarefa).

## Arquivos importantes (Fase 2)
| Arquivo | Papel |
|---|---|
| `orchestration/state_machine.py` | Estados/transições de tarefa e campanha. |
| `orchestration/task_registry.py` | Catálogo de executores autorizados. |
| `orchestration/executors.py` | Adaptadores dos agentes (sem reescrever detectores). |
| `orchestration/scheduler.py` | DAG, ondas topológicas, concorrência, falhas. |
| `orchestration/context.py` | ExecutionContext + blackboard. |
| `orchestration/legacy_plan.py` | `LegacyPlanBuilder` (DAG equivalente ao `run_scan`). |
| `orchestration/orchestrator.py` | `OrchestratorV2` (coordenação). |
| `orchestration/events.py` | Eventos estruturados. |
| `persistence/checkpoint_store.py` | Checkpoints atômicos + recuperação conservadora. |
| `pipeline.py` | Extraído `build_summary`/`finalize_result` (fonte única legado+V2). |

## Decisões arquiteturais
1. **Equivalência via fonte única:** `finalize_result`/`build_summary` em `pipeline.py` são
   usados pelo legado e pelo V2 → `ruleset_hash`/`summary` idênticos.
2. **V2 não é fachada:** executa tarefas individuais pelo scheduler; `run_scan` não é chamado
   (teste `test_v2_is_not_a_run_scan_facade`).
3. **Vocabulário de status:** `ScanResult.status` mantém valores legados
   (completed/inconclusive/stopped/failed); a máquina de campanha usa …/cancelled.
   Parada por operador/orçamento → status "stopped" / estado interno "cancelled".
4. **Concorrência:** scheduler suporta N workers; o plano legado roda com `max_concurrency=1`
   por determinismo/segurança de rede. Paralelismo real testado com tarefas locais independentes.
5. **Falhas:** tarefas críticas → `SchedulerFatal` (campanha falha); análises locais falham
   de forma isolada (campanha continua).
6. **Aprovações:** continuam dentro do `SurfaceTestAgent` (comportamento legado preservado);
   o estado `waiting_approval` existe na máquina para uso futuro.
7. **Contrato:** adicionado `cancelled` a `TASK_STATES` (aditivo).

## Testes executados / resultados
- Suíte completa: **229 testes, OK** (+1 pulado: isolamento real exige Docker). 33 novos na Fase 6:
  protocolo/worker, limites, manager, política, backends/scheduler, checkpoints e orquestração V2.
  Build do frontend OK.
- Equivalência legado↔V2 confirmada: status, selected_checks, ruleset_hash, findings
  (incl. severidade/confiança), by_severity/by_status, recommendations.
- Sem requisições a alvos externos (FakeTransport/mocks em toda a suíte).

## Pendências registradas ao fim da Fase 2 (histórico)
- Retomada automática a partir de checkpoint: implementada apenas a **restauração para inspeção**
  (`plan_recovery`); reexecução automática não é feita para tarefas de rede interrompidas.
- Planejamento adaptativo por IA: resolvido na Fase 5.
- Wiring de `checkpoint_store` no worker da API: resolvido e validado na Fase 6.5.

## Fase 6.5 — implementação inicial (registro histórico)

Diagnóstico adicional: causa do erro Docker comprovada pelo audit do kernel:
transição AppArmor de snap.docker.dockerd para docker-default recusada sob
no-new-privileges. Reproduz com Python oficial e com Na Mira; antes do código
Python. Detalhes e procedimento em [docker-diagnosis.md](docker-diagnosis.md).
Correção depende do runtime/perfil do host; controles do worker preservados.

- LaboratoryManager reutiliza ContainerManager e PolicyEngine, com contratos de
  validação, associação à campanha/hipótese e allowlist de laboratório/operação.
- Laboratórios iniciais: inventory (normalização) e evidence (estrutura).
  Não confirmam vulnerabilidades nem promovem hipóteses a findings.
- Tarefa laboratory_validation registrada no V2; ativação explícita com
  PENTEST_LABORATORY=enabled, junto de CVE Intelligence. Limite de três
  hipóteses por campanha. Executor utiliza Docker sem fallback simulado.
- Eventos preservam IDs de laboratório, hipótese e worker no Event Store.
  Resultados ficam em observations; frontend mostra estado e isolamento.
- Recuperação de tarefa de laboratório em running exige revisão manual.
- Dockerfile.worker cria namira/worker:local. Timeout do cliente Docker agora
  tenta remover somente o container nomeado desta execução.

Validação: 235 testes executados com PENTEST_DOCKER_IT=1: 234 passaram,
1 erro no teste Docker real, nenhum pulado. Build frontend aprovado.
Docker 29.8.0 acessível; imagem construída. Execução endurecida falhou com
`exec /usr/local/bin/python: operation not permitted`. Isolamento NÃO validado.
Não houve redução de controles nem execução de varreduras externas.

Pendências de aceite: laboratório de correlação CVE; decisões estruturadas de
hipótese sustentada/contradita; integridade/proveniência além da validação de
estrutura; cancelamento durante execução; confirmação de cleanup e eventos
de lifecycle; checkpoint durável durante validação; testes de integração e
verificação real de todos os controles Docker. O teste existente de Docker
verifica somente a operação do worker, não todos os controles de isolamento.

## Próxima atividade registrada naquele ponto
Concluir os critérios pendentes da Fase 6.5 antes da Fase 7; concluídos na auditoria final abaixo.

### Consolidação incremental

- Projeção backend execution_history separa planejamento, execução e validação;
  snapshot e histórico de campanha retornam executions/hypotheses.
- execution_events são persistidos junto ao resultado e conservam vínculos de
  validação. Relatórios antigos sem eventos estruturados não inventam execuções.
- Frontend: visão Execuções e hipóteses com detalhes expansíveis, referências e
  limitações, preservando a pipeline original. Executor desconhecido é explícito.
- Scheduler registra planejamento e checkpoint antes/depois de ondas; estados
  running de laboratório continuam exigindo revisão manual na recuperação.
- Docker manager observa cancelamento durante communicate, encerra o cliente
  e solicita remoção do container específico. Teste mock verifica esse caminho;
  comportamento real continua bloqueado pelo host Snap/AppArmor.
- Operações allowlisted adicionais: correlação local de versões (identidade exata
  e versões numéricas), integridade SHA-256 de JSON canônico e comparação local.
  Resultados supported/contradicted referem-se aos dados locais, nunca ao alvo.
- Documentação oficial Canonical confirma a limitação Snap. Migração do daemon
  não aplicada: afeta workloads existentes e exige planejamento administrativo.

O executor de laboratório agora usa correlação local quando encontra componente
e aviso correspondentes à hipótese; nos demais casos utiliza inventory.
A tela de testes salvos também apresenta execuções/hipóteses persistidas.

Validação: suíte com Docker habilitado, 242 testes: 241 aprovados e um erro
no worker real devido ao AppArmor/Snap, nenhum pulado. Build frontend aprovado.

As pendências deste ponto intermediário foram reavaliadas na consolidação abaixo.

### Consolidação — validação final (13/11/2026)

**Implementação:**

1. `execution_history` projeta tarefas e tentativas de worker a partir do Event
   Store, com IDs da campanha/tarefa/validação/hipótese, agente, operação,
   executor, início/fim, duração, estado operacional, validação, evidências,
   motivo de seleção e limitações. Tentativas de worker e eventual fallback
   local mantêm registros distintos. Eventos terminais não apagam referências.
2. Inventário passa suas referências reais às tecnologias e hipóteses.
   `hypothesis_registered` e `evidence_registered` disponibilizam esses dados
   durante a campanha. O catálogo público exibe somente metadados; não expõe
   corpos HTTP, cabeçalhos, comandos ou segredos. Correlação de CVEs e resultados
   `supported`/`contradicted` de laboratório nunca promovem findings.
3. `ScanResult.execution_events` conserva o histórico também em execuções V2
   fora do console. No console, `result.json` é gravado por substituição atômica.
   `/api/status` e `/api/history/{run_id}` retornam `executions`, `hypotheses`
   e `evidence_catalog`. Reiniciar o console e consultar campanhas salvas preserva
   os registros. Relatórios legacy sem eventos não ganham execuções fictícias.
4. Checkpoints guardam eventos e resultados antes/depois das ondas e durante
   validações. Falhas de controle preservam o último report em vez de sobrescrever
   o checkpoint com estados vazios. Uma validação interrompida em `running`
   exige revisão manual via `plan_recovery`; não há retomada automática do worker.
   Cancelamento é observado durante a espera pelo Docker, encerra o cliente e
   solicita remoção somente do container nomeado desta tentativa. Falha ou
   timeout da limpeza é registrada como não confirmada, nunca como sucesso.
5. `execution-history.jsx`, `main.jsx`, `styles.css` e `xai-panel.jsx` oferecem
   abas de Execuções/Hipóteses, filtros por estado, detalhes de executor/duração,
   evidências expansíveis e vínculo com CVEs, usando a paleta branca/azul.
   O XAI aponta para esses detalhes sem duplicar a lista na pipeline; os oito
   cartões, conexões e animações permanecem. Simulação é rotulada sem isolamento.

**Laboratórios disponíveis:**

| Laboratório | Operação registrada | Limite da conclusão |
|---|---|---|
| inventory | normalize_technology_inventory | Normalização de dados coletados; validação inconclusiva por si só. |
| evidence | validate_result_structure | Estrutura/referências; não autentica origem. |
| integrity | verify_integrity | SHA-256 de JSON canônico contra hash fornecido; não autentica origem. |
| comparison | compare_local_results | Igualdade/contradição entre resultados locais fornecidos. |
| cve | correlate_local_version | Produto/ecossistema exatos e versão numérica precisa contra intervalo registrado; não comprova aplicabilidade no alvo. |

O DAG opt-in executa CVE quando existem componente e aviso correspondentes;
caso contrário, normaliza inventário. Mantém o limite explícito de três hipóteses
por campanha e contabiliza as demais como não verificadas. Estrutura, integridade
e comparação estão disponíveis ao LaboratoryManager com entradas controladas,
cobertas por fixtures; não são disparadas automaticamente com hashes ou resultados
“esperados” fabricados. Hipótese sem evidência não inicia worker: execução não
realizada, validação inconclusiva. Runtime indisponível, resposta de outra tarefa,
timeout ou cancelamento não produzem evidência de sustentação.

Ativação da tarefa no V2: `PENTEST_ORCHESTRATOR=v2`,
`PENTEST_CVE_INTELLIGENCE=1`, `PENTEST_LABORATORY=enabled`.
O laboratório usa Docker sem fallback simulado. Testes injetam manager local
explicitamente; isso não constitui prova de isolamento.

**Validação anterior à troca do runtime:**

- Suíte completa em `backend/`, com `PENTEST_DOCKER_IT=1`: **251 testes,
  250 aprovados, 1 erro Docker, nenhum pulado**. Legacy/V2, AdaptivePlanner,
  PolicyEngine, Event Store, checkpoints e APIs incluídos. O erro remanescente é
  `exec /usr/local/bin/python: operation not permitted`, código 255.
- `test_phase65_acceptance.py`: cadeia hipótese → evidência → execução, falha de
  runtime, identidade de resposta, cancelamento durante execução, falha de cleanup
  e checkpoint intermediário, sem consultas externas. Testes de API verificam
  hipóteses ao vivo e recuperação de históricos após reiniciar o console.
- `npm run build` em `frontend/`: aprovado.
- `node tools/e2e-web/run_phase65.mjs`: **10 verificações aprovadas** no Chrome
  headless com sandbox padrão, API fixture em loopback e requisições externas
  bloqueadas. Estados, filtros, execução concluída/validação inconclusiva,
  evidências, hipótese sem verificação, reload, campanha salva, layout móvel,
  oito cartões e ausência de exceções JS. Capturas inspecionadas visualmente.
- Imagem `namira/worker:local` reconstruída com o código atual, sem rede no build.
  O teste real foi repetido com todas as restrições e falhou antes do Python.
  Nenhum worker `namira-worker-*` ficou listado depois da tentativa. Isso não
  prova cleanup de um worker que tenha iniciado e esteja em execução.

**Pendência externa identificada naquela validação:** disponibilizar runtime compatível com AppArmor e
`no-new-privileges` e repetir validação de execução/cancelamento/isolamento reais.
Só existe contexto Docker `default` neste host. A proposta de menor impacto é
um host/VM separado com Engine oficial, selecionado por contexto apenas para o
processo de teste. Migração do daemon Snap atual exige aprovação administrativa,
backup e janela de manutenção pelos quatro containers ativos. Ver
[diagnóstico e procedimento](docker-diagnosis.md). Nenhum mecanismo foi desativado
e nenhum container existente foi interrompido.

**Próxima fase:** 7 — Validação Independente e Autocorreção, não iniciada.

### Bloqueio Docker resolvido — 13/11/2026

O operador autorizou trocar a instalação e, depois, apagar containers, volumes
e demais dados antigos por serem usados apenas em estudos. Essa autorização
substituiu a restrição anterior de preservar os quatro serviços ativos.
Foi executado `snap remove docker --purge`; os 39 containers, 33 volumes e caches
da instalação Snap foram removidos. Somente as imagens do worker e do Python
usadas na validação foram exportadas e carregadas na instalação nova.

Instalados pacotes oficiais assinados para Ubuntu 26.04/amd64: Docker CE/CLI
29.8.0, containerd.io 2.4.2, Buildx 0.39.0 e Compose 5.7.1. Assinatura InRelease
e SHA-256 dos pacotes conferidos; repositório oficial configurado em
`/etc/apt/sources.list.d/docker.sources`. Engine usa `/var/lib/docker`, serviço
systemd habilitado. Nenhuma proteção do worker foi reduzida.

- Suíte completa com `PENTEST_DOCKER_IT=1`: **251 testes aprovados, nenhum erro,
  nenhuma falha e nenhum pulado**, incluindo legacy/V2 e o worker Docker real.
- `tools/docker/verify_worker.py`: UID/GID 65534, `NoNewPrivs=1`, seccomp em modo
  filtro, capabilities efetivas zeradas, `docker-default (enforce)`, raiz somente
  leitura, `/tmp` gravável e sem execução, somente interface loopback, sem socket
  Docker, cgroups com 256 MiB/128 PIDs/1 CPU. Cancelamento testado após o Python
  imprimir seu marcador de início; remoção do container confirmada.
- Build frontend e dez verificações no navegador aprovados na consolidação;
  nenhuma alteração de interface ocorreu durante a troca do runtime.

Não há pendência de autenticação ou compatibilidade Docker para os testes desta
fase. A verificação dos controles não equivale a provar contenção contra todas
as vulnerabilidades de kernel. Fase 7 permanece não iniciada.

### Auditoria final de ponta a ponta — 13/11/2026

**Status: concluída.** Foram reutilizados TaskRegistry, TaskScheduler,
PolicyEngine, LaboratoryManager, DockerContainerManager, Event Store,
CheckpointStore e a SPA existente. Não foi criada uma arquitetura paralela.

**Lacunas corrigidas:**

- LaboratoryManager agora registra a decisão de autorização de `PolicyEngine.decide`
  sobre a tarefa antes do despacho; tarefa que exige aprovação não inicia worker.
  A validação de runtime/imagem e a ausência de fallback continuam obrigatórias.
- Cada tentativa possui `execution_id` único, também conferido no protocolo de
  resposta. Resultado, eventos e evidências conservam campanha, hipótese, tarefa,
  execução, worker e operação. Repetir uma solicitação não mistura tentativas.
- Verificação concluída produz evidência própria, separada das referências de
  entrada, com versão, aviso, fonte, critérios de intervalo e conclusão observada.
  Metadados públicos recebem SHA-256 do JSON canônico (sem o campo `sha256`, com
  chaves ordenadas, UTF-8 e separadores `,`/`:`). O hash verifica integridade do
  registro, não autenticidade da origem nem exploração. Entradas arbitrárias não
  são copiadas para esse catálogo.
- Falha, cancelamento, timeout e verificação não realizada recebem validação
  `not_evaluated`, sem evidência de sustentação. `inconclusive` identifica uma
  verificação concluída sem dados suficientes. `worker_responded` diferencia
  resposta estruturada de ausência de resposta; sucesso operacional continua
  distinto da conclusão local sobre a hipótese.
- API de histórico ignora o diretório interno `checkpoints`, sem tratá-lo como
  campanha corrompida. Relatórios existentes e compatibilidade legacy preservados.

**Demonstração real:** `node tools/e2e-web/run_phase65.mjs --real-docker` cria cinco
campanhas em diretório temporário próprio. Apenas transporte do alvo e pesquisa
de avisos são substituídos por fixtures. O DAG registrado, autorização, scheduler,
containers, protocolo, eventos, checkpoints, persistência, servidor HTTP e React
são reais. O endpoint de histórico é servido pelo console de produção. A fixture
`fixture.example` é um identificador; nenhuma requisição é feita a esse alvo.

| Cenário | Estado operacional | Validação | Evidência de saída |
|---|---|---|---|
| Angular 14.0.0, aviso fictício afetando versões de 13.0.0 até antes de 15.0.0 | completed | supported | Critérios, fonte, IDs e hash |
| Angular 14.0.0, aviso corrigido em 14.0.0 | completed | contradicted | Critérios, fonte, IDs e hash |
| Tecnologia reconhecida, versão desconhecida | completed | inconclusive | Dados insuficientes registrados |
| Aviso local malformado; worker devolve falha estruturada | failed | not_evaluated | Nenhuma conclusão produzida |
| Hipótese com laboratório desativado | Sem verificação vinculada | Não avaliada | Nenhuma execução inventada |

O aviso `CVE-2099-6501` é fictício. Nenhum cenário promove CVE a achado confirmado.
O teste verifica autorização anterior ao despacho, identidade da resposta,
consulta real pela API e os dados exibidos em Execuções/Hipóteses. Após reiniciar
o processo Python, os cinco payloads do histórico permanecem idênticos. Recarregar
o navegador mantém a mesma execução. Checkpoints finais foram carregados com
verificação de integridade e confrontados com os registros da API. Recuperação
de laboratório interrompido continua conservadora: revisão manual, sem repetição
automática do worker.

**Frontend/XAI:** menu **Execuções e hipóteses**, com abas separadas; também em
**Relatórios → campanha salva → Execuções e hipóteses desta campanha**. Detalhes
mostram motivo persistido, autorização, agente/tarefa, worker, estado, duração,
resultado, hipótese, evidências consultadas/produzidas e limitações. Não se inventa
justificativa para registros sem motivo. Oito cartões, conexões e animações da
pipeline preservados. Teste visual automatizado em Chrome com sandbox padrão,
layout móvel sem overflow e nenhuma exceção JavaScript; captura inspecionada.

**Validação final:**

- `PENTEST_DOCKER_IT=1 ../.venv/bin/python -m unittest discover -s tests -q`,
  em `backend/`: **255 aprovados, 0 falhas, 0 erros, 0 pulados**. Inclui legacy/V2,
  hipótese sem verificação, planejamento sem execução, inconclusão, contradição,
  falha operacional, cancelamento, timeout, histórico e recuperação conservadora.
  Novas regressões cobrem recusa da política, timeout sem conclusão, identidade
  das tentativas/integridade da evidência e diretório interno do histórico.
- `npm run build`, em `frontend/`: aprovado.
- Aceite do navegador: **11 verificações com Docker/API reais + 10 com API
  fixture**, aprovadas. A segunda modalidade testa estados de UI; não é usada
  como prova de execução Docker.
- Imagem reconstruída com `--network=none`. `tools/docker/verify_worker.py`
  confirma UID/GID 65534, `NoNewPrivs=1`, seccomp=2, CapEff=0,
  `docker-default (enforce)`, raiz read-only, `/tmp` noexec, somente loopback,
  sem socket Docker, 256 MiB, 128 PIDs e 1 CPU. Cancelamento após início do
  Python e remoção confirmados. Nenhum `namira-worker-*` remanescente.

Evidência compacta com IDs reais, resultados e hashes:
[phase65-final-audit.json](phase65-final-audit.json).
Comandos reproduzíveis e artefatos: [harness E2E](../../tools/e2e-web/README.md).

**Pendências de aceite da Fase 6.5: nenhuma.** Permanecem os limites deliberados:
correlação local não comprova exploração/aplicabilidade no alvo; até três
hipóteses verificadas por campanha; retomada automática de worker interrompido
não suportada. Nenhuma mudança administrativa no Docker, redução de isolamento
ou exclusão de dados anteriores foi realizada nesta auditoria. **Fase 7 não iniciada.**

## Fase 7 — Validação Independente e Autocorreção (13/11/2026)

**Status: concluída.** Baseline reconfirmado antes das alterações: 255 testes,
sem falhas/pulados, incluindo Docker real. A [auditoria dos contratos](phase7-contract-audit.md)
identificou as lacunas; nenhum componente funcional de execução foi substituído.

### Implementado

1. **EvidenceValidator** separa integridade SHA-256 de suficiência. Confere
   existência, campanha, sujeito, execução, worker, autorização, origem, tempo,
   duplicação e correspondência dos critérios com a observação. Hash correto
   com campanha/critério errado continua sem sustentação. Ausência de evidência
   não é contradição. Metadados históricos sem hash são contexto explicitamente
   limitado. Reavaliação de versões reutiliza o comparador determinístico local.
2. **FindingClassifier e DecisionValidator** classificam suspected/potential/
   confirmed/rejected/inconclusive. Mapeamento legado explícito, proposta validada,
   referências conferidas, promoção indevida recusada. CVE local nunca vira
   finding confirmado. Confirmação de finding exige categoria suportada e
   metadados diretos da resposta previamente coletada, sem nova requisição.
3. **ReflectionAgent** propõe JSON estrito, com resumo público da justificativa,
   referências e ação limitada ao catálogo. Reutiliza os helpers OpenAI Responses/
   Bedrock Converse e suas configurações/timeouts. Falha, resposta inválida,
   evidência fabricada ou tarefa desconhecida causam fallback determinístico.
   Não se persiste raciocínio interno bruto nem se envia conteúdo HTTP bruto,
   credenciais ou cookies ao modelo. Até três chamadas ao provider por execução
   da tarefa; demais análises seguem deterministicamente.
4. **Ciclo de revisão integrado ao V2**: tarefa registrada `independent_validation`
   no mesmo TaskScheduler, após as dependências terminarem. `dependency_policy=terminal`
   é permitida somente nessa tarefa: falhas opcionais não impedem revisão;
   cancelamento global e falhas críticas continuam interrompendo a campanha.
   Eventos/checkpoints preservam proposta, decisão, versão, estado anterior,
   evidências e fingerprint. Mesmos dados não disparam outra reflexão; até três
   revisões por sujeito e 64 registros por campanha. Originais não são alterados.
5. **Projeções, relatórios e frontend**: `conclusions` aditivo no JSON/API, histórico
   de revisões e resumo Markdown com grupos de confirmação, potencialidade,
   rejeição e inconclusão. As abas existentes mostram estados inicial/atual,
   evidências favoráveis/contrárias, reflexão e decisão. Execução permite navegar
   para a hipótese. XAI mostra revisões persistidas e a projeção da pipeline é
   restaurada dos eventos após reinício. Oito cartões/conexões/animações preservados.

### Replanejamento e limites de autoridade

Recomendações referenciam somente `laboratory_validation` ou
`technology_normalization` presentes no plano/TaskRegistry. `PlanValidator`,
`PolicyEngine`, `ReplanningPolicy` compartilhada com o AdaptivePlanner, escopo,
orçamento, aprovações, dependências e parada são avaliados. Tarefa já finalizada
é recusada para a campanha corrente. Não há adição dinâmica ao DAG nem segunda
implementação de scheduler: propostas elegíveis ficam **deferred**, as demais
**rejected_for_current_campaign**, sempre com `executed=false`. Nenhuma verificação
externa ou repetição automática é disparada pela reflexão.

### Demonstrações verificadas

- **Contradição:** fixture inicia deliberadamente uma correlação fraca como
  `potentially_affected` (projeção `potential`). O aviso fictício CVE-2099-6501
  registra correção em 14.0.0; o componente é 14.0.0. O worker Docker real retorna
  `contradicted`, a evidência recebe hash, o EvidenceValidator confere vínculos e
  critérios, a resposta controlada do ReflectionAgent propõe `rejected`, e o
  DecisionValidator aprova a revisão **potential → rejected**. A correlação
  original permanece intacta no relatório.
- **Proposta indevida:** versão desconhecida produz verificação Docker concluída,
  porém `inconclusive`. A resposta controlada de IA sugere `confirmed` com referência
  existente. O DecisionValidator rejeita por insuficiência; estado atual continua
  `inconclusive`. JSON válido, hash e sucesso do worker não autorizam confirmação.
- Também exercitados: sustentação local (somente `potential`), falha operacional
  sem conclusão de segurança e hipótese sem verificação. Respostas HTTP/avisos
  são fixtures locais. O Docker, protocolo, scheduler, políticas, persistência,
  servidor HTTP e React são reais. Provider remoto não foi chamado nos testes.

`node tools/e2e-web/run_phase65.mjs --phase7` verifica os cinco cenários, navegação
execução → hipótese, decisões/evidências no React, igualdade dos payloads após
reinício, recarga, XAI, layout móvel e oito cartões. Capturas foram inspecionadas.
Os checkpoints finais também conservam revisões e resultados do mesmo worker.
Evidências compactas: [phase7-final-audit.json](phase7-final-audit.json).

### Ativação e compatibilidade

- `PENTEST_ORCHESTRATOR=v2` e `PENTEST_INDEPENDENT_VALIDATION=enabled` ativam a
  revisão independente. Sem a flag, o V2 mantém o fluxo anterior; legacy ignora
  a opção sem receber parâmetros incompatíveis.
- Para hipóteses/laboratório, continuam necessárias as opções já existentes
  `PENTEST_CVE_INTELLIGENCE=1` e `PENTEST_LABORATORY=enabled`.
- A reflexão é determinística por padrão. Opcionalmente,
  `PENTEST_REFLECTION_PROVIDER=openai|bedrock` reutiliza credenciais e modelo já
  configurados. Não foi alterado nenhum segredo ou configuração local do usuário.
- Relatórios antigos não recebem revisões inventadas. Dados originais, findings,
  hipóteses, controles Docker e limites do alvo foram preservados.

### Arquivos principais

| Arquivo/diretório | Papel |
|---|---|
| `contracts/validation.py` | Resultados de evidência, reflexão e revisão; JSON estável após reload. |
| `validation/` | Validadores, classificador, ReflectionAgent/providers, ciclo, projeção e gates de revalidação. |
| `orchestration/executors_validation.py` | Adapta os dados coletados à tarefa registrada, sem novas consultas. |
| `orchestration/{legacy_plan,scheduler,orchestrator,event_store,projection}.py` | DAG, dependências terminais restritas, eventos e checkpoints. |
| `models.py`, `report.py`, `web_server.py` | Projeção aditiva, relatórios JSON/Markdown e API persistente. |
| `frontend/src/components/ui/conclusion-review.jsx` | Histórico de decisões reutilizado nas abas, achados e XAI. |
| `tests/test_independent_validation.py`, `tests/test_phase7_integration.py` | 49 testes novos, incluindo Docker real. |
| `tools/e2e-web/run_phase65.mjs --phase7` | Aceite integrado reutilizando o harness anterior. |

### Validação final

- Em `backend/`: `PENTEST_DOCKER_IT=1 ../.venv/bin/python -m unittest discover -s tests -q`
  → **304 aprovados, 0 falhas, 0 erros, 0 pulados**.
- Em `frontend/`: `npm run build` → aprovado.
- Navegador: **18 verificações da Fase 7 + 11 Docker/API da Fase 6.5 + 10 de UI**,
  todas aprovadas, sem exceções JavaScript.
- Imagem atual reconstruída com `--network=none`; worker real executado tanto
  pela suíte quanto pelo E2E. Nenhum container de worker remanescente. Runtime,
  AppArmor, seccomp, usuário não root, filesystem read-only, rede desabilitada,
  capabilities e ausência de socket mantidos; diagnóstico administrativo não foi
  repetido e Docker não foi reinstalado.

**Limitações deliberadas:** confirmação independente de findings está restrita
a critérios de cabeçalhos HTTP para os quais há metadados verificáveis. Categorias
sem prova estruturada suficiente ficam inconclusivas; textos legados não viram
prova por rehash. Hipóteses de CVE continuam sendo correlações locais. Não há
reexecução automática nem autenticação criptográfica da origem dos advisories.
Providers foram testados com respostas controladas/mocks, sem consumo de API real.

Referência usada para o contrato OpenAI: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
que exige também validar regras de negócio fora do schema.

**Pendências de aceite: nenhuma. Próxima fase: 8 — MITRE ATT&CK e integração final,
não iniciada.**

## Correção posterior à Fase 7 — clareza e identidade de produto (13/11/2026)

O relatório apresentado pelo usuário registrava 11 requisições/respostas HTTP,
20 hipóteses e três comparações locais concluídas. O worker é Python em Docker;
não há executor de ferramentas no Kali nem reprodução de vulnerabilidade nesse
registro. A indicação genérica de operação concluída confundia processamento
interno, comparação de metadados e testes no alvo.

### Comportamento corrigido

- A API e os novos JSON/Markdown incluem um resumo de verificações. A interface
  separa respostas HTTP, comparações locais e ausência de execução registrada no
  Kali. Etapas internas ficam recolhidas; resultado e explicação aparecem antes
  de IDs, hashes, autorização e histórico técnico, acessíveis por expansão.
- O relatório histórico mostra a explicação derivada dos critérios originais,
  sem reescrever evidência, hash, revisão ou veredito persistido. Simulação,
  tentativa sem resposta e tarefa apenas planejada não entram no total de
  comparações concluídas reais.
- Causa da correlação incorreta: o comparador aceitava nome por substring e,
  sem correspondência, usava intervalos de outros produtos. Angular 22.2.2 não
  pode ser avaliado contra intervalos de Cloud Foundry Elastic Runtime.
- Agora produto e ecossistema devem corresponder exatamente; avisos com vários
  produtos usam apenas os intervalos aplicáveis ao pacote identificado. Falta de
  identidade resulta em inconclusivo, nunca em confirmação ou descarte por versão.
- A seleção registra `laboratory_hypothesis_skipped` com o motivo e segue para
  hipóteses compatíveis. Os três lugares continuam limitando tentativas locais;
  resultados irrelevantes de busca não os consomem. Todas as hipóteses continuam
  no histórico. Não há fallback de inventário apresentado como teste de CVE.
- A versão das regras do fingerprint independente passou a 2; texto de
  apresentação é excluído do fingerprint para não criar revisão por mudança de UI.

### Verificação

- 315 testes Python aprovados com `PENTEST_DOCKER_IT=1`, incluindo 11 regressões
  de identidade, seleção, contagens e preservação de evidências.
- Build React aprovado; navegador: 18 verificações Fase 7/Docker/API, 11 Fase
  6.5/Docker/API, 10 de UI e sete sobre o relatório salvo, com rede externa
  bloqueada no navegador. Fixtures substituem o transporte do alvo nos testes.
- Worker reconstruído com `--network=none`. Rede isolada, usuário não root,
  filesystem read-only, seccomp, AppArmor, limites, capabilities removidas e
  ausência do socket preservados. Nenhum alvo externo foi consultado.

**Limite mantido:** Kali em Docker é o ambiente pretendido pelo usuário para
futuros testes com ferramentas; essa integração não existe na implementação
atual. Classificação/revisão de evidências não é execução de ferramenta. A Fase 8
não foi iniciada por esta correção.
