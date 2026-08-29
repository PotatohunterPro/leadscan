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


def criar_cookie_valor() -> str:
    """Valor assinado a guardar no cookie de sessão."""
    return _serializer.dumps("admin")


def cookie_valido(valor: str | None) -> bool:
    """True se o cookie existe, está assinado e dentro da validade."""
    if not valor:
        return False
    try:
        return _serializer.loads(valor, max_age=SESSION_MAX_AGE) == "admin"
    except (BadSignature, SignatureExpired):
        return False
