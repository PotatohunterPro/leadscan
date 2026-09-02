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
SESSION_SECRET = os.environ.get("SESSION_SECRET", "").strip()
SESSION_COOKIE = "leadscan_session"
SESSION_MAX_AGE = 12 * 3600  # 12 horas
TOKEN_LOGIN_MAX_AGE = 5 * 60  # etapa de escolha de usuário do login (5 min)

# A1 (auditoria fix_final): SEM fallback de segredo conhecido. Se o deploy
# subir sem SESSION_SECRET, login e sessão ficam DESATIVADOS (fail-closed) —
# nenhum cookie é assinado, nenhuma sessão é aceita. O install.sh garante o
# segredo no .env antes de subir; os testes definem o seu próprio.
if not SESSION_SECRET:
    logger.error(
        "SESSION_SECRET não configurado no ambiente — login/sessão "
        "desativados (fail-closed). Configure SESSION_SECRET no .env "
        "antes de subir o serviço."
    )
    _serializer = None
else:
    _serializer = URLSafeTimedSerializer(SESSION_SECRET, salt="leadscan-admin")


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


def sessao_disponivel() -> bool:
    """True se SESSION_SECRET está configurado e sessões podem ser assinadas."""
    return _serializer is not None


def criar_cookie_valor(usuario: str | None = None) -> str:
    """Valor assinado a guardar no cookie de sessão.

    Sem usuário (fluxo antigo/install) o payload continua "admin" — V3
    (item 5.5) permite logar como um dos responsáveis; o papel NÃO vem do
    cookie (que o cliente controla), e sim do banco, na hora da requisição.

    Devolve "" (cookie inválido) quando SESSION_SECRET não está configurado
    (A1 — fail-closed): login nunca gera sessão nesse caso.
    """
    if _serializer is None:
        return ""
    return _serializer.dumps(f"u:{usuario}" if usuario else "admin")


def criar_token_login() -> str:
    """Token curto (5 min) que prova que a senha foi digitada correta.

    Usado no login em duas etapas (B16): a lista de usuários do time só é
    exibida DEPOIS de a senha correta ser digitada — nunca na página aberta.
    """
    if _serializer is None:
        return ""
    return _serializer.dumps("senha-ok", salt="leadscan-login")


def token_login_valido(token: str | None) -> bool:
    """True se o token de senha-verificada é válido e está dentro da validade."""
    if not token or _serializer is None:
        return False
    try:
        return _serializer.loads(token, salt="leadscan-login", max_age=TOKEN_LOGIN_MAX_AGE) == "senha-ok"
    except (BadSignature, SignatureExpired):
        return False


def _payload(valor: str | None) -> str | None:
    if not valor or _serializer is None:
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
