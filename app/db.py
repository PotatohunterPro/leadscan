"""
SQLite — arquivo único em data/leadscan.db. Sem serviço extra, sem ORM:
funções CRUD simples e um schema explícito com coluna para cada campo do
formulário de lead (mesmo modelo de dados do HubLead).
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("leadscan.db")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "leadscan.db"
FOTOS_DIR = DATA_DIR / "fotos"

# Colunas que podem ser expostas na API pública (UI de captura). Fica fora
# daqui todo dado sensível de qualificação de vendas (anotações, possui_sistema,
# mensalidade, trocaria_*, caminhos de foto etc.) — só no painel autenticado.
COLUNAS_PUBLICAS = [
    "id",
    "criado_em",
    "nome_empresa",
    "nome_contato",
    "whatsapp",
    "endereco",
    "cidade",
]

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

# Informações do cartão: tabela SEPARADA, 1 por lead (lead_id UNIQUE).
# O lead continua sendo UM registro só — o cartão é uma camada complementar,
# nunca um segundo lead. Guardamos o JSON completo da análise (telefones,
# redes, endereço, outras informações) + o texto do OCR bruto, para conferência.
_SCHEMA_CARTAO = """
CREATE TABLE IF NOT EXISTS lead_cartao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL UNIQUE,
    dados_json TEXT NOT NULL DEFAULT '{}',
    ocr_texto TEXT NOT NULL DEFAULT '',
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
"""


def init_db() -> None:
    """Cria diretórios e tabelas se ainda não existirem (idempotente).

    Também roda a migração das colunas de 'leads': bancos antigos ganham as
    colunas novas com ALTER TABLE — nenhum dado é apagado ou reescrito.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FOTOS_DIR.mkdir(parents=True, exist_ok=True)
    with _conexao() as con:
        con.execute(_SCHEMA)
        con.execute(_SCHEMA_CARTAO)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_lead_cartao_lead ON lead_cartao(lead_id)"
        )
        _migrar_colunas(con)
    logger.info("Banco pronto em %s", DB_PATH)


def _migrar_colunas(con: sqlite3.Connection) -> None:
    """Adiciona a 'leads' colunas de CAMPOS que ainda não existem."""
    existentes = {
        linha["name"] for linha in con.execute("PRAGMA table_info(leads)").fetchall()
    }
    for coluna in CAMPOS:
        if coluna not in existentes:
            logger.info("Migração: adicionando coluna %s em leads", coluna)
            con.execute(
                f"ALTER TABLE leads ADD COLUMN {coluna} TEXT NOT NULL DEFAULT ''"
            )


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


def listar_leads_publico(limite: int = 20) -> list[dict]:
    """Últimos leads, apenas colunas públicas (sem dados sensíveis)."""
    limite = max(1, min(int(limite), 100))
    with _conexao() as con:
        linhas = con.execute(
            f"SELECT {', '.join(COLUNAS_PUBLICAS)} FROM leads "
            "ORDER BY id DESC LIMIT ?",
            [limite],
        ).fetchall()
        return [_para_dict(l) for l in linhas]


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


# ------------------------------------------------------- informações do cartão

def salvar_cartao(lead_id: int, info: dict) -> int:
    """Grava (ou atualiza) as INFORMAÇÕES DO CARTÃO de um lead.

    Não toca em nenhuma coluna de 'leads': o que o vendedor digitou continua
    exatamente como estava. Se já existir cartão para o lead, ele é
    substituído pela análise nova (continua sendo 1 cartão por lead).
    """
    if not info:
        return 0
    payload = json.dumps(info, ensure_ascii=False)
    ocr_texto = str((info.get("ocr") or {}).get("texto", ""))
    agora = agora_iso()
    with _conexao() as con:
        linha = con.execute(
            "SELECT id FROM lead_cartao WHERE lead_id = ?", [lead_id]
        ).fetchone()
        if linha:
            con.execute(
                "UPDATE lead_cartao SET dados_json = ?, ocr_texto = ?, "
                "atualizado_em = ? WHERE lead_id = ?",
                [payload, ocr_texto, agora, lead_id],
            )
            return int(linha["id"])
        cur = con.execute(
            "INSERT INTO lead_cartao (lead_id, dados_json, ocr_texto, "
            "criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?)",
            [lead_id, payload, ocr_texto, agora, agora],
        )
        return int(cur.lastrowid)


def buscar_cartao(lead_id: int) -> dict | None:
    """Informações do cartão do lead (None se o lead não tiver cartão)."""
    with _conexao() as con:
        linha = con.execute(
            "SELECT * FROM lead_cartao WHERE lead_id = ?", [lead_id]
        ).fetchone()
    if not linha:
        return None
    try:
        dados = json.loads(linha["dados_json"] or "{}")
    except json.JSONDecodeError:
        logger.warning("JSON do cartão do lead %s corrompido", lead_id)
        dados = {}
    if not isinstance(dados, dict):
        dados = {}
    dados.setdefault("ocr", {})
    if not dados["ocr"].get("texto"):
        dados["ocr"]["texto"] = linha["ocr_texto"] or ""
    dados["_meta"] = {
        "id": linha["id"],
        "lead_id": linha["lead_id"],
        "criado_em": linha["criado_em"],
        "atualizado_em": linha["atualizado_em"],
    }
    return dados


def buscar_lead_completo(lead_id: int) -> dict | None:
    """Lead + cartão no MESMO registro de resposta (chave 'cartao')."""
    lead = buscar_lead(lead_id)
    if lead is None:
        return None
    lead["cartao"] = buscar_cartao(lead_id)
    return lead


def leads_com_cartao(ids: list[int]) -> dict[int, dict]:
    """Cartões de vários leads de uma vez (usado no painel/CSV)."""
    if not ids:
        return {}
    marcadores = ",".join("?" * len(ids))
    with _conexao() as con:
        linhas = con.execute(
            f"SELECT lead_id, dados_json FROM lead_cartao WHERE lead_id IN ({marcadores})",
            list(ids),
        ).fetchall()
    saida: dict[int, dict] = {}
    for linha in linhas:
        try:
            saida[int(linha["lead_id"])] = json.loads(linha["dados_json"] or "{}")
        except json.JSONDecodeError:
            continue
    return saida


def total_cartoes() -> int:
    with _conexao() as con:
        return int(con.execute("SELECT COUNT(*) FROM lead_cartao").fetchone()[0])


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
    """Timestamp em UTC, sempre o mesmo fuso (predictável pro filtro de datas)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
