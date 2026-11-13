# NA MIRA — Relatório de Demonstração Auditável

## Resumo executivo

Demonstração local com inventário e avisos fictícios. Nenhum alvo externo foi consultado. Os processos Docker, os eventos, as comparações e as revisões foram executados nesta tentativa.

Execução: **completed**. Completude da análise: **partial**.

A versão ausente impede concluir uma hipótese. Correspondência de versão não comprova exploração.

## Tecnologias e hipóteses

| Tecnologia (fixture) | Versão | Aviso fictício | Classificação independente |
|---|---|---|---|
| Demo Supported | 1.2.0 | DEMO-ADVISORY-001 | potential |
| Demo Contradicted | 3.0.0 | DEMO-ADVISORY-002 | rejected |
| Demo Unknown Version | Não identificada | DEMO-ADVISORY-003 | inconclusive |

## Verificações executadas

| Operação | Backend | Execução | Resultado |
|---|---|---|---|
| inspect_demo_environment | Docker real | completed | inconclusive |
| correlate_fixture_version | Docker real | completed | supported |
| correlate_fixture_version | Docker real | completed | contradicted |
| correlate_fixture_version | Docker real | completed | inconclusive |

O diagnóstico executa python --version, id, uname -s e sha256sum da fixture dentro do worker. A saída capturada fica em Verificações → Saída real do processo, disponível durante a retenção configurada.

## Revisões

- DEMO-ADVISORY-001: potential → potential; aprovada. Critérios registrados sustentam a observação dentro dos limites documentados.
- DEMO-ADVISORY-002: suspected → rejected; aprovada. A evidência válida contradiz a hipótese; possível falso positivo na conclusão anterior.
- DEMO-ADVISORY-003: inconclusive → inconclusive; aprovada. Faltam evidências verificáveis para determinar a conclusão.

## Controles operacionais

Operação desconhecida rejeitada pelo PolicyEngine antes de criar qualquer worker. É um controle da infraestrutura, não um achado no alvo.

Rede none; UID/GID 65534; filesystem somente leitura; cap-drop ALL; no-new-privileges; tmpfs noexec/nosuid; CPU, memória, PIDs, tempo e saída limitados. Sem Docker socket no worker.

## Evidências e auditoria

<details><summary>Identificadores e hashes verificáveis</summary>

- Campanha: `20261113T085045Z-61c83415`
- Imagem: `sha256:b1c30a4322d5f4f3d17f46ee06b354e0e3dfd8e5a6f75923168e9ebb82464411`
- Fixture SHA-256: `ab83fae26bc5c09a4f9c6ab0ab1a58c7ad87921f116b37a32947276c91a14d35`
- `exec-222bd57b019847a286c60c8e050d4239` · `worker-d012c808cddc49e78dd797ef4125f304` · saída sanitizada SHA-256 `32854135be529b768e05d7953b431aeeb9c8d157be1b21cc57c3e6155e11af96`
- `exec-458298f3d8bc438ba2c871fbc3e5eea0` · `lab-b38bd2cb9a094410a0aec856b0db0621` · saída sanitizada SHA-256 `a120a6e3956412e4427e9cb537e6b49620d2b627906e9555d836f376321df505`
- `exec-59080b5162484367a21bab1a79b832b6` · `lab-b3564e89a00d4cd098abf46ee43525ce` · saída sanitizada SHA-256 `cc0eff05e33a52614748eda7fb6b13472437d084487d8ec76c3104f1fed9e338`
- `exec-4f9b400fb436412a800555d80e0ff8a4` · `lab-bd1d457ffea34f13ba971ca1ddaaf8c1` · saída sanitizada SHA-256 `201cdee2209515ec3661ff383b678e84c721296e1049b311a8e05afef79bf7eb`
- `evidence:exec-458298f3d8bc438ba2c871fbc3e5eea0` · evidência SHA-256 `3384a2b95bf2cb8a41c4645b232ab14c1675d64e1573bdc97562c966deec4d55`
- `evidence:exec-59080b5162484367a21bab1a79b832b6` · evidência SHA-256 `f361f884e8aa0cddb6d1986b417e45f742cdaf02dc5a7ae84ff7af7926d0457a`
- `evidence:exec-4f9b400fb436412a800555d80e0ff8a4` · evidência SHA-256 `c881d6a9034c1a924bdd921415698095c1a1f6dc00bd77f39d51978ac1b50f7a`

</details>

## Limitações

- Inventário e avisos fictícios; nenhuma consulta a alvo externo.
- Processos e comparações executados no Docker real. Sem Kali, exploit ou comprovação de vulnerabilidade.
- Fallback determinístico: nenhuma resposta de IA foi gerada nesta demonstração.
- Uma tecnologia não tem versão; a avaliação permanece parcial.

## Conclusão

A campanha demonstra orquestração, isolamento, rastreabilidade e revisão de dados locais. Não demonstra exploração, comprometimento nem execução de técnicas MITRE no Kali.
