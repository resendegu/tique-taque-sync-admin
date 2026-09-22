#!/usr/bin/env bash
#
# Escreve as instruções de deploy no corpo de uma release do GitHub.
#
# Usado por dois caminhos:
#   - .github/workflows/docker.yml  -> logo após publicar a imagem (caso normal)
#   - .github/workflows/release.yml -> quando a release é publicada depois
#
# Variáveis esperadas:
#   TAG        tag do git             (ex: v1.2.3 ou 1.2.3)
#   REPO       owner/nome             (ex: resendegu/tique-taque-sync-admin)
#   IMAGE_TAG  tag DA IMAGEM          (ex: 1.2.3 — sem o "v", como a metadata-action gera)
#   DIGEST     digest da imagem       (opcional)
#   PLATFORMS  lista de plataformas   (opcional)
#   GH_TOKEN   token com permissão de escrita em contents
#
set -euo pipefail

: "${TAG:?informe TAG}"
: "${REPO:?informe REPO}"
: "${IMAGE_TAG:?informe IMAGE_TAG}"

IMAGE="ghcr.io/${REPO}"
MARKER="<!-- gerado automaticamente pelo workflow Release -->"
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

if ! gh release view "$TAG" >/dev/null 2>&1; then
  echo "Nenhuma release publicada para a tag ${TAG} ainda — nada a escrever."
  echo "As notas serão preenchidas quando a release for publicada."
  exit 0
fi

# Placeholders em vez de expansão dentro do heredoc: assim o Markdown pode
# conter crases e cifrões sem o shell tentar interpretá-los.
cat > "$WORKDIR/generated.md" <<'TEMPLATE'
__MARKER__

## 🐳 Subir com Docker

```bash
docker run -d --name tique-taque-sync-admin --restart unless-stopped \
  -p 8000:8000 \
  -e TIQUETAQUE_ADMIN_TOKEN="seu-token-da-api-publica" \
  -e SLACK_ENABLED=true \
  -e SLACK_BOT_TOKEN="xoxb-..." \
  -e SLACK_SIGNING_SECRET="..." \
  -e ADMIN_SECRET_KEY="$(openssl rand -hex 32)" \
  -v tiquetaque-admin-data:/app/data \
  __IMAGE__:__IMAGE_TAG__
```

Painel administrativo em `http://localhost:8000`.

Com Docker Compose, baixe o `docker-compose.yml` e o `.env.example` desta versão:

```bash
curl -O https://raw.githubusercontent.com/__REPO__/__TAG__/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/__REPO__/__TAG__/.env.example
# edite o .env com seu token do TiqueTaque e as credenciais do Slack
docker compose up -d
```

## ☸️ Subir no Kubernetes

```bash
git clone --branch __TAG__ https://github.com/__REPO__.git
cd tique-taque-sync-admin

cp k8s/03-secret.example.yaml k8s/03-secret.yaml
# preencha TIQUETAQUE_ADMIN_TOKEN, SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET e ADMIN_SECRET_KEY

kubectl apply -k k8s/
kubectl -n tique-taque-sync-admin rollout status deploy/tique-taque-sync-admin
```

Para fixar esta versão no cluster, troque a imagem do `05-deployment.yaml` por
`__IMAGE__:__IMAGE_TAG__`.

> ⚠️ O painel `/` e as rotas `/api/admin/*` são internos. Se expuser pelo Ingress,
> proteja-os (Cloudflare Access, oauth2-proxy, VPN). O único endpoint que precisa
> ficar acessível ao mundo é `/api/slack/interactions`, e ele valida a assinatura
> do Slack. Veja o Dual Ingress no README.

## 📦 Imagem

| | |
|---|---|
| Imagem | `__IMAGE__:__IMAGE_TAG__` |
| Plataformas | __PLATFORMS__ |
| Digest | `__DIGEST__` |

Verificar a procedência:

```bash
gh attestation verify oci://__IMAGE__:__IMAGE_TAG__ --repo __REPO__
```
TEMPLATE

sed -i \
  -e "s|__MARKER__|${MARKER}|g" \
  -e "s|__IMAGE__|${IMAGE}|g" \
  -e "s|__IMAGE_TAG__|${IMAGE_TAG}|g" \
  -e "s|__TAG__|${TAG}|g" \
  -e "s|__REPO__|${REPO}|g" \
  -e "s|__PLATFORMS__|${PLATFORMS:-linux/amd64, linux/arm64}|g" \
  -e "s|__DIGEST__|${DIGEST:-consulte o workflow Docker}|g" \
  "$WORKDIR/generated.md"

{
  printf '\n## 📝 Último commit (%s)\n\n' "$(git rev-parse --short HEAD)"
  printf '```text\n'
  # A substituição de comando já descarta as quebras de linha do fim.
  printf '%s\n' "$(git log -1 --pretty=%B)"
  printf '```\n'
} >> "$WORKDIR/generated.md"

# Preserva o que a pessoa escreveu à mão: o bloco gerado fica abaixo do marcador
# e é substituído, não duplicado, se o workflow rodar de novo.
gh release view "$TAG" --json body --jq .body > "$WORKDIR/existing.md" || : > "$WORKDIR/existing.md"
if grep -qF "$MARKER" "$WORKDIR/existing.md"; then
  escaped=$(printf '%s' "$MARKER" | sed 's/[][\.*^$/]/\\&/g')
  sed -i "/${escaped}/,\$d" "$WORKDIR/existing.md"
fi

{
  cat "$WORKDIR/existing.md"
  printf '\n'
  cat "$WORKDIR/generated.md"
} > "$WORKDIR/release-notes.md"

gh release edit "$TAG" --notes-file "$WORKDIR/release-notes.md"
echo "Notas da release ${TAG} atualizadas (imagem ${IMAGE}:${IMAGE_TAG})."
