"""
Autenticação do painel admin — senha única (bcrypt no .env) + cookie de
sessão assinado (itsdangerous). Não é multiusuário: uma senha só.
"""

import logging
import os

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

logger = logging.getLogger("leadscan.auth")

ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
SESSION_COOKIE = "leadscan_session"
SESSION_MAX_AGE = 12 * 3600  # 12 horas

# Em dev local sem SESSION_SECRET ainda assina (com aviso); em produção o
# install.sh garante que o segredo está configurado antes de subir.
_serializer = URLSafeTimedSerializer(
    SESSION_SECRET or "dev-secret-nao-usar-em-producao",
    salt="leadscan-admin",
)


def senha_confere(senha: str) -> bool:
    """Confere a senha digitada contra o hash bcrypt do .env."""
    if not ADMIN_PASSWORD_HASH:
        logger.warning(
            "ADMIN_PASSWORD_HASH não configurado no .env — login negado."
        )
        return False
    try:
        return bcrypt.checkpw(
            senha.encode("utf-8"), ADMIN_PASSWORD_HASH.encode("utf-8")
        )
    except ValueError:
        logger.error("ADMIN_PASSWORD_HASH inválido no .env — corrija o hash.")
        return False


def criar_cookie_valor(usuario: str | None = None) -> str:
    """Valor assinado a guardar no cookie de sessão.

    Sem usuário (fluxo antigo/install) o payload continua "admin" — V3
    (item 5.5) permite logar como um dos responsáveis; o papel NÃO vem do
    cookie (que o cliente controla), e sim do banco, na hora da requisição.
    """
    return _serializer.dumps(f"u:{usuario}" if usuario else "admin")


def _payload(valor: str | None) -> str | None:
    if not valor:
        return None
    try:
        return _serializer.loads(valor, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def cookie_valido(valor: str | None) -> bool:
    """True se o cookie existe, está assinado e dentro da validade."""
    payload = _payload(valor)
    return payload == "admin" or (isinstance(payload, str) and payload.startswith("u:"))


def usuario_da_sessao(request) -> str | None:
    """Nome do usuário logado (None na sessão 'admin' antiga = gestor)."""
    payload = _payload(request.cookies.get(SESSION_COOKIE))
    if isinstance(payload, str) and payload.startswith("u:"):
        return payload[2:] or None
    return None
