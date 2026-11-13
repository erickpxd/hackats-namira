# Prompt para o Kiro — deploy completo do NA MIRA e seed auditável

Você está trabalhando no projeto **NA MIRA**, repositório:
`https://github.com/erickpxd/hackats-namira.git`, branch `main`.

Quero que você **execute o deploy**, configure os ambientes e rode o seed real.
Não entregue somente um plano ou arquivos de exemplo: finalize o serviço acessível,
persistência, campanha demonstrativa e verificações de funcionamento.

## Autorização e variáveis de ambiente

Esta é uma PoC. **Você está autorizado a preencher e configurar as variáveis de
ambiente reais necessárias no servidor**, usando as credenciais já disponibilizadas
no ambiente, no arquivo privado `backend/.env` (se estiver disponível na máquina de
origem) ou no gerenciador de segredos da infraestrutura. Não deixe essa etapa para
eu fazer manualmente. Configure também as flags de orquestração, laboratório e IA.

O projeto local usa **AWS Bedrock**. O arquivo versionado `backend/.env.example`
contém os nomes e valores não secretos. O token real é
`AWS_BEARER_TOKEN_BEDROCK`; ele não está no Git. Também é possível usar a role ou
credenciais AWS já autorizadas no servidor. Não confunda bearer token do Bedrock com
Access Key ID/Secret Access Key. Preserve modelo/região reais já configurados,
quando disponíveis e compatíveis com a conta.

Guarde valores reais em configuração privada de runtime, por exemplo
`/etc/namira/namira.env` com permissão 0600 e `EnvironmentFile=` no systemd.
Não coloque tokens no repositório, prompt de entrega, logs ou variáveis `VITE_*`.
Não é necessário pedir confirmação para cada variável: a configuração está
autorizada. Se uma credencial ou acesso à infraestrutura realmente não existir,
informe precisamente o que falta, sem inventar valores. Continue as etapas que não
dependem disso; o seed determinístico não exige credenciais externas.

## Leia e confirme antes de executar

- `docs/architecture/migration-progress.md`
- `docs/architecture/orchestration-auditable-demo.md`
- `docs/architecture/auditable-demo-manifest.json`
- `backend/.env.example`
- `backend/Dockerfile.worker`
- `backend/pentest_pipeline/web_server.py`
- `backend/pentest_pipeline/demo/seed_campaign.py`
- `frontend/vite.config.js`

Atualize o checkout de `main` e registre o commit implantado. O último baseline
local é **348 testes aprovados, zero falhas e zero pulados**, build React aprovado,
15 verificações de navegador da demo e 18 de regressão da Fase 7. Esses números
são referência: registre os resultados realmente obtidos no servidor.

## Infraestrutura e processos

Use a infraestrutura já disponível. O backend precisa executar **Docker real**,
manter arquivos persistentes e ficar ativo entre requisições. Se o destino atual
for apenas hospedagem estática/serverless sem essas capacidades, coloque o backend
numa VM Linux com Docker disponível; não declare completo um deploy somente do
frontend. Uma única VM com frontend estático, API e Docker atende esta PoC.

Estrutura existente:

- Frontend React/Vite em `frontend/`, build em `frontend/dist/`.
- Backend Python em `backend/`, pacote `pentest_pipeline`.
- Worker `namira/worker:local`, construído de `backend/Dockerfile.worker`.
- API Python escuta **127.0.0.1:8765**. É um serviço do host, com acesso ao daemon
  Docker para criar workers. Os workers nunca recebem o socket Docker.
- Relatórios, checkpoints e capturas ficam em **`backend/reports/`**.

Prepare Python compatível com o projeto (>=3.11; a imagem do worker usa 3.12),
Node compatível com Vite e o harness (22 ou superior), npm e Docker Engine.
Reutilize o runtime funcional; não reinstale Docker desnecessariamente.

Na raiz do checkout, adapte somente os caminhos ao servidor:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e './backend[bedrock]'
npm --prefix frontend ci
npm --prefix frontend run build
docker build --network=none -f backend/Dockerfile.worker -t namira/worker:local backend
```

Use instalação **editable** a partir do checkout: fixtures JSON e caminhos de
frontend/relatórios precisam continuar disponíveis nessa estrutura. Se precisar
obter a imagem base `python:3.12-slim`, faça isso durante a preparação da imagem;
o seed e os workers não podem substituir Docker por execução simulada.

## Configuração do serviço

Configure os valores de `backend/.env.example` no ambiente privado do serviço.
Observe a diferença entre os flags: `PENTEST_CVE_INTELLIGENCE=1` e
`PENTEST_AI_PLANNING=1`; nesses dois, o valor `enabled` **não ativa a funcionalidade**.
Laboratório, execução em container, validação independente e MITRE usam `enabled`.
Mantenha `PENTEST_LABORATORY_INPROCESS=0`.

**O backend não lê `.env` automaticamente.** Injete as variáveis efetivamente no
processo, por exemplo com systemd `EnvironmentFile=/etc/namira/namira.env`.
Verifique presença dos nomes sem imprimir os valores secretos.

Crie um serviço persistente com usuário dedicado, diretório de trabalho `backend/`,
ambiente configurado, reinício controlado e comando equivalente a:

```bash
/CAMINHO/DO/REPO/.venv/bin/python -m pentest_pipeline.web_server --port 8765 --ai --ai-provider bedrock
```

O usuário do serviço deve conseguir executar Docker e escrever nos relatórios.
Execute também o seed com esse mesmo usuário para não gerar capturas 0600 ilegíveis
pela API. Não rode o worker como root nem flexibilize suas restrições para corrigir
permissões do serviço.

Se IA não puder ser configurada por falta real de credenciais, mantenha a leitura
da demo funcionando e declare claramente essa pendência; não anuncie novas
varreduras com IA como validadas. Não use uma chave fictícia para iniciar `--ai`.

## Frontend, proxy e domínio

Sirva `frontend/dist/` com Nginx ou equivalente. Não use o servidor Vite de
desenvolvimento como deploy. Encaminhe `/api/` e `/evidence/` para a API local e
sirva o restante como SPA. API e frontend devem aparecer na mesma origem HTTPS.
Configure o acesso da PoC para os avaliadores, com controle de acesso no proxy;
as rotas que iniciam campanhas e consomem credenciais não devem ficar abertas
anonimamente na internet.

**Atenção ao contrato real de Host/Origin:**

- A API recusa `Host` externo. No upstream, encaminhe
  `Host: 127.0.0.1:8765`.
- Os POSTs exigem `Origin: http://127.0.0.1:8765`.
- No proxy, valide primeiro que o Origin recebido pertence exatamente ao domínio
  HTTPS implantado. Só depois traduza o Origin para o valor interno esperado.
  Rejeite origens diferentes; não aceite todas e não remova as validações Python.
- Teste requisições válidas e rejeição de origem diferente sem iniciar varredura
  externa. Por exemplo, POST com `authorization_confirmed=false` deve chegar à
  validação da API e ser recusado sem executar campanha.
- Não crie CORS `*`, não exponha a porta 8765 publicamente e não publique arquivos
  de ambiente ou o diretório bruto de capturas pelo servidor estático.

Garanta que a apresentação da splash, vídeos, ícones, fontes e rotas por hash
funcione na URL publicada. Preserve os oito cartões da pipeline.

## Persistência

Preserve **todo `backend/reports/`**, incluindo `checkpoints/` e `worker-captures/`,
entre reinícios e atualizações. Use disco/diretório persistente e o caminho real
esperado pelo código, mantendo permissões corretas. Não sobrescreva campanhas.
Não aponte o seed para outro `--reports-dir` se a API continuar lendo o diretório
padrão; ambos precisam acessar os mesmos dados.

`PENTEST_CAPTURE_RETENTION_DAYS=7` conserva saídas por sete dias. Capturas expiradas
são removidas na consulta ou na próxima gravação, e metadados/hashes permanecem.
Não use zero na apresentação: isso desativa a persistência das saídas.

## Execute o seed real, sem chamadas a alvos ou modelos externos

Use **o módulo abaixo**, não `backend/demo/poc_final_demo.py`, que é uma outra
demonstração local sem o mesmo aceite Docker.

Dentro de `backend/`, com o mesmo usuário do serviço:

```bash
env PENTEST_AI_PLANNING=0 PENTEST_AI_PLANNING_PROVIDER= PENTEST_REFLECTION_PROVIDER= \
  ../.venv/bin/python -m pentest_pipeline.demo.seed_campaign --demo
```

Essas sobrescritas valem **somente para o processo do seed**. O serviço mantém seus
providers reais configurados. Limpar `PENTEST_REFLECTION_PROVIDER` é necessário
porque o OrchestratorV2 consulta essa variável mesmo quando nenhum provider é
passado explicitamente; o seed deve usar reflexão determinística e não chamar IA.

O seed deve criar **NA MIRA — Demonstração Auditável**, pelo OrchestratorV2,
TaskRegistry, TaskScheduler, PolicyEngine, laboratório e validação independente.
Não insira eventos manualmente e não copie o run_id ou relatório da máquina local
como se fossem resultados do servidor. Cada tentativa recebe ID novo.

Resultados esperados:

1. **Quatro workers Docker reais**, exit code 0, saída capturada e limpeza confirmada.
2. Diagnóstico com comandos fixos: `python --version`, `id`, `uname -s` e
   `sha256sum` da fixture. UID/GID 65534, e hash correspondente à fixture na imagem.
3. Três comparações da fixture: `supported`, `contradicted`, `inconclusive`.
4. Hipóteses: `potential`, `rejected`, `inconclusive`.
5. Revisão independente **suspected → rejected**, preservando o estado original.
6. Operação desconhecida rejeitada pelo PolicyEngine antes de criar worker.
7. Estado final **`execution_status=completed` e `assessment_status=partial`**.
8. Nenhuma resposta de fixture apresentada como coleta HTTP ao vivo; nenhuma
   exploração, requisição a alvo externo ou execução de técnicas no Kali.
9. `errors: []` no retorno do CLI e evidências/manifesto persistidos.

Os workers devem manter rede `none`, usuário não root, filesystem read-only,
cap-drop ALL, no-new-privileges, seccomp/AppArmor padrão quando aplicável, tmpfs
noexec/nosuid e limites existentes. Não use privileged, seccomp unconfined, socket
Docker dentro do worker ou capabilities adicionais. Se houver bloqueio do host,
diagnostique sem trocar silenciosamente para `InProcessContainerManager`.

## Valide o deploy de ponta a ponta

- API local: `/api/status`, `/api/history` e `/api/history/<NOVO_RUN_ID>`.
- Relatório da execução: `/api/history/<NOVO_RUN_ID>/report.md`.
- Abra a URL pública `/#test/<NOVO_RUN_ID>`.
- Mostre as hipóteses, revisão, análise parcial, motivos dos skips e XAI.
- Abra uma operação → **Saída real do processo**: stdout e stderr separados,
  vinculados ao execution_id, sem erros de integridade e somente leitura.
- Recarregue a página e reinicie o serviço. Confirme que IDs, saídas, hipóteses,
  relatório e revisões continuam disponíveis; não rode outro seed para mascarar
  perda de persistência.
- Confira que nenhum worker dessa campanha ficou em execução após finalizar.

Rode os testes a partir de `backend/`, em ambiente de teste isolado dos providers
externos do serviço:

```bash
env PENTEST_DOCKER_IT=1 PENTEST_ORCHESTRATOR=legacy PENTEST_CVE_INTELLIGENCE=0 \
  PENTEST_AI_PLANNING=0 PENTEST_AI_PLANNING_PROVIDER= PENTEST_REFLECTION_PROVIDER= \
  PENTEST_CONTAINER_EXECUTION=disabled PENTEST_LABORATORY=disabled \
  PENTEST_INDEPENDENT_VALIDATION=disabled PENTEST_MITRE_ATTACK=disabled \
  ../.venv/bin/python -m unittest discover -s tests -q
```

As flags desativadas acima são locais ao comando de testes: os testes habilitam
explicitamente o que cada cenário verifica; o serviço de deploy permanece com
sua configuração. Confirme build com `npm --prefix frontend run build` na raiz.

Se Chrome estiver disponível, na raiz:

```bash
node tools/e2e-web/run_phase65.mjs --demo-run NOVO_RUN_ID
node tools/e2e-web/run_phase65.mjs --phase7
```

O primeiro modo consulta a API real em 127.0.0.1:8765 e serve o build num proxy
local de teste. Ele não substitui uma inspeção da URL pública com TLS/proxy.
Sem navegador no servidor, use o navegador do seu ambiente para a URL pública e
registre precisamente a validação feita; não invente aprovação do harness.

## Entrega final

Informe de forma objetiva:

- URL pública e link direto da campanha demonstrativa.
- Commit implantado e infraestrutura usada.
- Serviços ativos e como reiniciar/consultar logs.
- Variáveis configuradas **pelos nomes**, provedor/modelo/região e origem privada
  das credenciais; não mostre valores secretos.
- ID da campanha nova, quatro execuções, resultados, hashes e revisão.
- Local do manifesto/relatório no servidor e política de persistência/retenção.
- Resultados reais de testes, build, navegador, API pública e reinício.
- Qualquer limitação ou bloqueio restante.

Salve também um registro sem segredos em `docs/deploy/deployment-result.md`.
Não declare o deploy completo se só o frontend estiver acessível, se o Docker
estiver simulado, se as saídas forem de fixtures ou se os dados sumirem ao reiniciar.
