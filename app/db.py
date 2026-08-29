"""
SQLite — arquivo único em data/leadscan.db. Sem serviço extra, sem ORM:
funções CRUD simples e um schema explícito com coluna para cada campo do
formulário de lead (mesmo modelo de dados do HubLead).
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("leadscan.db")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "leadscan.db"
FOTOS_DIR = DATA_DIR / "fotos"

# Colunas do lead (snake_case) — espelham o formulário completo, com as
# fotos e o timestamp. Ordem importa: é a ordem das colunas no CSV também.
CAMPOS = [
    "nome_empresa",
    "endereco",
    "cidade",
    "nome_contato",
    "cargo",
    "whatsapp",
    "aceita_demonstracao",
    "anotacoes",
    "telefone",
    "email",
    "ramo_atividade",
    "possui_sistema",
    "qual_sistema",
    "mensalidade",
    "suporte_bom",
    "trocaria_suporte",
    "trocaria_preco",
    "site",
    "redes_sociais",
    "foto_frente_path",
    "foto_verso_path",
]

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    {",\n    ".join(f"{c} TEXT NOT NULL DEFAULT ''" for c in CAMPOS)},
    criado_em TEXT NOT NULL
);
"""


def init_db() -> None:
    """Cria diretórios e tabela se ainda não existirem (idempotente)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FOTOS_DIR.mkdir(parents=True, exist_ok=True)
    with _conexao() as con:
        con.execute(_SCHEMA)
    logger.info("Banco pronto em %s", DB_PATH)


@contextmanager
def _conexao():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _para_dict(linha: sqlite3.Row) -> dict:
    return {chave: linha[chave] for chave in linha.keys()}


def salvar_lead(dados: dict) -> int:
    """Insere um lead. Campos desconhecidos são ignorados."""
    dados = {c: str(dados.get(c, "")).strip() for c in CAMPOS}
    with _conexao() as con:
        cur = con.execute(
            f"INSERT INTO leads ({', '.join(CAMPOS)}, criado_em) "
            f"VALUES ({', '.join('?' * (len(CAMPOS) + 1))})",
            [dados[c] for c in CAMPOS] + [agora_iso()],
        )
        return int(cur.lastrowid)


def atualizar_lead(lead_id: int, dados: dict) -> bool:
    """Atualiza apenas as colunas presentes em dados. False se não existir."""
    if not buscar_lead(lead_id):
        return False
    # atualiza qualquer coluna conhecida presente em dados (inclui fotos)
    colunas = [c for c in dados if c in CAMPOS]
    if not colunas:
        return True
    with _conexao() as con:
        con.execute(
            f"UPDATE leads SET {', '.join(f'{c} = ?' for c in colunas)} WHERE id = ?",
            [str(dados[c]).strip() for c in colunas] + [lead_id],
        )
    return True


def buscar_lead(lead_id: int) -> dict | None:
    with _conexao() as con:
        linha = con.execute(
            "SELECT * FROM leads WHERE id = ?", [lead_id]
        ).fetchone()
        return _para_dict(linha) if linha else None


def listar_leads(
    busca: str = "",
    de: str | None = None,
    ate: str | None = None,
    limite: int = 50,
) -> list[dict]:
    """Lista leads mais recentes primeiro, com busca e filtro por período.

    - busca: casa com nome_empresa, nome_contato ou whatsapp.
    - de/ate: datas ISO (YYYY-MM-DD) para filtrar por criado_em.
    """
    sql = "SELECT * FROM leads WHERE 1=1"
    params: list = []
    if busca:
        sql += " AND (nome_empresa LIKE ? OR nome_contato LIKE ? OR whatsapp LIKE ?)"
        like = f"%{busca}%"
        params += [like, like, like]
    if de:
        sql += " AND date(criado_em) >= ?"
        params.append(de)
    if ate:
        sql += " AND date(criado_em) <= ?"
        params.append(ate)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, int(limite)))
    with _conexao() as con:
        linhas = con.execute(sql, params).fetchall()
        return [_para_dict(l) for l in linhas]


def ultima_extracao_sucesso() -> str | None:
    """criado_em do lead mais recente — 'última vez que validei com foto real'."""
    with _conexao() as con:
        linha = con.execute(
            "SELECT criado_em FROM leads ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return linha["criado_em"] if linha else None


def total_leads() -> int:
    with _conexao() as con:
        return int(con.execute("SELECT COUNT(*) FROM leads").fetchone()[0])


def agora_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
