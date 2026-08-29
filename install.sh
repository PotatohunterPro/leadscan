#!/usr/bin/env bash
# =============================================================================
#  LeadScan — instalação / atualização (idempotente)
#
#  Uso:  sudo bash install.sh
#  Após alterações:  git pull && sudo bash install.sh
#
#  NUNCA assume que "container rodando" = "rota funcionando": no final,
#  valida com chamadas HTTP reais que /extract e /admin/login existem.
# =============================================================================
set -Eeuo pipefail

info() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[ OK ]\033[0m $*"; }
err()  { echo -e "\033[1;31m[ERR ]\033[0m $*" >&2; }

# roda de qualquer lugar, a partir do próprio diretório (o clone git)
cd "$(dirname "$0")"

# 1. Dependências
command -v docker >/dev/null || { err "docker não encontrado. Instale antes de continuar."; exit 1; }
docker compose version >/dev/null 2>&1 || { err "docker compose (plugin) não encontrado."; exit 1; }
command -v curl >/dev/null || { err "curl não encontrado (necessário p/ verificação pós-deploy)."; exit 1; }

# 2. Ollama e modelo
if ! command -v ollama >/dev/null; then
    info "Instalando Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    # garante que o binário recém-instalado esteja no PATH desta sessão
    export PATH="$PATH:/usr/local/bin"
fi

MODEL="hf.co/LiquidAI/LFM2.5-VL-450M-GGUF:Q8_0"
if ! ollama list | grep -q "$MODEL"; then
    info "Baixando modelo $MODEL..."
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

ok "=== leadscan instalado e verificado com sucesso ==="
echo "Acesse: http://$(hostname -I | awk '{print $1}'):8000  (ou configure um proxy reverso/domínio)"
