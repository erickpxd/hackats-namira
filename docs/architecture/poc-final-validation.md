# PoC Final — Validação (Fase 8)

> Registro de aceite da Prova de Conceito do hackathon. Reprodutível, offline e
> seguro. Nenhuma técnica de ataque é executada; a camada MITRE é de
> **classificação e contextualização**.

## 1. O que a PoC demonstra

Uma campanha de análise de segurança que, de ponta a ponta e com componentes
reais, produz:

1. **Achados** por verificações HTTP não destrutivas (agentes existentes).
2. **Hipóteses de vulnerabilidades conhecidas** (CVE Intelligence — NVD/OSV/CISA
   KEV via cliente com allowlist), separadas dos achados.
3. **Validação independente** com laboratório isolado (worker sobre
   `ContainerManager`), resultando em três desfechos verificáveis:
   - **A — hipótese sustentada** (`potential`);
   - **B — hipótese contradita por evidência** (`rejected`);
   - **C — evidência insuficiente** (`inconclusive`).
4. **Contextualização MITRE ATT&CK** dos achados, com estados
   `mapped` / `candidate` / `unmapped`.
5. **Relatório final** em Markdown com MITRE, revisões e limitações.

Flags (todos com padrão que preserva o baseline):
`PENTEST_ORCHESTRATOR`, `PENTEST_CVE_INTELLIGENCE`, `PENTEST_LABORATORY`,
`PENTEST_AI_PLANNING`, `PENTEST_CONTAINER_EXECUTION`, `PENTEST_MITRE_ATTACK`.

## 2. Demonstração A/B/C + MITRE (segura, sem Docker, sem rede)

```bash
cd backend
PYTHONPATH=.:tests python demo/poc_final_demo.py [diretório_de_saída]
```

O script **reusa os componentes reais** (OrchestratorV2, CVE Intelligence,
`LaboratoryManager` sobre `InProcessContainerManager`, EvidenceValidator →
ReflectionAgent → DecisionValidator, contextualização MITRE). Apenas o transporte
do alvo e a pesquisa de advisories são fixtures locais. `socket.create_connection`
é bloqueado durante a demonstração.

Saída esperada (resumo):

```
[A] hipótese sustentada        -> potential      OK
[B] hipótese contradita        -> rejected       OK
[C] evidência insuficiente     -> inconclusive   OK
[MITRE] candidate T1539 ...; unmapped missing_* ...
Resultado geral: OK
```

Cada cenário grava `cenario_<A|B|C>_<scenario>.md` com a seção
"Contextualização MITRE ATT&CK".

## 3. MITRE ATT&CK — regras de honestidade

A camada (`backend/pentest_pipeline/mitre/`, contrato
`contracts/mitre.py`) segue regras verificáveis:

- Só atribui **IDs ATT&CK válidos** de um catálogo curado local
  (`DEFAULT_CATALOG`), indexado pela **categoria de verificação** — nunca por
  correspondência textual com o nome de uma CVE.
- **Nenhuma atribuição sem evidência** (`evidence_refs` obrigatório).
- Estado **`unmapped`** é legítimo e preferido à especulação (ex.: cabeçalhos de
  segurança ausentes são controle defensivo ausente, não comportamento
  adversário → `unmapped`).
- **`mapped`** exige fraqueza confirmada de forma determinística (achado
  `confirmed`/`high`); caso contrário **`candidate`** (requer revisão humana).
  Uma comparação local de versão permanece hipótese — **nunca** confirmação de
  exploração.
- Distingue `known_vulnerability` de `observed_behavior`. O scanner observa
  fraquezas; não presencia ações adversárias.
- A versão da fonte é registrada em cada mapeamento (`MITRE_SOURCE_VERSION`).

Catálogo atual (conservador): `sql_error_exposure`, `ftp_listing`,
`ftp_file_head` → T1190 (TA0001); `public_metrics` → T1592,
`source_map_reference` → T1592.002 (TA0043); `cookie_flags` → T1539 (TA0006).
Demais categorias ficam `unmapped`.

## 4. Isolamento do worker (reuso, não reconstrução)

`LaboratoryManager` reusa `ContainerManager` e `PolicyEngine`. O
`DockerContainerManager` já aplica: imagem **allowlisted** (suporta digest
pinado), comando de worker **fixo**, `--user` não-root, `--read-only`,
`--network none`, `--security-opt no-new-privileges`, `--cap-drop ALL`,
limites de `--pids-limit`/`--memory`/`--cpus` e tmpfs `noexec,nosuid`. Entrada do
worker é limitada em tamanho; nada vindo de alvo/resposta/IA define imagem,
volumes ou comando. Operações são allowlisted (não há exploração/payload).

## 5. Execução com Docker real (opcional, opt-in)

Requer a imagem `namira/worker:local` e `PENTEST_DOCKER_IT=1`:

```bash
cd backend
PENTEST_DOCKER_IT=1 python -m unittest tests.test_phase7_integration -v
```

Sem a imagem/flag, os dois testes de Docker real são **pulados** (nunca se puxa
imagem substituta).

## 6. Suíte e build

```bash
cd backend && python -m unittest discover -s tests -p "test_*.py"
# Ran 333 tests ... OK (skipped=2)

cd ../frontend && node_modules/.bin/vite build --config vite.config.js
# ✓ built
```

## 7. Limitações declaradas

- As hipóteses de CVE são **conhecimento público correlacionado**, não prova de
  que a vulnerabilidade existe no alvo.
- A contextualização MITRE classifica fraquezas; **não executa técnicas** nem
  comprova exploração. Estados `candidate` exigem revisão humana.
- A demonstração A/B/C usa fixtures locais para tornar os desfechos
  determinísticos; os componentes de decisão são reais.
- A interface reflete apenas atividade real registrada (sem atividade inventada).
