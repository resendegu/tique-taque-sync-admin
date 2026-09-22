# 🤖 AGENTS.md — AI Context, Operational Guidelines & System Truth

> **Aviso para Agentes de IA (Claude, Antigravity, Copilot, Cursor, OpenAI, etc.):**  
> Este documento é a **Fonte Única da Verdade (Single Source of Truth - SSOT)** sobre a arquitetura corporativa, integração com a API Pública de Admin do TiqueTaque (v2.1), o bot interativo do Slack ("TiqueTaque Ponto") e as regras de governança deste repositório (`tique-taque-sync-admin`). Leia atentamente antes de refatorar código ou sugerir alterações.

> ### ⚠️ Antes de encerrar qualquer alteração de comportamento
>
> **Suba `[project].version` no `pyproject.toml`.** Aquela linha é o gatilho da release: se
> ela não mudar, nenhuma versão é publicada e a correção não chega a quem faz `docker pull`.
> MAJOR quebra compatibilidade, MINOR adiciona função compatível, PATCH corrige mantendo
> compatibilidade — detalhes e casos de dúvida na seção 7.

---

## 🎯 1. Escopo & Filosofia do Projeto

O **`tique-taque-sync-admin`** é uma solução corporativa open-source voltada para empresas que utilizam o ponto eletrônico **TiqueTaque**.  
Diferente da versão mono-usuário, o foco deste projeto é:
1. **Atender a base inteira de colaboradores da empresa**.
2. **Monitorar batidas em tempo real via API Pública de Admin (v2.1)**.
3. **Disparar notificações ativas e personalizadas no Slack** de um bot oficial chamado **"TiqueTaque Ponto"**.
4. **Permitir controle e governança de RH/Gestão** através de um Dashboard Web administrativo, onde colaboradores podem ser ativados/desativados (ex: estagiários ou dispensados de ponto) e as políticas de customização podem ser delimitadas.
5. **Backup portátil das configurações**: O banco SQLite de baixo impacto (iniciado com 1Gi expansível) pode ser exportado para JSON a qualquer momento.

---

## 🏗️ 2. Arquitetura de Módulos

```text
src/
├── config.py               # Pydantic Settings (.env, token público de admin, tokens do Slack)
├── main.py                 # FastAPI app, endpoints administrativos, webhook de interações do Slack e probes
├── tiquetaque/
│   ├── client.py           # Cliente assíncrono para a API Pública de Admin v2.1
│   └── models.py           # Modelos Pydantic (AdminEmployee, TimeRecord, EmployeeTimesResponse)
├── database/
│   └── db.py               # SQLite WAL (Employees, Company Settings, DispatchedAlerts, Backup JSON)
├── engine/
│   ├── workday.py          # Máquina de estados (5 estágios, previsões e guardião do Art. 71 da CLT)
│   └── scheduler.py        # Loop duplo: Poller em lote (3m) + Ticker local rápido (15s)
├── slack/
│   ├── bot.py              # Slack Bot (lookupByEmail, conversations.open e chat.postMessage DM)
│   ├── blocks.py           # Templates Block Kit interativos ("TiqueTaque Ponto")
│   └── interactions.py     # Parser de ações de clique (ajuste de minutos e silenciamento)
└── web/
    ├── templates/index.html # Dashboard Web Administrativo em Dark Glassmorphism
    └── static/             # CSS e JavaScript de gestão ao vivo e upload/download de backup
```

---

## 🔬 3. Engenharia e Verdades da API Pública do TiqueTaque (v2.1)

A API pública oficial de administração está documentada em `https://api-docs.tiquetaque.app/openapi`:

### 3.1. Autenticação (HTTP BasicAuth)
* **Host de Produção**: `https://api.tiquetaque.com/v2.1`
* **Esquema de Autenticação**: HTTP BasicAuth estrito.
  * O nome de usuário deve ser **sempre** a string fixa: `public`.
  * A senha deve ser o **Token de API** gerado no painel de administração (`Configurações > Integrações > API Pública`).
  * Header HTTP gerado:
    ```http
    Authorization: Basic base64("public:<api_token>")
    ```

### 3.2. Listagem de Funcionários Ativos
* **Endpoint**: `GET /v2.1/employees`
* **Retorno**: Lista de objetos em `_items` com `_id`, `full_name`, `email`, `timezone`, `work_schedule` e permissões contratuais.

### 3.3. Consulta de Batidas de Ponto
* **Endpoint**: `GET /v2.1/times`
* **Query Parameters Obrigatórios**:
  - `employee_id`: ID de 24 caracteres hex do funcionário.
  - `start_date`: Data de início no formato `YYYY-MM-DD`.
  - `end_date`: Data de término no formato `YYYY-MM-DD`.
* **Retorno**: Objeto contendo `times: list` com `time` em formato ISO (ex: `"2026-09-21T14:51"`).

---

## 💬 4. Bot do Slack ("TiqueTaque Ponto") & Interatividade

1. **Resolução de Usuário**:
   - O e-mail do colaborador cadastrado no TiqueTaque é consultado no Slack via `users.lookupByEmail`.
   - O `slack_user_id` retornado (ex: `U12345678`) é salvo em cache no SQLite para evitar chamadas redundantes.
2. **Escopos Obrigatórios do Bot (Bot Token Scopes)**:
   - `chat:write`: Permite enviar mensagens no canal de DM do funcionário.
   - `users:read`: Permite listar e consultar detalhes dos usuários do workspace.
   - `users:read.email`: Permite pesquisar o funcionário pelo e-mail (`users.lookupByEmail`).
   - `im:write`: Permite abrir conversas diretas com o funcionário (`conversations.open`).
3. **Entrega via Mensagem Direta (DM)**:
   - Uma conversa direta é aberta via `conversations.open` e a notificação é postada via `chat.postMessage`.
4. **Governança & Botões Interativos**:
   - Se a política da empresa permitir (`allow_employee_customization = true`), as mensagens incluem botões para o colaborador escolher com quantos minutos quer ser avisado (5 min, 10 min, 15 min) ou silenciar seus alertas.
   - Os cliques chegam no webhook `POST /api/slack/interactions` e atualizam a preferência no banco SQLite em tempo real.
   - Se `allow_employee_customization = false`, os botões são suprimidos e os prazos padrão da empresa são impostos.

---

## ⚖️ 5. Regras CLT & Máquina de Estados da Jornada

O motor avalia as batidas de cada colaborador e dispara alertas nos seguintes momentos:
* **Almoço (1h)**: Aviso preventivo (5-15 min antes conforme preferência) e aviso final 1 min antes.
* **Fim de Expediente (8h)**: Aviso preventivo e aviso final 1 min antes da saída calculada.
* **Artigo 71 da CLT**: Alerta preventivo 10 min antes e crítico 1 min antes de completar 6 horas de trabalho ininterrupto sem pausa.
* **Resumo do Dia**: Enviado assim que a 4ª batida (ou encerramento) for detectada.

---

## 🛡️ 6. Arquitetura de Segurança & Isolamento Dual Ingress

1. **Dual Ingress Pattern**:
   - **Frontend / Admin Ingress (`ponto-admin...`)**: Serve o dashboard e `/api/admin/*`. Deve ser protegido por Cloudflare Access (SSO/MFA). O browser consome a API através de um token assinado de sessão HMAC-SHA256 gerado no template (`admin_session` cookie / `meta[name="admin-token"]`), com bloqueio estrito de requisições cross-site.
   - **Webhook Ingress (`ponto-api...`)**: Aberto para a internet, expondo estritamente `/api/slack/*` e `/healthz`. Rejeita qualquer tentativa de acesso a `/` ou `/api/admin/*` com HTTP 404 antes de chegar à aplicação.
2. **Validação Criptográfica do Slack**:
   - Toda requisição no webhook `/api/slack/interactions` valida a assinatura `v0=HMAC_SHA256(SLACK_SIGNING_SECRET, "v0:" + timestamp + ":" + raw_body)`.
   - Janela máxima de 300 segundos contra ataques de replay.
   - O payload decodificado valida se `payload.team.id` corresponde a `SLACK_ALLOWED_TEAM_ID`.
3. **Proteção contra Vazamento de Dados de Funcionários**:
   - Todas as rotas `/api/admin/*` exigem autenticação via token de sessão interno ou header `X-Admin-Key` / Bearer token com `ADMIN_SECRET_KEY`. Requisições diretas não autenticadas recebem HTTP 403 Forbidden.
4. **Modo Zero Exposição Externa (Air-Gapped / Zero-Ingress)**:
   - Quando `allow_employee_customization = False`, as mensagens do Slack são geradas em modo somente-leitura, sem botões de ação ou opt-out.
   - O Slack App mantém a opção de Interatividade desativada.
   - Todo o tráfego do bot e do TiqueTaque é **estritamente outbound** (pod -> Internet).
   - Nenhuma porta de entrada ou Ingress precisa ser exposto (`07-ingress.yaml` não é aplicado). A gestão corporativa acessa o painel de forma segura via `kubectl port-forward svc/tique-taque-sync-admin 8000:8000`.

---

## 🔖 7. Versionamento: a linha que dispara a release

**Toda alteração de comportamento sobe a versão em `[project].version` do `pyproject.toml`.**
Aquela linha é o gatilho da release: quando ela muda num push para a `main`, o CI cria a tag
`vX.Y.Z`, publica a imagem com as tags `X.Y.Z`, `X.Y` e `X`, abre a release no GitHub e
escreve as instruções de deploy. Se a linha não muda, o commit só atualiza `latest` e
`sha-<commit>` — nenhuma versão é publicada.

### Qual casa incrementar (SemVer)

O critério é **compatibilidade**, não tamanho nem urgência da mudança:

| Incremento | Quando | Exemplos neste projeto |
|---|---|---|
| **MAJOR** — `2.4.1` → `3.0.0` | Quebra compatibilidade: quem atualizar precisa mudar algo | Renomear/remover variável de ambiente, mudar formato do `config.json`, remover rota da API, exigir migração de banco |
| **MINOR** — `2.4.1` → `2.5.0` | Funcionalidade nova, compatível com quem já usa | Novo canal de notificação, nova rota `/api/admin/*`, novo botão no Slack, nova variável de ambiente **opcional** |
| **PATCH** — `2.4.1` → `2.4.2` | Correção compatível | Bug no cálculo da jornada, alerta disparando na hora errada, correção de segurança que não muda a interface, ajuste de layout |

Ao subir MAJOR ou MINOR, zere as casas à direita: depois de `2.4.7`, um MINOR vira `2.5.0`
(não `2.5.7`), e um MAJOR vira `3.0.0`.

Dois detalhes que costumam gerar dúvida:

1. **Correção de segurança não é automaticamente MAJOR nem MINOR.** Se ela não quebra nada e
   não adiciona função, é PATCH — por mais grave que seja. O que muda a casa é a
   compatibilidade, não a gravidade. (Comunique a gravidade no texto da release, não no
   número.)
2. **MINOR é para funcionalidade nova, não para "correção maior".** Um bug difícil, que levou
   três dias e mexeu em meio motor, continua sendo PATCH se a interface não mudou.

Pré-lançamentos usam `X.Y.Z-rc.N` (ex: `2.5.0-rc.1`): a release sai marcada como
*pre-release* e as tags móveis `X.Y` e `X` **não** são movidas para ela.

### Checklist ao fechar uma alteração

1. O comportamento mudou para quem usa? Então suba a versão no `pyproject.toml`.
2. Escolha a casa pela tabela acima.
3. Commit e push na `main` — o resto é automático.
4. Não crie a tag à mão: o CI cria `vX.Y.Z` a partir da versão. Tag manual é caminho de
   exceção (e é tratada pelo job `release-notes`).

---

## 📦 8. CI/CD e publicação da imagem

O artefato deste projeto é **a imagem de container**, não um pacote instalável: o alvo é
Kubernetes ou uma VM com Docker.

| Workflow | Dispara | Responsabilidade |
|---|---|---|
| `ci.yml` | push `main`, PR | Testes em Python 3.11/3.12/3.13; `kubectl kustomize` dos manifests; `docker compose config`; checagem de que o Deployment aponta para a imagem publicada e de que não há credencial real nos `.example` |
| `docker.yml` | push `main`, tag de versão, PR | Build amd64 carregado localmente → **teste real do container** → build multi-arch (amd64 + arm64) e push para `ghcr.io/resendegu/tique-taque-sync-admin`, com proveniência e SBOM. Em push de tag, o job `release-notes` (`needs: build`) escreve as notas da release |
| `release.yml` | `release: published`, manual | Caso da release publicada depois do build: espera o run do Docker com `gh run watch` e chama o mesmo `scripts/release-notes.sh` |

Regras:

1. **A imagem é pública e usada por terceiros.** Nada nela pode exigir configuração manual
   pós-`docker run`. Os defaults de container vivem como `ENV` no Dockerfile
   (`HOST`, `PORT`, `DATA_DIR`).
2. **O `CMD` precisa respeitar `HOST`/`PORT`.** Ele é forma shell com `exec` — mantém o
   uvicorn como PID 1 (recebe o `SIGTERM` do Kubernetes) *e* expande as variáveis. Um `CMD`
   com porta fixa faz o `PORT` do ConfigMap virar mentira.
3. **O teste da imagem no `docker.yml` inclui uma asserção de segurança:**
   `/api/admin/metrics` tem que responder **403 sem credencial**. Se alguém afrouxar o
   `verify_admin_access`, a imagem não é publicada. Não remova essa checagem.
4. **Não quebre o arm64.** O build roda em QEMU sobre runner amd64; dependência que exija
   compilação nativa pesada estoura o tempo do job.
5. **Tags:** `latest` só sai da branch default; versões vêm de tags `vX.Y.Z`; `sha-<short>`
   sempre. Em PR builda e testa, mas não publica — nenhum segredo de registry vai para fork.
6. **Nunca colocar credencial real em default de código ou em arquivo `.example`.** O
   `tiquetaque_admin_token` tem default vazio de propósito; o `ci.yml` falha se aparecer algo
   com formato de UUID ou de token `xoxb-` nesses arquivos.
7. **Tag do git ≠ tag da imagem.** A `metadata-action` remove o `v`: a tag `v1.2.3` publica
   `ghcr.io/…:1.2.3`. Qualquer texto que mande alguém dar `docker pull`/`docker run` precisa
   usar a tag da IMAGEM (`needs.build.outputs.version`, ou `${TAG#v}`), enquanto `git clone
   --branch` e URLs do `raw.githubusercontent.com` usam a tag do GIT. Misturar as duas gera
   instrução que falha com `manifest unknown`.
8. **O filtro de tags aceita `v1.2.3` e `1.2.3`.** Um filtro só com `v*` faz tags sem prefixo
   passarem batido e a imagem nunca ganhar versão — só `latest` e `sha-*`.
9. **Uma tag empurrada com o `GITHUB_TOKEN` não dispara outros workflows.** O GitHub
   bloqueia isso para evitar recursão. Por isso build, tag, release e notas acontecem no
   mesmo run do `docker.yml`, em vez de workflows encadeados por evento de tag. Se algum dia
   precisar encadear de verdade, será preciso um PAT em segredo — não tente com o token
   padrão, porque falha em silêncio.
10. **As notas da release saem do `docker.yml`, não de um poller.** Sondar o registry até a
   imagem aparecer é lento e cego (não distingue "ainda não publicou" de "tag errada"). O
   digest e a tag vêm dos outputs do job de build.

---

## 🔒 9. Guardrails para Agentes de IA

1. **Volume Mínimo & Eficiência**: Começar sempre com volume leve (1Gi) no `04-pvc.yaml`. O SQLite WAL de metadados administrativos não armazena arquivos pesados, apenas configurações e logs.
2. **Preservação de Escolhas dos Colaboradores no Poller**: Ao re-sincronizar a lista de funcionários da API do TiqueTaque, **nunca sobrescreva** os campos `notifications_enabled`, `lunch_warning_advance_minutes` ou `slack_user_id` já customizados no banco.
3. **Formatação Slack Block Kit**: Utilize blocos estruturados e mrkdwn. Lembre-se que o Slack rejeita tags HTML como `<b>` ou `<i>`.
4. **Isolamento de Credenciais**: Nunca commite credenciais reais (tokens, senhas, chaves) no repositório open-source `tique-taque-sync-admin`. Credenciais de produção pertencem exclusivamente aos manifests do repositório privado (`resende-context/trabalho-admin`).
5. **Cobertura de Testes**: Mantenha 100% dos testes unitários passando em `python tests/run_tests.py`.

