# ⏱️ TiqueTaque Sync Admin

> **Plataforma corporativa de notificações inteligentes de ponto, controle de jornada e assistente interativo no Slack ("TiqueTaque Ponto") integrada à API Pública de Administração do TiqueTaque.**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Multi--Arch-2496ED.svg?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-Ready-326CE5.svg?style=flat&logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![Slack](https://img.shields.io/badge/Slack-Block%20Kit-4A154B.svg?style=flat&logo=slack&logoColor=white)](https://api.slack.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/resendegu/tique-taque-sync-admin/actions/workflows/ci.yml/badge.svg)](https://github.com/resendegu/tique-taque-sync-admin/actions/workflows/ci.yml)
[![Docker](https://github.com/resendegu/tique-taque-sync-admin/actions/workflows/docker.yml/badge.svg)](https://github.com/resendegu/tique-taque-sync-admin/actions/workflows/docker.yml)
[![GHCR](https://img.shields.io/badge/ghcr.io-tique--taque--sync--admin-2496ED?logo=docker&logoColor=white)](https://github.com/resendegu/tique-taque-sync-admin/pkgs/container/tique-taque-sync-admin)

---

## 🎯 Por que o TiqueTaque Sync Admin?

Em empresas onde centenas ou milhares de funcionários registram ponto diariamente, esquecimentos de marcação de retorno de almoço ou saídas fora do horário causam passivos trabalhistas, retrabalho para o DP/RH e horas extras não planejadas.

O **TiqueTaque Sync Admin** conecta diretamente na **API Pública de Admin do TiqueTaque (v2.1)** e atua como uma ponte corporativa de notificações automáticas:

- 👥 **Sincronização em Lote de Colaboradores**: Importa e monitora automaticamente a lista de funcionários ativos da empresa.
- 🤖 **Slack Bot "TiqueTaque Ponto"**: Dispara mensagens diretas (DMs) personalizadas no Slack para cada colaborador com base no seu e-mail corporativo.
- 🔘 **Botões Interativos no Slack**: O colaborador pode ajustar seu tempo de aviso preferido (5 min, 10 min, 15 min antes) ou silenciar notificações diretamente pela mensagem.
- 🏢 **Governança & Controle de RH**:
  - Dashboard Web moderno (Glassmorphism dark theme) para a gestão da empresa.
  - **Opt-in / Opt-out por colaborador**: Ative ou desative notificações para quem não precisa (ex: estagiários, cargos de confiança ou diretores).
  - **Diretrizes da Empresa**: O RH decide se os funcionários podem alterar os tempos de alerta ou se devem seguir estritamente o padrão da empresa.
- 💾 **Backup Portátil em 1 Clique (JSON)**: Exporte todas as configurações e preferências dos colaboradores em JSON para salvar externamente ou restaurar a qualquer momento.
- ⚖️ **Conformidade CLT (Artigo 71)**: Alerta preventivo (10 min) e crítico (1 min) antes de qualquer colaborador atingir 6 horas contínuas de trabalho sem descanso.
- 📦 **Leve e Econômico**: Persistência local em SQLite WAL com volume inicial mínimo de 1Gi (expansível), de baixíssimo impacto e sem dependência de bancos pesados.

---

## 🏗️ Arquitetura da Solução

```mermaid
flowchart TD
    subgraph TiqueTaqueCloud["TiqueTaque Cloud"]
        TT_AdminAPI["API Pública de Admin (v2.1)\napi.tiquetaque.com/v2.1"]
    end

    subgraph SyncAdminService["TiqueTaque Sync Admin"]
        Poller["Poller em Lote (3 min)"]
        FastTicker["Fast Alert Ticker (15s)"]
        WorkdayEngine["Motor de Jornada Multi-Colaborador"]
        DB[(SQLite WAL - 1Gi PVC)]
        SlackBotService["Slack Bot ('TiqueTaque Ponto')"]
        WebDashboard["Dashboard Web Administrativo (RH)"]
    end

    subgraph SlackWorkspace["Workspace da Empresa (Slack)"]
        EmployeeDM["DM Direta ao Funcionário"]
        Buttons["Botões Interativos (5m, 10m, 15m, Mudo)"]
    end

    Poller -- "GET /employees & GET /times" --> TT_AdminAPI
    Poller --> WorkdayEngine
    FastTicker --> WorkdayEngine
    WorkdayEngine --> DB
    WorkdayEngine -- "Dispara Alertas" --> SlackBotService
    SlackBotService -- "chat.postMessage (DM)" --> EmployeeDM
    EmployeeDM -- "Clique em Botão" --> Buttons
    Buttons -- "POST /api/slack/interactions" --> WebDashboard
    WebDashboard <--> DB
```

---

## 🚀 Como Executar

### 1. Pré-requisitos
- Docker & Docker Compose **OU** Python 3.11+
- Token da API Pública do TiqueTaque (gerado em `Configurações > Integrações > API Pública` no painel admin da empresa).
- Um Slack App configurado no workspace da sua empresa (veja guia abaixo).

---

### 2. Configuração do `.env`
Copie o arquivo de exemplo e preencha suas chaves:

```bash
git clone https://github.com/resendegu/tique-taque-sync-admin.git
cd tique-taque-sync-admin
cp .env.example .env
```

Edite o arquivo `.env`:
```ini
# Token gerado no admin do TiqueTaque
TIQUETAQUE_ADMIN_TOKEN=seu-token-uuid-aqui

# Slack App
SLACK_ENABLED=true
SLACK_BOT_TOKEN=xoxb-seu-slack-bot-token
SLACK_SIGNING_SECRET=seu-slack-signing-secret

# Políticas Padrão da Empresa
ALLOW_EMPLOYEE_CUSTOMIZATION=true
DEFAULT_WARNING_ADVANCE_MINUTES=10
```

---

### 3. Rodando via Docker (Recomendado)

A imagem é publicada automaticamente pelo CI no **GitHub Packages**, multi-arquitetura
(`linux/amd64` e `linux/arm64` — roda em VM x86, Graviton/Ampere e Raspberry Pi):

```text
ghcr.io/resendegu/tique-taque-sync-admin:latest
```

**Em um comando, numa VM:**

```bash
docker run -d --name tique-taque-sync-admin --restart unless-stopped -p 8000:8000 -e TIQUETAQUE_ADMIN_TOKEN="seu-token-da-api-publica" -e SLACK_ENABLED=true -e SLACK_BOT_TOKEN="xoxb-..." -e SLACK_SIGNING_SECRET="..." -e ADMIN_SECRET_KEY="$(openssl rand -hex 32)" -v tiquetaque-admin-data:/app/data ghcr.io/resendegu/tique-taque-sync-admin:latest
```

**Ou com Docker Compose** (o `docker-compose.yml` já aponta para a imagem publicada,
então não é preciso clonar nem buildar):

```bash
docker compose up -d
```

Acesse o painel no navegador: **`http://localhost:8000`**

Para construir a partir do código-fonte (contribuindo com o projeto), descomente o bloco
`build:` do `docker-compose.yml` e rode `docker compose up -d --build`.

#### Tags disponíveis

| Tag | Quando usar |
| --- | ----------- |
| `latest` | Último commit da branch `main` |
| `1.2.3`, `1.2`, `1` | Versões publicadas — **recomendado fixar em produção** |
| `sha-abc1234` | Commit específico, para rastreabilidade |

Toda imagem carrega **atestado de proveniência** e SBOM:

```bash
gh attestation verify oci://ghcr.io/resendegu/tique-taque-sync-admin:latest --repo resendegu/tique-taque-sync-admin
```

---

### 4. Rodando Localmente com Python
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🤖 Como Configurar o Slack App ("TiqueTaque Ponto")

> 💡 **Dica Rápida:** Você também pode clicar no botão **"📖 Tutorial Slack Bot"** no topo da Dashboard Web do sistema. Ele gera o manifesto automaticamente com o domínio atual da sua aplicação e botão de cópia com 1 clique!

### Passo a Passo Manual

1. Acesse o portal de desenvolvedores do Slack: [api.slack.com/apps](https://api.slack.com/apps) e clique em **Create New App**.
2. Selecione a opção **"From an app manifest"** e escolha o Workspace da sua empresa.
3. Na aba **JSON**, substitua o conteúdo pelo manifesto abaixo (ajustando a URL de `request_url` para o domínio público onde o app está hospedado):

```json
{
  "display_information": {
    "name": "TiqueTaque Ponto",
    "description": "Assistente inteligente de jornada e alertas de ponto",
    "background_color": "#1e1b4b"
  },
  "features": {
    "bot_user": {
      "display_name": "TiqueTaque Ponto",
      "always_online": true
    }
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "chat:write",
        "users:read",
        "users:read.email",
        "im:write"
      ]
    }
  },
  "settings": {
    "interactivity": {
      "is_enabled": true,
      "request_url": "https://seu-dominio.com/api/slack/interactions"
    },
    "org_deploy_enabled": false,
    "socket_mode_enabled": false,
    "token_rotation_enabled": false
  }
}
```

> ⚠️ **Importante sobre as permissões:** O escopo `users:read` é obrigatório junto com `users:read.email` para que o bot consiga resolver o e-mail do colaborador cadastrado no TiqueTaque para o seu respectivo ID de usuário no Slack (`users.lookupByEmail`).

4. Clique em **Next** e depois em **Create**.
5. No menu lateral esquerdo, vá em **Install App** e clique em **Install to Workspace** (autorize as permissões solicitadas).
6. Copie as credenciais:
   * **Bot User OAuth Token** (começa com `xoxb-...`) em *OAuth & Permissions* ou *Install App*.
   * **Signing Secret** em *Basic Information* > *App Credentials*.
7. Configure as variáveis `SLACK_BOT_TOKEN` e `SLACK_SIGNING_SECRET` no seu arquivo `.env` (ou Secret do Kubernetes) e reinicie o serviço.

---

## 🛡️ Arquitetura de Segurança & Dual Ingress (Cloudflare Access)

Para ambientes corporativos que demandam **vazamento zero de dados de colaboradores** e integração aberta com o Slack, o projeto adota uma arquitetura de **Dual Ingress**:

```mermaid
flowchart TD
    subgraph Internet["Tráfego Externo"]
        RHUser["Equipe de RH / Gestão"]
        SlackServers["Servidores do Slack (Webhooks)"]
    end

    subgraph SecurityPerimeter["Perímetro de Segurança"]
        CFAccess["Cloudflare Access / Zero Trust (SSO / MFA)"]
        UI_Ingress["Ingress UI (ponto-admin.suaempresa.com.br)\nRotas: /* e /api/admin/*"]
        API_Ingress["Ingress API (ponto-api.suaempresa.com.br)\nRotas APENAS: /api/slack/* e /healthz"]
    end

    subgraph ClusterK8s["Cluster Kubernetes"]
        AppService["Service: tique-taque-sync-admin (Port 8000)"]
        FastAPIApp["FastAPI + Validações Criptográficas"]
    end

    RHUser -->|Protegido com MFA| CFAccess --> UI_Ingress --> AppService
    SlackServers -->|Requisições Webhook| API_Ingress --> AppService
    AppService --> FastAPIApp
```

### Por que dois domínios?
1. **`ponto-admin.suaempresa.com.br` (Frontend Ingress):**
   - Serve o Dashboard Web e os endpoints `/api/admin/*`.
   - **Deve ser colocado atrás do Cloudflare Access (Zero Trust)** com política de autenticação por e-mail corporativo (Google Workspace, Microsoft Entra ID / Azure AD, Okta ou PIN).
   - Impede que invasores ou robôs na internet visualizem a dashboard ou os nomes e batidas dos colaboradores.
   - O dashboard web emite um token assinado de sessão interna (`admin-token`) e bloqueia requisições `cross-site` maliciosas.

2. **`ponto-api.suaempresa.com.br` (Webhook Ingress):**
   - **Livre de Cloudflare Access**, permitindo que os servidores do Slack enviem os eventos de interação dos botões (`POST /api/slack/interactions`).
   - O Ingress expõe **estritamente** `/api/slack` e `/healthz`. Qualquer tentativa de acessar `/` ou `/api/admin` via este domínio é rejeitada com **HTTP 404** diretamente pelo Ingress (Traefik/Nginx), antes mesmo de atingir a aplicação.
   - Todas as requisições recebidas passam por **validação criptográfica HMAC-SHA256** (`X-Slack-Signature` e `X-Slack-Request-Timestamp` com janela anti-replay de 5 minutos).
   - O endpoint valida se o evento veio do `team.id` autorizado (`SLACK_ALLOWED_TEAM_ID`), rejeitando qualquer outro workspace do Slack.

---

### 🔒 Modo de Máxima Segurança: Zero Exposição Externa (Sem Ingress)

Para organizações com políticas rígidas de conformidade (SOC 2, ISO 27001, LGPD) que desejam **superfície zero de ataque na internet**:

1. **Defina a política corporativa fixa no ConfigMap:**
   ```yaml
   ALLOW_EMPLOYEE_CUSTOMIZATION: "false"
   ```
2. **O que acontece:**
   - As notificações enviadas no Slack tornam-se **100% informativas e em modo somente-leitura** (sem botões de alteração de minutos ou opt-out de silenciamento).
   - O Slack App no [api.slack.com](https://api.slack.com) mantém a opção **Interactivity desativada** (*Disabled*).
   - O bot opera exclusivamente por chamadas **outbound** (saída) para `https://slack.com/api/chat.postMessage` e para a API do TiqueTaque.
3. **Isolamento de Rede Total:**
   - **Nenhum Ingress precisa ser exposto!** Você não precisa aplicar o manifest `07-ingress.yaml`.
   - Nenhuma porta aberta de entrada no cluster ou firewall corporativo.
   - O acesso ao painel de gestão de RH é realizado de forma 100% interna e segura via `kubectl port-forward`:
     ```bash
     kubectl port-forward svc/tique-taque-sync-admin 8000:8000 -n tique-taque-sync-admin
     ```
     Basta acessar no navegador local: `http://localhost:8000`.

---

## ☸️ Deploy no Kubernetes

O projeto acompanha manifests prontos na pasta [`k8s/`](k8s/) com volume persistente de 1Gi (expansível):

```bash
# 1. Copie e edite o arquivo de segredos
cp k8s/03-secret.example.yaml k8s/03-secret.yaml
# Insira seu TIQUETAQUE_ADMIN_TOKEN, SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET e ADMIN_SECRET_KEY

# 2. Aplique com Kustomize
kubectl apply -k k8s/

# 3. Acompanhe a subida
kubectl -n tique-taque-sync-admin rollout status deploy/tique-taque-sync-admin
```

Os manifests já apontam para a imagem pública `ghcr.io/resendegu/tique-taque-sync-admin:latest`
— em produção, troque por uma versão fixa (ex: `:1.0.0`) no `05-deployment.yaml`.

> O `kustomization.yaml` referencia `03-secret.yaml`, que **não é versionado**. O passo 1
> acima não é opcional: sem ele o `kubectl apply -k` falha, em vez de subir silenciosamente
> com credenciais de exemplo.

Manifests inclusos:
- `01-namespace.yaml`: Namespace dedicado `tique-taque-sync-admin`.
- `02-configmap.yaml`: Configurações de horários, timezone e `SLACK_ALLOWED_TEAM_ID`.
- `03-secret.yaml`: Credenciais protegidas e chave mestra de administração (`ADMIN_SECRET_KEY`).
- `04-pvc.yaml`: Volume leve de 1Gi (`ReadWriteOnce`).
- `05-deployment.yaml`: Deployment multi-arch com health probes (`/healthz`).
- `06-service.yaml`: ClusterIP na porta 8000.
- `07-ingress.yaml`: Configuração pronta de Dual Ingress (UI restrita + API Slack aberta) com TLS / cert-manager.

---

## 📚 Endpoints da API REST

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Dashboard Web Administrativo |
| `GET` | `/api/admin/metrics` | Métricas gerais (total colaboradores, notificações ativas, online) |
| `GET` | `/api/admin/employees` | Lista de colaboradores, batidas de hoje e estágios |
| `POST` | `/api/admin/employees/{id}/toggle` | Ativa ou desativa notificações para um funcionário |
| `POST` | `/api/admin/employees/{id}/preferences` | Altera tempo de antecedência do colaborador |
| `POST` | `/api/admin/employees/{id}/test-slack` | Dispara mensagem de teste no Slack para o colaborador |
| `POST` | `/api/admin/sync` | Força sincronização imediata com o TiqueTaque |
| `GET` | `/api/admin/policy` | Consulta diretrizes de governança da empresa |
| `POST` | `/api/admin/policy` | Salva diretrizes de governança da empresa |
| `GET` | `/api/admin/backup/export` | Download do arquivo de backup JSON com todas as preferências |
| `POST` | `/api/admin/backup/import` | Restauração de preferências a partir de arquivo de backup JSON |
| `POST` | `/api/slack/interactions` | Webhook de recebimento de cliques nos botões do Slack |
| `GET` | `/healthz` | Probe de liveness/readiness para o Kubernetes |

---

## 🧪 Testes Automatizados

O repositório inclui suíte de testes unitários cobrindo o banco SQLite, cálculos de jornada, regras da CLT, geração de blocos do Slack e parser de interações:

```bash
python tests/run_tests.py
```

---

## 🔄 Integração Contínua & publicação da imagem

Três workflows em [`.github/workflows/`](.github/workflows/):

| Workflow | Dispara em | O que faz |
| -------- | ---------- | --------- |
| [`ci.yml`](.github/workflows/ci.yml) | push na `main`, PRs | Roda a suíte em Python 3.11/3.12/3.13; renderiza os manifests com `kubectl kustomize`; valida o `docker-compose.yml`; confere que o Deployment aponta para a imagem publicada e que nenhum valor com cara de credencial real ficou nos arquivos `.example` |
| [`docker.yml`](.github/workflows/docker.yml) | push na `main`, tags de versão, PRs | Builda, **sobe a imagem e a testa de verdade**, publica `linux/amd64` + `linux/arm64` em `ghcr.io/resendegu/tique-taque-sync-admin` com proveniência e SBOM e, quando o push é de tag, escreve as instruções de deploy na release (em PR, builda e testa sem publicar) |
| [`release.yml`](.github/workflows/release.yml) | release publicada (ou manual) | Cobre o caso da release publicada depois: espera o run do Docker daquele commit com `gh run watch` e então escreve as mesmas notas |

O teste da imagem no `docker.yml` não é simbólico: ele sobe o container, espera o
`HEALTHCHECK` ficar `healthy`, consulta `/healthz`, confere que o painel renderiza, que os
estáticos são servidos e que **`/api/admin/metrics` responde 403 sem credencial** — ou seja,
uma imagem que exponha o painel administrativo por engano não chega a ser publicada.

Para publicar uma versão:

```bash
git tag v1.2.3
git push origin v1.2.3
```

Isso gera as tags `1.2.3`, `1.2` e `1` no GHCR — note que o `v` **cai**: a tag do git
`v1.2.3` vira a imagem `ghcr.io/resendegu/tique-taque-sync-admin:1.2.3`. As notas da release
são escritas pelo próprio `docker.yml`, logo após o push da imagem, então elas citam a tag e o
digest que acabaram de ser publicados — sem adivinhação.

Se a release for publicada só depois, o `release.yml` assume: ele espera o build daquele
commit terminar (`gh run watch`) e escreve as mesmas notas. Os dois caminhos chamam o mesmo
[`scripts/release-notes.sh`](scripts/release-notes.sh).

O texto que você escrever à mão é preservado: o bloco gerado entra abaixo de um marcador e é
substituído, não duplicado, se o workflow rodar de novo.

> 📦 **Primeira publicação:** pacotes no GHCR nascem privados. Depois do primeiro build, abra
> o pacote em *Packages → tique-taque-sync-admin → Package settings* e mude a visibilidade
> para **Public** — só é preciso fazer isso uma vez.

---

## 🤖 Orientações para Agentes de IA

Consulte o arquivo [**`AGENTS.md`**](AGENTS.md) para detalhes técnicos aprofundados sobre a autenticação BasicAuth, formatos de payload e guardrails operacionais do sistema.

---

## 📄 Licença

Distribuído sob a licença **MIT**. Veja o arquivo [`LICENSE`](LICENSE) para mais detalhes.
