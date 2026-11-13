# Diagnóstico Docker — Fase 6.5

## Situação atual — resolvido em 13/11/2026

O operador autorizou a substituição do Docker e a exclusão dos dados antigos de
estudo. O Snap foi removido com `snap remove docker --purge`, incluindo containers,
volumes e caches. Docker Engine **29.8.0 oficial**, CLI, containerd.io 2.4.2,
Buildx e Compose foram instalados para Ubuntu 26.04/amd64; assinaturas e hashes
dos pacotes foram conferidos. O repositório oficial está configurado para
atualizações. O daemon agora usa `/var/lib/docker` e o serviço `docker.service`.

**Resultado:** suíte com `PENTEST_DOCKER_IT=1`: **251 testes aprovados, zero
falhas/erros, zero pulados**. O worker inicia e conclui a operação sem retirar
`no-new-privileges`, AppArmor ou seccomp. A mesma versão do Engine fora do
confinamento Snap resolve a incompatibilidade diagnosticada abaixo.

Verificação adicional reproduzível, na raiz do projeto:

```sh
rtk proxy .venv/bin/python tools/docker/verify_worker.py
```

O probe real confirmou UID/GID 65534, `NoNewPrivs=1`, `Seccomp=2`, `CapEff=0`,
`docker-default (enforce)`, filesystem raiz read-only, tmpfs gravável/noexec,
somente interface `lo`, ausência do socket Docker e cgroups configurados com
256 MiB de memória, 128 PIDs e quota de 1 CPU. O cancelamento ocorreu depois
da inicialização do Python e a remoção do container foi confirmada.
As operações são fixas, locais e sem rede; a allowlist da aplicação não mudou.

Os trechos seguintes preservam o diagnóstico e as propostas anteriores à
autorização. Eles não representam bloqueios atuais.

## Confirmação oficial na consolidação

A Canonical documenta expressamente que no-new-privileges impede a inicialização
de containers no Snap por restrição AppArmor:
https://github.com/canonical/docker-snap/blob/main/README.md

O Docker Engine distribuído pelo repositório oficial é uma alternativa:
https://docs.docker.com/engine/install/ubuntu/
Não é uma troca transparente do daemon Snap e não foi instalado automaticamente.
Opção de menor impacto para validar: um host/VM separado administrado pelo operador,
com Engine oficial e as mesmas flags do worker. Migração no host atual exige
inventário/backup dos volumes, configuração de redes e janela de manutenção;
não pode garantir ausência de interrupção dos quatro containers ativos observados.
Nenhuma alteração de perfil AppArmor ou retirada de no-new-privileges foi aplicada.

Diagnóstico local em 13/11/2026. Nenhum teste contra alvos externos.

## Causa comprovada

Docker Engine 29.8.0, Snap revisão 3618, runtime runc, containerd,
kernel 7.0.0-43-generic, host x86_64. AppArmor e seccomp builtin ativos.
O kernel registra na inicialização:

```text
apparmor="DENIED" operation="exec" info="no new privs" error=-1
profile="snap.docker.dockerd" name="/usr/local/bin/python"
comm="runc:[2:INIT]" fsuid=65534 target="docker-default"
```

O bloqueio ocorre na transição de perfil AppArmor sob no-new-privileges,
antes do código Python. Não é uma exceção da aplicação nem permissão UNIX
ausente no executável: /usr/local/bin/python aponta para python3.12, modo
0755, executável por UID 65534. Ambas as imagens são amd64, sem ENTRYPOINT.

## Comparação reproduzida

| Imagem | Configuração diagnóstica | Resultado |
|---|---|---|
| python:3.12-slim | --network none | Python iniciou |
| python:3.12-slim | --network none --user 65534:65534 | Python iniciou |
| namira/worker:local | --network none --user 65534:65534 | Python iniciou |
| Ambas | mesmas opções + --security-opt no-new-privileges | exec recusado, código 255 |

Esses testes básicos apenas isolam a causa; não validam isolamento completo.
A falha reproduz sem read-only, tmpfs, cap-drop ou limites de recursos, logo
essas opções não são necessárias para provocá-la. O registro do kernel
identifica AppArmor, não seccomp, como autor da recusa observada.

## Correção e limites

Nenhuma restrição do worker foi removida. Não existe correção comprovada no
Dockerfile ou no código Python para esta recusa do host. A correção exige um
runtime/perfil do host compatível com a transição AppArmor e no-new-privileges.
Não foram modificados Snap, perfis, kernel nem daemon: o host possui outros
containers e serviços ativos. Uma atualização suportada do runtime ou uma
migração planejada do Docker Snap deve ser avaliada pelo administrador,
preservando dados e workloads. Nenhuma versão corretiva específica foi verificada.

Após corrigir o ambiente, executar em backend/:

```sh
PENTEST_DOCKER_IT=1 python3 -m unittest discover -s tests -p test_container_execution.py -v
```

Permanecem obrigatórios: usuário não root, read-only, rede none, cap-drop ALL,
no-new-privileges, tmpfs restrita, limites de CPU/memória/PIDs, timeout, imagem
permitida e ausência de socket Docker no worker. O teste real continua falhando
até a correção do host; isolamento real permanece não validado.

## Revalidação da consolidação

Em 13/11/2026 a imagem foi reconstruída sem rede no build:

```sh
rtk proxy docker build --network=none -f backend/Dockerfile.worker -t namira/worker:local backend
```

Imagem resultante (manifest list):
`sha256:e3fb22184cec76042143c5685603c399d28acac4e62f1d0149e2fb1e95482913`.
Na suíte completa, a chamada real a DockerContainerManager manteve todas as
flags e retornou `rc=255`, com `exec /usr/local/bin/python: operation not permitted`.
Foram 251 testes: 250 aprovados, um erro no Docker real, zero pulados.
O diagnóstico não foi refeito nem contornado. Após a tentativa, a consulta
`docker ps -a --filter name=namira-worker-` não listou workers remanescentes.
Os quatro containers já existentes continuaram em execução.

## Caminho de menor impacto, aguardando ambiente do operador

Docker documenta a seleção de daemon por `DOCKER_CONTEXT`, sem trocar o contexto
padrão: [Docker contexts](https://docs.docker.com/engine/manage-resources/contexts/).
O host atual tem somente `default`; nenhum ambiente alternativo foi presumido.

O operador pode disponibilizar uma VM/host de laboratório com Engine oficial,
AppArmor/seccomp ativos e acesso autenticado, criando um contexto `namira-lab`.
Após conferir esse contexto, os comandos abaixo usam exclusivamente o novo daemon:

```sh
# Na raiz do projeto; pressupõe contexto namira-lab já provisionado e conferido.
rtk proxy env DOCKER_CONTEXT=namira-lab docker build --network=none -f backend/Dockerfile.worker -t namira/worker:local backend
# Em backend/; usar o Python do ambiente virtual do projeto.
rtk proxy env DOCKER_CONTEXT=namira-lab PENTEST_DOCKER_IT=1 python3 -m unittest discover -s tests -p test_container_execution.py -v
```

São instruções para o ambiente futuro, não comandos já executados. O backend
herda o contexto do processo e não monta o socket no worker. Essa opção evita
migrar os workloads atuais. Se a preferência for substituir o Snap neste host,
é necessária autorização explícita para a migração, inventário/backup de dados
e planejamento de parada; nenhuma alteração administrativa foi aplicada.

O teste existente comprova o protocolo/operação quando passa, mas não verifica
sozinho todos os controles do kernel. Antes do aceite do isolamento real no novo
host, verificar também AppArmor/seccomp efetivos, usuário, capabilities, rede,
filesystem, limites e encerramento durante cancelamento. As verificações com
mocks desta consolidação não substituem essa evidência.
