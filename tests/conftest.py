"""Configuração compartilhada dos testes (pytest).

Define um SESSION_SECRET de teste ANTES de qualquer import do app: com o
fix A1 (fail-closed), o app/auth.py recusa assinar sessões sem o segredo no
ambiente — os testes precisam de um segredo próprio (nunca o de produção).
"""

import os

os.environ.setdefault("SESSION_SECRET", "chave-de-teste-leadscan-nao-usar-em-producao")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _rate_limiter_limpo():
    """Zera o limitador por IP (M10) antes e depois de cada teste.

    O TestClient sempre se apresenta com o mesmo IP ("testclient") e os
    arquivos de teste rodam no mesmo processo — sem limpar, um arquivo
    esgotava a cota de outro e os POSTs viravam 429."""
    from app import main as main_mod

    main_mod._RATE_LIMIT.clear()
    yield
    main_mod._RATE_LIMIT.clear()
