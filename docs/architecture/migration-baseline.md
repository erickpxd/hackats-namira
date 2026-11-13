# Baseline da Arquitetura — Pré-migração (Fase 1)

> Documento de inspeção. **Nenhum comportamento foi alterado** durante este
> levantamento. Todas as afirmações abaixo foram confirmadas no código em
> `backend/pentest_pipeline/` na data da Fase 1.

## 1. Mapa dos componentes atuais

| Módulo | Responsabilidade | Confirmado |
|---|---|---|
| `pipeline.py` | `run_scan` — orquestra a sequência fixa de etapas e monta `ScanResult`. | ✔ `def run_scan` (linha ~40) |
| `agents.py` | Agentes determinísticos (`ScopeAgent`, `DiscoveryAgent`, `TestAgent`, `SurfaceTestAgent`, `TriageAgent`, `RemediationAgent`). | ✔ |
| `ai.py` | Planners/reviewers/advisors OpenAI e Bedrock + `create_ai_components`. | ✔ |
| `target_analysis.py` | Análise local paralela e hipóteses (sem promover a achado). | ✔ |
| `transport.py` | `BoundedTransport` — limites de rede, orçamento, `Response`, exceções de controle. | ✔ |
| `scope.py` | `ScopeConfig` (frozen) — escopo autorizado **e** orçamento; `assert_request`, `validate`. | ✔ |
| `models.py` | `ScanResult`, `Finding` (dataclasses com `to_dict`). | ✔ |
| `stage_plan.py` | Planos declarados por etapa (`_STEPS`, `record_step_plan`, `plan_observation`). | ✔ |
| `report.py` | `render_markdown`, `save_run`. | ✔ |
| `monitoring.py` | `compare_runs`, `MonitorAgent`. | ✔ |
| `web_server.py` | `CampaignConsole` + HTTP server (`/api/*`), worker em thread. | ✔ |
| `__main__.py` | CLI (`scan`, `monitor`). | ✔ |
| `attack_map.py` / `attack_poc.py` | PoC de orientação MITRE ATT&CK (read-only, derivada de `actions`/`findings`). | ✔ (fora do caminho de execução) |

### Fluxo de execução atual (confirmado em `run_scan`)

`scope → discovery → check_selection → ai_planning → asset_fetch →
framework_inventory → surface_checks → headers → cookies → triage →
demo_archive → remediation → target_analysis → ai_target_review → ai_advisor`

Cada etapa registra um plano declarado via `record_step_plan` **antes** de executar.

## 2. Dependências principais

- **Runtime: somente biblioteca padrão.** `pyproject.toml` → `dependencies = []`.
  `boto3` é opcional (`optional-dependencies.bedrock`) para o provedor Bedrock.
- Imports externos no código: apenas `ipaddress`, `ssl` e stdlib. Nenhuma
  dependência de terceiros no caminho de execução padrão.
- **Configuração por ambiente:** `OPENAI_API_KEY`, `PENTEST_AI_PROVIDER`,
  `PENTEST_AI_MODEL`, `PENTEST_BEDROCK_MODEL`, `PENTEST_BEDROCK_REGION`,
  `AWS_REGION`/`AWS_DEFAULT_REGION`, `AWS_BEARER_TOKEN_BEDROCK`.
  **Nova nesta fase:** `PENTEST_ORCHESTRATOR` (default `legacy`).

## 3. Contratos públicos

### `run_scan` (ponto central de execução)
```
run_scan(config, *, stop_event=None, on_event=None, ai_advisor=None,
         ai_planner=None, ai_target_reviewer=None, selected_checks=None,
         approval_queue=None, approved_actions=()) -> ScanResult
```
Chamado em: `web_server.py` (worker da campanha) e `__main__.py` (CLI).
Reexportado em `pentest_pipeline/__init__.py`.

### API HTTP consumida pelo frontend (confirmado em `frontend/src/`)
Endpoints: `/api/status`, `/api/campaign/start`, `/api/campaign/stop`,
`/api/approval/decision`, `/api/history`, `/api/history/<id>`,
`/api/report.json`, `/api/report.md`.

Campos do payload lidos pelo frontend: `running`, `result`, `events`, e dentro
de `result`: `run_id`, `target`, `status`, `stop_reason`, `summary`,
`findings[].{severity,confidence,...}`, `actions`, `recommendations`,
`started_at`. **Estes campos não podem mudar de forma incompatível.**

### `ScanResult.to_dict()` / `Finding.to_dict()`
Formato JSON estável; `summary` contém `requests`, `findings`,
`selected_checks`, `available_checks`, `ruleset_hash`, `by_severity`,
`by_status`, `audit_events`, `scope`.

## 4. Regras de autorização, escopo e orçamento (preservar)

- `ScopeConfig.assert_request` bloqueia host/esquema/porta/método fora do escopo
  e IPs privados (salvo `allow_private_ips`).
- Orçamento: `max_requests`, `max_assets`, `min_interval_seconds`,
  `timeout_seconds`, `max_response_bytes` — propriedade do `ScopeConfig` e
  aplicados pelo `BoundedTransport`.
- Aprovações humanas: `ApprovalQueue` para ações condicionais
  (`quoted_search`). Nenhuma ação condicional roda sem aprovação explícita.
- Redirecionamentos são registrados mas **nunca seguidos** (confirmado em
  `test_scope_and_monitor`).

## 5. Riscos de regressão identificados

| Risco | Mitigação na Fase 1 |
|---|---|
| Testes da API mockam `web_server.run_scan`. | Worker agora usa `run_campaign`; os 4 mocks foram retargetados para `web_server.run_campaign` (mesma intenção, mesmo seam). |
| Ciclo de import ao expor `run_campaign` no pacote. | `entry.py` importa `run_scan` **tardiamente**; suíte completa passa. |
| `v2` acionado antes da implementação. | `ensure_executable` levanta erro controlado; sem fallback silencioso. |
| Mudança de assinatura de `run_scan`. | `run_campaign` repassa `**kwargs` sem alterar a assinatura. |

## 6. Funcionalidades que precisam ser preservadas

Execução legada completa; contratos da API/CLI; formato de relatórios;
controles de escopo/orçamento/aprovação; trilha de auditoria (`actions`);
serialização de `ScanResult`/`Finding`; comparação de campanhas (`compare_runs`).

## 7. Limitações conhecidas (herdadas, não corrigidas nesta fase)

1. `run_scan` fixa a ordem das etapas (sem máquina de estados formal).
2. Agentes não têm coordenação autônoma.
3. Persistência ocorre majoritariamente **após** a conclusão (sem checkpoints).
4. Eventos ao vivo (`on_event`) e persistidos podem divergir da trilha final.
5. Sem mecanismo de retomada.
6. `pytest` reporta "no tests collected" neste ambiente; o runner canônico é
   `python -m unittest` (104 testes, todos passando).

## 8. Estratégia de rollback

A Fase 1 é aditiva e reversível:

1. **Flag:** manter `PENTEST_ORCHESTRATOR=legacy` (padrão) preserva 100% do
   comportamento atual; `v2` é inerte (erro controlado).
2. **Reverter wiring:** trocar `run_campaign` de volta por `run_scan` em
   `web_server.py`/`__main__.py` e restaurar os mocks dos testes.
3. **Remover pacotes novos:** `contracts/` e `orchestration/` não têm
   dependentes no caminho legado além do wiring acima; podem ser removidos sem
   afetar `run_scan`.
4. Nenhum detector, formato de relatório ou contrato de API foi alterado — não
   há migração de dados a desfazer.
