# Auditoria da orquestração e demonstração auditável — 13/11/2026

## Estado confirmado e resultado

O repositório já continha as Fases 1–7, contextualização MITRE e a PoC local da Fase 8. Havia alterações locais extensas, preservadas. O baseline medido antes desta correção foi **333 testes aprovados, zero pulados**, com `PENTEST_DOCKER_IT=1`. O baseline antigo de 315 não representava mais a árvore atual.

Após a correção: **348 testes aprovados, zero falhas e zero pulados**, Docker real habilitado; build React aprovado; **15 verificações da demonstração no navegador e 18 da Fase 7** aprovadas. Não houve avanço para execução ofensiva, Kali ou exploração de técnicas MITRE.

Campanha final: **`20261113T085045Z-61c83415`**. Estado operacional `completed`; completude `partial`. [Manifesto com execuções, hipóteses, revisões e hashes](auditable-demo-manifest.json). [Relatório gerado](auditable-demo-report.md).

## Evidência do incidente

Campanhas preservadas:

- `backend/reports/20261113T081629Z-c76db27a/result.json`
- `backend/reports/20261113T080455Z-b19d4f0c/result.json`
- `backend/reports/checkpoints/20261113T081629Z-c76db27a/checkpoint.json` (integridade verificada pelo CheckpointStore).

Na primeira campanha, `cve_research` registrou cobertura `partial`: OSV e CISA responderam; NVD falhou com `Falha de rede: TimeoutError`. O checkpoint registrou **zero avisos**. Foram consumidas **11 de 60 requisições do alvo**, não 11 de 11. O limite do laboratório era três verificações, mas nenhuma chegou a ser selecionada; não foi esgotamento desse orçamento.

O inventário identificou apenas `tech:@angular/core`, Angular 22.2.2, npm, versão exata. Entretanto, `_register_framework_advisories` registrou `GHSA-ffj9-42qx-f38h`, referente a **@angular/upgrade não identificado**, como `potentially_affected`. O helper criava um `CveRecord` sem `affected` e não o colocava em `cve_correlations`. O laboratório não encontrava os critérios e emitia `laboratory_hypothesis_skipped`, motivo `identity_missing`.

Portanto, **não executar essa comparação era correto**: não havia evidência de que o pacote afetado estivesse instalado. O defeito estava no registro paralelo de uma hipótese potencial sem critérios/identidade e na comunicação da incompletude. Forçar sua execução teria produzido uma comparação enganosa entre produtos diferentes.

### Decisões das tarefas ignoradas: doze verificações

| Verificação | Correlação de CVEs | Validação em laboratório |
|---|---|---|
| 1. Catálogo | `CveCorrelationExecutor`, registrado em `build_registry()` | `LaboratoryExecutor`, registrado em `build_registry()` |
| 2. Habilitada | Presente no plano persistido; CVE Intelligence habilitada nessa execução | Presente no plano; laboratório habilitado nessa execução |
| 3. Obrigatória/opcional | `optional=true`, não crítica | `optional=true`, não crítica |
| 4. Dependências | `cve_research` | `hypothesis_registration` |
| 5. Dependências executadas | Pesquisa terminou `inconclusive`; a política de dependência admite continuar com dados parciais | Registro terminou `completed`, uma hipótese |
| 6. Entradas suficientes | Não: `record_count=0` | Não: sem entrada correspondente em `cve_correlations`; pacote do aviso não identificado |
| 7. Orçamento | Não bloqueada por orçamento; correlação é local | Zero das três verificações usadas; limite não causou o skip |
| 8. Planner | Incluída no plano determinístico; sem remoção por seleção adaptativa | Incluída no plano determinístico; sem remoção por seleção adaptativa |
| 9. Política | Nenhuma negativa registrada | Pré-seleção rejeitou os dados antes de chamar PolicyEngine/worker; não confundir com autorização negada |
| 10. Scheduler | Despachou o executor; foi o executor que retornou `skipped` | Despachou o executor; foi o executor que retornou `skipped` |
| 11. Registro | Checkpoint: `no_records_to_correlate`; evento terminal perdia o código | Checkpoint: `no_eligible_hypotheses`; evento por hipótese: `identity_missing` |
| 12. Frontend anterior | Exibia `skipped` sem motivo causal | Exibia nome técnico/skip; macrofase permanecia `completed` |

As revisões de IA registraram resultados próprios (cinco prioridades e sete recomendações). Isso não substituiu pesquisa, correlação ou laboratório. Não há evidência de que a IA tenha selecionado deliberadamente a omissão dessas tarefas.

## Correções aplicadas

- `orchestration/executors_intelligence.py`: avisos do catálogo entram no mesmo conjunto de registros consumido pela correlação. `frameworks.py` preserva produto, ecossistema e intervalos. A identidade é verificada pelo `CveCorrelationEngine`; não se usa a versão de @angular/core como prova da presença de @angular/upgrade. Registro de hipóteses consome apenas correlações estruturadas.
- `intelligence/cve_research.py`: cache TTL vazio fornecido pelo chamador é preservado; listas vazias continuam cacheáveis e falhas não são cacheadas. Hits válidos são registrados no resultado; serviço sem providers não informa cobertura completa. O cache é em memória por instância, não uma base persistente entre reinícios.
- `orchestration/scheduler.py`: estado passa a `running` antes do despacho; resultados precisam ser terminais, identificados com a tarefa correta e conter outputs estruturados. Dependências falhadas registram `dependency_failed` e `blocked_by`. Não tornamos tarefas opcionais obrigatórias e não bloqueamos correlação parcial só porque uma fonte falhou.
- Eventos terminais preservam `reason_code`, resumo seguro dos outputs, estado operacional e completude. Eventos planejados preservam dependências, executor e opcionalidade. O Event Store mantém esses campos sanitizados.
- `executors_laboratory.py`: agrega contagem e motivos de hipóteses não verificadas e indica avaliação parcial quando há versões ausentes ou verificações pendentes. Limite de três comparações preservado.
- `orchestration/orchestrator.py`: propostas de novas dependências durante execução são explicitamente rejeitadas (`running_dag_is_immutable`), pois esse scheduler só aplica prioridades. Antes, podiam ser validadas sem efetivamente alterar o DAG. Planejamento estático continua podendo validar dependências.
- `assessment.py`/`projection.py`: `execution_status` e `assessment_status` independentes. `completed + partial` é válido. Resultado de hipótese continua separado. O progresso mede etapas encerradas, não cobertura de vulnerabilidades. Tarefas planejadas entram no denominador desde o início.
- Histórico/API/React/relatório usam a mesma avaliação. Campanhas antigas permanecem intactas; quando há checkpoint íntegro, a API consulta seus motivos com proveniência `verified_checkpoint`, sem inventar eventos retroativos. A campanha original agora aparece como execução encerrada/análise parcial, com motivos acessíveis no XAI.
- Pipeline mantém oito cartões. Skip não recebe mais o mesmo rótulo de conclusão. Avisos sem identidade/critério não são apresentados como ausência de vulnerabilidades.

`complete` significa completude do trabalho selecionado e aplicável, nunca segurança absoluta. Consultoria opcional sem provedor/achados pode ser um no-op legítimo; ausência de dados em uma pesquisa selecionada não equivale a sucesso de análise.

## Agentes e comunicação

| Responsabilidade | Implementação e contrato |
|---|---|
| Descoberta/inventário | Discovery/Framework Inventory → `TechnologyComponent`, evidências referenciadas |
| Pesquisa | `CveResearchService` e providers → registros `CveRecord`, cobertura/falhas/cache |
| Correlação | `CveCorrelationEngine` → `CorrelationResult`, identidade antes da versão |
| Hipóteses | `HypothesisRegistry` → registros e histórico, sem promover a finding |
| Seleção/autorização/execução | `LaboratoryExecutor` → `PolicyEngine` → `LaboratoryManager` → protocolo → `DockerContainerManager` |
| Evidência | `EvidenceValidator`: hash, campanha, execução, worker, tempo, critérios e suficiência |
| Reflexão | `ReflectionAgent`: proposta delimitada; fallback determinístico declarado |
| Decisão | `DecisionValidator`: aprova/rejeita propostas, revisões append-only |
| Persistência/apresentação | Event Store, CheckpointStore, relatório e projeções somente leitura |

As tarefas compartilham contratos no `ExecutionContext` e referências estáveis; dependências representam disponibilidade de dados. A IA não substitui resultados especializados. A demo usa adaptadores de entrada de fixtures, não agentes duplicados para fabricar conclusões.

## Reproduzir e abrir

Na raiz do repositório (RTK conforme instruções locais):

```bash
rtk proxy docker build --network=none -f backend/Dockerfile.worker -t namira/worker:local backend
```

Dentro de `backend/`:

```bash
rtk proxy /home/erickpxd/scan-blueteam/.venv/bin/python -m pentest_pipeline.demo.seed_campaign --demo
```

Sem `--demo`, o CLI recusa a execução. A imagem precisa existir; não há pull automático, substituição por simulação ou exigência de credenciais de IA. Cada chamada cria um run_id novo e um diretório exclusivo. Tentativas anteriores são preservadas. `--reports-dir` permite uma raiz de relatórios separada.

Abra `http://localhost:5173/#test/20261113T085045Z-61c83415`, ou a campanha **NA MIRA — Demonstração Auditável** no histórico. Abra **Verificações e hipóteses desta campanha**, a operação e **Saída real do processo**. stdout/stderr são somente leitura, recolhidos por padrão. IDs, imagem, código de saída, tempo, limpeza e hash ficam na auditoria. O link para o Markdown baixa o relatório dessa campanha, não o da última execução global.

## Cenários e execução real

1. Fixture `demo-supported`, versão 1.2.0, intervalo [1.0.0, 2.0.0): comparação `supported`, hipótese `potential`.
2. Fixture `demo-contradicted`, versão 3.0.0: a pesquisa fornece inicialmente o resumo do produto sem intervalo; a correlação normal gera `candidate`/classificação `suspected`. Uma tarefa registrada lê o detalhe local do aviso e preserva o registro anterior. O worker lê a fixture completa e devolve `contradicted`. EvidenceValidator valida a cadeia; ReflectionAgent propõe `rejected`; DecisionValidator aprova **suspected → rejected**. Não há alteração artificial da conclusão inicial.
3. Fixture `demo-inconclusive`, versão null: comparação `inconclusive`; hipótese continua inconclusiva. Nenhuma versão inventada.
4. Operação desconhecida: PolicyEngine verifica TaskRegistry/allowlist, rejeita antes de criar worker; evento de controle operacional, não finding no alvo.

Quatro containers reais: um diagnóstico com quatro comandos fixos e três comparações da fixture. Diagnóstico captura `python --version`, `id`, `uname -s` e `sha256sum` do arquivo incluído na imagem. Sem shell, comandos/argumentos/caminhos fornecidos por IA ou terminal interativo. O diagnóstico não é uma validação de vulnerabilidade; sua classificação de segurança é não conclusiva/não aplicável.

Inventário/avisos/HTML são fixtures identificadas, URL `https://demo.invalid/` é apenas identificador. `FixtureTransport` não possui transporte de rede nem fallback; leituras geram `fixture_read`, não `request`/`response`. Nenhuma fixture é anunciada como resposta HTTP ao vivo. Worker, eventos, correlação e revisões são reais. Nenhuma resposta de modelo foi usada: `decision_source=deterministic`.

## Captura, integridade e isolamento

Captura vinculada ao execution_id e worker_id, com container_name, imagem, comando real do wrapper, início/fim, duração, exit_code, streams separados e truncamento. A saída do wrapper é JSON real e contém as saídas dos quatro subprocessos fixos no diagnóstico; a interface não inventa um prompt de terminal.

O protocolo limita mensagens a 256 KiB; o manager verifica stdout+stderr, timeout e limite durante a execução. Streams são lidos de arquivos temporários com leitura limitada, evitando acumular saída ilimitada na memória. Excertos persistidos têm até 8.192 caracteres por stream, UTF-8 com substituição, remoção de controles/ANSI e redação de campos de credencial. Arquivos de captura têm modo 0600, diretório 0700. Não há armazenamento de stdout bruto contendo segredos.

`PENTEST_CAPTURE_RETENTION_DAYS` aceita 0–365 (padrão 7). Zero não persiste saída. Expirados são removidos ao consultar a captura ou gravar nova captura; não há serviço de expurgo contínuo. A história da campanha e hashes permanecem. A API só entrega o artefato se seu hash corresponder ao registrado no evento; corrupção, symlink, expiração ou ausência não recebem saída substituta. Hash de captura refere-se ao **registro sanitizado**, não a uma assinatura criptográfica do container ou ao fluxo bruto descartado.

Preservados: imagem allowlisted, UID/GID 65534, `--network none`, read-only, `--cap-drop ALL`, no-new-privileges, tmpfs noexec/nosuid de 16 MiB, 1 CPU, memória/swap 256 MiB, 128 PIDs e timeout padrão 30 s. Nenhum `--privileged`, seccomp unconfined, AppArmor desabilitado, socket Docker no worker ou alteração de daemon/host.

## Verificação e limites restantes

- Suíte: `PENTEST_DOCKER_IT=1 .../.venv/bin/python -m unittest discover -s tests -q`: 348/348, nenhum skip.
- Build: `npm run build`: aprovado.
- Navegador: `node tools/e2e-web/run_phase65.mjs --demo-run 20261113T085045Z-61c83415`: 15 verificações; `--phase7`: 18. API real, stdout real, revisões, oito cartões, recarga, viewport móvel, persistência após reinício e ausência de exceções React.
- Campanha original consultada pela API: `completed/partial`; skips explicados pelo checkpoint íntegro. Dados originais não regravados.
- O timeout do NVD é fato histórico; disponibilidade externa não foi retestada. Não se elimina essa limitação marcando pesquisas como completas.
- Uma comparação de versão não comprova exploração. MITRE continua contextualização. Não houve execução de técnicas no Kali.
- A semântica de versões existente é comparação numérica simplificada; a demo usa versões estáveis simples, não prova correção para todos os ecossistemas/prereleases.
- Isolamento usa Docker e kernel do host; não é uma VM Kali nem uma fronteira absoluta contra código hostil. Não foi introduzido código hostil.
- A única versão não identificada é mantida como limitação real. Não se força análise completa para tornar a apresentação verde.
