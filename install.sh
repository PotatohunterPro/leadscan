#!/usr/bin/env bash
# =============================================================================
#  LeadScan — instalação / atualização (idempotente) + bootstrap de VPS nova
#
#  Uso:  sudo bash install.sh
#  Após alterações:  git pull && sudo bash install.sh
#
#  Numa VPS limpa, instala o que faltar: git, Docker, plugin compose, Ollama,
#  modelo de visão, Nginx e Certbot. No final valida com chamadas HTTP reais
#  que /extract e /admin/login existem — nunca assume "container up" = "rota ok".
# =============================================================================
set -Eeuo pipefail

info() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[ OK ]\033[0m $*"; }
err()  { echo -e "\033[1;31m[ERR ]\033[0m $*" >&2; }

APT_UPDATED=0
apt_update() {
    if [ "$APT_UPDATED" = "0" ]; then
        apt-get update -qq
        APT_UPDATED=1
    fi
}

# roda de qualquer lugar, a partir do próprio diretório (o clone git)
cd "$(dirname "$0")"

# 1. Dependências (bootstrap: instala o que faltar)
command -v curl >/dev/null || { err "curl não encontrado. Instale antes de continuar."; exit 1; }

if ! command -v git >/dev/null; then
    info "Instalando git..."
    apt_update && apt-get install -y git
fi

if ! command -v docker >/dev/null; then
    info "Instalando Docker (script oficial)..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker 2>/dev/null || true
fi

if ! docker compose version >/dev/null 2>&1; then
    info "Instalando plugin docker compose..."
    apt_update
    if ! apt-get install -y docker-compose-plugin 2>/dev/null && ! apt-get install -y docker-compose-v2 2>/dev/null; then
        err "Não consegui instalar o plugin compose. Instale manualmente e rode de novo."
        exit 1
    fi
fi

# 2. Ollama e modelo
if ! command -v ollama >/dev/null; then
    info "Instalando Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    # garante que o binário recém-instalado esteja no PATH desta sessão
    export PATH="$PATH:/usr/local/bin"
fi

MODEL="hf.co/LiquidAI/LFM2.5-VL-450M-GGUF:Q8_0"
if ! ollama list | grep -q "$MODEL"; then
    info "Baixando modelo $MODEL (pode levar alguns minutos)..."
    ollama pull "$MODEL"
else
    ok "Modelo $MODEL já está instalado."
fi

# 3. .env
if [ ! -f .env ]; then
    cp .env.example .env
    info "Arquivo .env criado a partir do .env.example."
fi

# 3.1 Garantir que a senha do admin foi configurada (não subir com painel aberto)
if ! grep -qE "^ADMIN_PASSWORD_HASH=.+" .env; then
    err "ADMIN_PASSWORD_HASH não configurado no .env — gere um hash com:"
    err "  python3 -c \"import bcrypt; print(bcrypt.hashpw(b'SUA_SENHA', bcrypt.gensalt()).decode())\""
    err "e cole em .env antes de continuar. Abortando."
    exit 1
fi

# 3.2 Mesma coisa pro segredo da sessão (cookie assinado)
if ! grep -qE "^SESSION_SECRET=.+" .env; then
    err "SESSION_SECRET não configurado no .env — gere um com:"
    err "  openssl rand -hex 32"
    err "e cole em .env antes de continuar. Abortando."
    exit 1
fi

# 4. Subir os containers
info "Subindo containers..."
docker compose up -d --build

# 5. Esperar health
info "Aguardando serviço ficar saudável..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8000/health >/dev/null; then
        ok "Serviço saudável."
        break
    fi
    [ "$i" -eq 30 ] && { err "Serviço não respondeu ao /health a tempo."; docker compose logs --tail 50; exit 1; }
    sleep 2
done

# 6. Verificar que a rota principal está registrada (não assumir, testar de verdade)
info "Verificando rota /extract..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X GET http://127.0.0.1:8000/extract)
# esperado 405 (Method Not Allowed) pois /extract é POST-only — GET deve existir mas ser rejeitado
if [ "$HTTP_CODE" = "405" ] || [ "$HTTP_CODE" = "422" ]; then
    ok "Rota /extract registrada e ativa."
else
    err "Rota /extract não respondeu como esperado (HTTP $HTTP_CODE). Abortando."
    err "Veja os logs: docker compose logs leadscan --tail 50"
    exit 1
fi

# 7. Verificar que o painel admin está de pé (sem exigir login, só que a rota exista)
info "Verificando rota /admin/login..."
ADMIN_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/admin/login)
if [ "$ADMIN_CODE" = "200" ]; then
    ok "Painel admin acessível em /admin (login necessário)."
else
    err "Rota /admin/login não respondeu como esperado (HTTP $ADMIN_CODE)."
    exit 1
fi

# 8. Nginx (bootstrap) + configuração do site
if ! command -v nginx >/dev/null; then
    info "Instalando Nginx..."
    apt_update && apt-get install -y nginx
fi

if [ ! -f /etc/nginx/sites-available/hublead.conf ]; then
    info "Configurando site do Nginx..."
    cp nginx/hublead.conf /etc/nginx/sites-available/hublead.conf
    ln -sf /etc/nginx/sites-available/hublead.conf /etc/nginx/sites-enabled/hublead.conf
    systemctl enable nginx 2>/dev/null || true
    if nginx -t; then
        systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || true
        ok "Site Nginx configurado."
    else
        err "nginx -t falhou — confira /etc/nginx/ manualmente."
    fi
else
    ok "Nginx já configurado."
fi

# 9. Certificado SSL (se CERTBOT_EMAIL configurado no .env)
DOMAIN=$(grep "^DOMAIN=" .env | cut -d= -f2- | tr -d ' ')
CERTBOT_EMAIL=$(grep "^CERTBOT_EMAIL=" .env | cut -d= -f2- | tr -d ' ')
[ -n "$DOMAIN" ] || DOMAIN="hublead.pradodacostasolucoes.com.br"

if [ -n "$CERTBOT_EMAIL" ]; then
    if ! command -v certbot >/dev/null; then
        info "Instalando Certbot..."
        apt_update && apt-get install -y certbot python3-certbot-nginx
    fi
    if certbot certificates 2>/dev/null | grep -q "Domains:.*$DOMAIN"; then
        ok "Certificado para $DOMAIN já existe."
    else
        info "Emitindo certificado para $DOMAIN (o DNS precisa apontar pra este servidor)..."
        if certbot --nginx -d "$DOMAIN" -m "$CERTBOT_EMAIL" --agree-tos --non-interactive --redirect; then
            ok "HTTPS ativo em https://$DOMAIN"
        else
            err "Certbot falhou. Confira o registro DNS de $DOMAIN e rode depois:"
            err "  sudo certbot --nginx -d $DOMAIN"
        fi
    fi
else
    info "CERTBOT_EMAIL vazio no .env — pulei o HTTPS. Para ativar, rode:"
    info "  sudo certbot --nginx -d $DOMAIN"
fi

ok "=== leadscan instalado e verificado com sucesso ==="
if [ -n "$CERTBOT_EMAIL" ] && certbot certificates 2>/dev/null | grep -q "Domains:.*$DOMAIN"; then
    echo "Acesse: https://$DOMAIN"
else
    echo "Acesse: http://127.0.0.1:8000 (local) — configure o domínio para acesso público"
fi
