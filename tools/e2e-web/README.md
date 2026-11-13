# E2E legado do console vanilla

Este harness exercitava a interface removida de `web/` e não valida o frontend atual.
O frontend suportado está em `frontend/` e roda pelo Vite; a API Python não serve arquivos
da interface. Para validar o frontend atual, execute `npm run build` dentro de `frontend/`
e use o preview/proxy do Vite junto ao backend local, iniciado dentro de `backend/`.

## Aceite React da Fase 6.5

Após o build, na raiz execute `node tools/e2e-web/run_phase65.mjs`.
Requer Node 22+ (WebSocket global) e Google Chrome; `CHROME_BIN` permite selecionar
outro executável compatível. O Chrome usa seu sandbox padrão.

O script inicia uma API fixture e serve o build apenas em loopback, bloqueia
requisições externas da página e encerra seus processos ao terminar. Não inicia
campanha nem usa o backend ou Docker reais. Cobre sete estados operacionais,
validação inconclusiva, filtros, evidências, hipóteses sem verificação, histórico
salvo/reload, layout móvel e preservação dos oito cartões. Gera screenshots num
diretório temporário informado na saída. Persistência real e projeção de eventos
são verificadas separadamente pela suíte Python (`test_web_console.py` e
`test_phase65_acceptance.py`).

## Aceite integrado com Docker e API reais

Na raiz, com a imagem Python base já disponível e Docker funcional:

```sh
docker build --network=none -f backend/Dockerfile.worker -t namira/worker:local backend
npm --prefix frontend run build
node tools/e2e-web/run_phase65.mjs --real-docker
```

Requer `.venv/bin/python` com o backend instalado (ou variável `PYTHON` apontando
para o interpretador), além de Node/Chrome. Uma imagem ausente causa falha, sem
pull ou fallback simulado. Este modo substitui somente o transporte do alvo e
os avisos de segurança por fixtures em `backend/tests/phase65_fixtures.py`.
OrchestratorV2, TaskRegistry, PolicyEngine, TaskScheduler, laboratório, Docker,
protocolo, Event Store, checkpoints e CampaignConsole são reais.

`phase65_fixture_server.py` serve a API de produção em loopback; o proxy do
harness entrega suas respostas ao build React sem fabricar payloads. São cinco
campanhas: supported, contradicted, versão desconhecida/inconclusive, falha do
worker/not_evaluated e hipótese sem verificação. O aviso CVE-2099-6501 é fictício.
Nenhum alvo externo é consultado. O navegador também bloqueia requisições externas.

As 11 verificações incluem vínculos dos IDs, autorização anterior ao despacho,
evidências produzidas e seus critérios, apresentação nas duas abas, reinício do
servidor com igualdade dos payloads persistidos, reload da página, layout móvel,
oito cartões e ausência de exceções JavaScript. O worker não é simulado.

A saída informa um diretório `/tmp/namira-phase65-*` com `acceptance.json`,
`api-<cenario>.json`, captura de tela e `backend/reports/` contendo os resultados
e checkpoints reais. O diretório não substitui os relatórios do usuário.
Somente o perfil temporário do navegador e os processos do harness são limpos;
artefatos ficam disponíveis até a limpeza normal de `/tmp`.

Verificação complementar do isolamento/cancelamento:
`.venv/bin/python tools/docker/verify_worker.py`. Suíte completa, em `backend/`:
`PENTEST_DOCKER_IT=1 ../.venv/bin/python -m unittest discover -s tests -q`.

## Fase 7: reflexão e autocorreção

Após o mesmo build de imagem/frontend, execute:

```sh
node tools/e2e-web/run_phase65.mjs --phase7
```

Reutiliza o servidor e os cinco cenários, ativando a revisão independente no V2.
A fixture de contradição registra uma conclusão inicial fraca deliberada; o
comparador do worker e o EvidenceValidator não são substituídos. Docker real
produz a contradição que permite revisar `potential` para `rejected`.
`ControlledReflection` fornece uma resposta estruturada fixa; no cenário de
versão desconhecida, recomenda indevidamente `confirmed`, que deve ser recusado.
Não há chamadas a providers externos.

São 18 verificações: inclui navegação da execução à hipótese, classificação
inicial/atual, histórico de revisão, justificativa/evidências, rejeição da IA,
reinício/reload e XAI persistente. Gera capturas `phase7-contradiction-revised.png`
e `phase7-unjustified-ai-rejected.png`, além dos mesmos payloads, relatórios e
checkpoints reais. O modo padrão e `--real-docker` continuam validando a Fase 6.5
com a revisão independente desativada.

Na aplicação, a ativação é `PENTEST_INDEPENDENT_VALIDATION=enabled` com V2.
`PENTEST_REFLECTION_PROVIDER=openai|bedrock` é opcional; sem ele, o ReflectionAgent
é determinístico. Credenciais/modelos existentes são reutilizados.

## Clareza das verificações e relatório existente

Os modos acima também verificam a separação entre resultado legível e auditoria
recolhida, mantendo acessíveis IDs, hashes e revisões. A auditoria não foi removida.
O modo opcional `rtk proxy node tools/e2e-web/run_phase65.mjs --review-run RUN_ID`
lê uma campanha existente da API local em `127.0.0.1:8765`, sem iniciar varredura.
Esse cenário de regressão exige um relatório histórico com comparação entre
produtos incompatíveis e revisão independente. Verifica contagens HTTP/local/Kali,
explicação, auditoria, navegação à hipótese e layout móvel (sete verificações).
# Demonstração auditável

Depois de gerar a campanha com `python -m pentest_pipeline.demo.seed_campaign --demo`
dentro de `backend/`, compilar o frontend e iniciar a API local na porta 8765:

```bash
rtk proxy node tools/e2e-web/run_phase65.mjs --demo-run ID_DA_CAMPANHA
```

O modo faz apenas leituras da API real: verifica quatro workers, stdout/stderr,
controle negado sem worker, três resultados de hipótese, revisão independente,
análise parcial, relatório, reload, oito cartões e viewport móvel. Bloqueia rede
externa no navegador. As fixtures são entradas explicitamente identificadas;
os processos Docker não são simulados. Consulte `docs/architecture/orchestration-auditable-demo.md`.
