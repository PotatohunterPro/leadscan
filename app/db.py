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

# Colunas do funil de vendas (funildevendas.md) — ficam FORA de CAMPOS para
# o POST /leads da captura não tocar nelas. O lead nasce no estágio 'novo'
# por DEFAULT do banco; só as funções do funil escrevem aqui.
FUNIL_COLUNAS: dict[str, str] = {
    "estagio": "TEXT NOT NULL DEFAULT 'novo'",
    "data_estagio_atual": "TEXT NOT NULL DEFAULT ''",
    "responsavel_atual": "TEXT NOT NULL DEFAULT ''",
    "ligacao_feita": "INTEGER NOT NULL DEFAULT 0",
    "data_ligacao": "TEXT NOT NULL DEFAULT ''",
    "ligacao_virou_lead": "INTEGER NOT NULL DEFAULT 0",
    "ligacao_observacao": "TEXT NOT NULL DEFAULT ''",
    "motivo_perda": "TEXT NOT NULL DEFAULT ''",
    # V2 (funil_implement_v2.md — itens 18, 21, 22, 39): origem do lead,
    # última interação e próxima ação. DEFAULTs mantêm os fluxos atuais
    # (POST /leads e /extract) funcionando sem envio desses campos.
    "origem": "TEXT NOT NULL DEFAULT 'manual'",
    "data_ultima_interacao": "TEXT NOT NULL DEFAULT ''",
    "proxima_acao": "TEXT NOT NULL DEFAULT ''",
    "data_proxima_acao": "TEXT NOT NULL DEFAULT ''",
    "proxima_acao_observacao": "TEXT NOT NULL DEFAULT ''",
    # V3 (5.1): valor estimado do negócio, em R$. Fica FORA de CAMPOS para
    # o POST /leads da captura não tocar — só a API do funil escreve aqui.
    "valor_estimado": "REAL NOT NULL DEFAULT 0",
}

# Usuários e papéis (V3 — 5.5). Sem tela de admin: a tabela é semeada a
# partir de funil.RESPONSAVEIS / funil.PAPEL_RESPONSAVEL (config no código).
# O papel define a visibilidade aplicada NA QUERY de listar_funil.
_SCHEMA_USUARIOS = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    papel TEXT NOT NULL DEFAULT 'sdr'
);
"""

# Histórico simples de mudanças de estágio — auditoria e métricas de tempo.
_SCHEMA_FUNIL = """
CREATE TABLE IF NOT EXISTS historico_estagios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    estagio TEXT NOT NULL,
    data TEXT NOT NULL,
    usuario_responsavel TEXT NOT NULL DEFAULT '',
    observacao TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
"""


# Histórico comercial geral (funildevendas.md itens 23/24/39) — a
# timeline única do detalhe: estagio, ligacao, whatsapp, email, proposta,
# observacao, proxima_acao, cartao, outro. O historico_estagios continua
# existindo (métricas de tempo e auditoria de estágios); as duas tabelas são
# escritas na MESMA transação (item 59).
_SCHEMA_ATIVIDADES = """
CREATE TABLE IF NOT EXISTS lead_atividades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    data_hora TEXT NOT NULL,
    responsavel TEXT NOT NULL DEFAULT '',
    estagio_anterior TEXT DEFAULT '',
    estagio_novo TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'realizada',
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);
"""


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
        con.execute(_SCHEMA_FUNIL)
        con.execute(_SCHEMA_ATIVIDADES)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_lead_cartao_lead ON lead_cartao(lead_id)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_hist_estagio_lead ON historico_estagios(lead_id)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_atividades_lead ON lead_atividades(lead_id)"
        )
        _migrar_colunas(con)
        _migrar_funil(con)
        _migrar_origem(con)
        _migrar_atividades(con)
        con.execute(_SCHEMA_USUARIOS)
        _semear_usuarios(con)
    logger.info("Banco pronto em %s", DB_PATH)


def _semear_usuarios(con: sqlite3.Connection) -> None:
    """Semeia os responsáveis do código na tabela usuarios (idempotente).

    V3 (5.5): o papel mora no banco para a regra de visibilidade viver no
    backend. Nomes novos no código entram na próxima inicialização; papéis
    de usuários existentes NÃO são sobrescritos (evita perder ajuste manual).
    """
    from .funil import PAPEL_RESPONSAVEL, RESPONSAVEIS

    existentes = {
        linha["nome"] for linha in con.execute("SELECT nome FROM usuarios").fetchall()
    }
    for nome in RESPONSAVEIS:
        if nome not in existentes:
            con.execute(
                "INSERT INTO usuarios (nome, papel) VALUES (?, ?)",
                [nome, PAPEL_RESPONSAVEL.get(nome, "sdr")],
            )


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


def _migrar_funil(con: sqlite3.Connection) -> None:
    """Adiciona a 'leads' as colunas do funil (ALTER TABLE — sem apagar dados)."""
    existentes = {
        linha["name"] for linha in con.execute("PRAGMA table_info(leads)").fetchall()
    }
    for coluna, definicao in FUNIL_COLUNAS.items():
        if coluna not in existentes:
            logger.info("Migração (funil): adicionando coluna %s em leads", coluna)
            con.execute(f"ALTER TABLE leads ADD COLUMN {coluna} {definicao}")


def _migrar_origem(con: sqlite3.Connection) -> None:
    """Backfill de origem (item 61/18): leads antigos que JÁ têm cartão viram
    origem='cartao'; os demais seguem 'manual'. Idempotente (WHERE origem='manual')."""
    con.execute(
        "UPDATE leads SET origem = 'cartao' "
        "WHERE origem = 'manual' AND id IN (SELECT lead_id FROM lead_cartao)"
    )


def _migrar_atividades(con: sqlite3.Connection) -> None:
    """V3 (5.2): garante a coluna status em lead_atividades (ALTER TABLE).

    Bancos antigos ganham status='realizada' — nada que já existia era
    agendado. Idempotente."""
    existentes = {
        linha["name"]
        for linha in con.execute("PRAGMA table_info(lead_atividades)").fetchall()
    }
    if "status" not in existentes:
        logger.info("Migração (V3): adicionando coluna status em lead_atividades")
        con.execute(
            "ALTER TABLE lead_atividades "
            "ADD COLUMN status TEXT NOT NULL DEFAULT 'realizada'"
        )


@contextmanager
def _conexao():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    # item 39 da spec: foreign keys ativas (leads -> lead_cartao/atividades/histórico)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _para_dict(linha: sqlite3.Row) -> dict:
    return {chave: linha[chave] for chave in linha.keys()}


def salvar_lead(dados: dict, origem: str = "manual") -> int:
    """Insere um lead. Campos desconhecidos são ignorados.

    origem (item 18): 'cartao' quando o lead nasce de uma captura de cartão
    (/extract salvar=1 ou POST /leads com cartao_json); default 'manual'.
    A origem NUNCA muda depois (item 47): edições não tocam nela.
    """
    dados = {c: str(dados.get(c, "")).strip() for c in CAMPOS}
    if origem not in ("manual", "cartao"):
        origem = "manual"
    with _conexao() as con:
        cur = con.execute(
            f"INSERT INTO leads ({', '.join(CAMPOS)}, origem, criado_em) "
            f"VALUES ({', '.join('?' * (len(CAMPOS) + 2))})",
            [dados[c] for c in CAMPOS] + [origem, agora_iso()],
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
        # timeline comercial (item 71): primeira captura do cartão é atividade
        # (só no INSERT — atualizar o cartão não gera nova entrada)
        _registrar_atividade(con, int(lead_id), "cartao", "📇 Cartão capturado")
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


# ------------------------------------------------------------- usuários (5.5)

def listar_usuarios() -> list[dict]:
    """Usuários configurados (nome + papel) — usados no login e na UI."""
    with _conexao() as con:
        linhas = con.execute(
            "SELECT id, nome, papel FROM usuarios ORDER BY id"
        ).fetchall()
        return [_para_dict(l) for l in linhas]


def buscar_usuario(nome: str) -> dict | None:
    with _conexao() as con:
        linha = con.execute(
            "SELECT id, nome, papel FROM usuarios WHERE nome = ?", [nome]
        ).fetchone()
        return _para_dict(linha) if linha else None


# ------------------------------------------------------- funil de vendas


def _registrar_atividade(
    con: sqlite3.Connection,
    lead_id: int,
    tipo: str,
    descricao: str = "",
    responsavel: str = "",
    estagio_anterior: str = "",
    estagio_novo: str = "",
    status: str = "realizada",
) -> None:
    """INSERT na lead_atividades + data_ultima_interacao (item 22) — na MESMA
    transação da chamadora (item 59). Usar só dentro de um `with _conexao()`.

    V3 (5.2): `status` distingue agendada/realizada/cancelada — a próxima
    ação nasce 'agendada' e só vira 'realizada' quando concluída de fato.
    """
    if status not in ("agendada", "realizada", "cancelada"):
        status = "realizada"
    agora = agora_iso()
    con.execute(
        "INSERT INTO lead_atividades (lead_id, tipo, descricao, data_hora, "
        "responsavel, estagio_anterior, estagio_novo, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [lead_id, tipo, (descricao or "").strip(), agora,
         (responsavel or "").strip(), estagio_anterior, estagio_novo, status],
    )
    con.execute(
        "UPDATE leads SET data_ultima_interacao = ? WHERE id = ?",
        [agora, lead_id],
    )


def registrar_atividade(
    lead_id: int,
    tipo: str,
    descricao: str = "",
    responsavel: str = "",
    estagio_anterior: str = "",
    estagio_novo: str = "",
) -> None:
    """Versão pública (transação própria) — usada fora de mudar_estagio etc."""
    if not buscar_lead(lead_id):
        raise ValueError("Lead não encontrado")
    with _conexao() as con:
        _registrar_atividade(
            con, lead_id, tipo, descricao, responsavel,
            estagio_anterior, estagio_novo,
        )


def atividades_do_lead(lead_id: int) -> list[dict]:
    """Timeline comercial geral (item 23/71) — mais recente primeiro."""
    with _conexao() as con:
        linhas = con.execute(
            "SELECT id, tipo, descricao, data_hora, responsavel, "
            "estagio_anterior, estagio_novo, status FROM lead_atividades "
            "WHERE lead_id = ? ORDER BY id DESC",
            [lead_id],
        ).fetchall()
        return [_para_dict(l) for l in linhas]


def concluir_atividade(lead_id: int, atividade_id: int, usuario: str = "") -> dict:
    """V3 (5.2): marca uma atividade AGENDADA como 'realizada'.

    A ligação entre a próxima ação agendada e a execução é feita por ID
    (botão "concluída" na timeline) — não por proximidade de data, que é
    frágil quando duas ações caem no mesmo dia. Também limpa a próxima ação
    do lead se a atividade concluída for a que está pendente nele.
    """
    from .funil import TIPOS_ATIVIDADE

    if not buscar_lead(lead_id):
        raise ValueError("Lead não encontrado")
    with _conexao() as con:
        linha = con.execute(
            "SELECT tipo, status FROM lead_atividades WHERE id = ? AND lead_id = ?",
            [atividade_id, lead_id],
        ).fetchone()
        if not linha:
            raise ValueError("Atividade não encontrada")
        if linha["status"] == "realizada":
            return buscar_lead(lead_id)
        if linha["status"] != "agendada":
            raise ValueError("Só atividades agendadas podem ser concluídas.")
        con.execute(
            "UPDATE lead_atividades SET status = 'realizada' WHERE id = ?",
            [atividade_id],
        )
        # a próxima ação correspondente deixa de ser a ação pendente
        if linha["tipo"] in ("proxima_acao", "ligacao", "whatsapp", "email", "proposta"):
            con.execute(
                "UPDATE leads SET proxima_acao = '', data_proxima_acao = '', "
                "proxima_acao_observacao = '' WHERE id = ?",
                [lead_id],
            )
        _registrar_atividade(
            con, lead_id, "observacao",
            "✅ Ação concluída: " + str(linha["tipo"]), usuario,
        )
    return buscar_lead(lead_id)


def cancelar_atividade(lead_id: int, atividade_id: int, usuario: str = "") -> dict:
    """V3 (5.2): marca uma atividade AGENDADA como 'cancelada'."""
    if not buscar_lead(lead_id):
        raise ValueError("Lead não encontrado")
    with _conexao() as con:
        linha = con.execute(
            "SELECT status FROM lead_atividades WHERE id = ? AND lead_id = ?",
            [atividade_id, lead_id],
        ).fetchone()
        if not linha:
            raise ValueError("Atividade não encontrada")
        if linha["status"] != "agendada":
            return buscar_lead(lead_id)
        con.execute(
            "UPDATE lead_atividades SET status = 'cancelada' WHERE id = ?",
            [atividade_id],
        )
        con.execute(
            "UPDATE leads SET proxima_acao = '', data_proxima_acao = '', "
            "proxima_acao_observacao = '' WHERE id = ?",
            [lead_id],
        )
        _registrar_atividade(
            con, lead_id, "observacao", "🚫 Ação cancelada", usuario,
        )
    return buscar_lead(lead_id)


def mudar_estagio(
    lead_id: int,
    estagio: str,
    usuario: str = "",
    observacao: str = "",
    motivo_perda: str = "",
) -> dict:
    """Move o lead de estágio com as regras do funil (funildevendas.md).

    - 'qualificado' exige ligação registrada E 'virou lead';
    - 'perdido' exige motivo_perda;
    - toda mudança grava em historico_estagios (auditoria com usuário/data);
    - toda mudança vira atividade na lead_atividades e atualiza
      data_ultima_interacao (itens 22/26) — MESMA transação (item 59);
    - fechado gera atividade "✅ Lead fechado" (item 27);
    - perdido gera atividade com o motivo (item 28);
    - reabertura (itens 29/30): o motivo da perda é PRESERVADO no lead.

    Levanta ValueError com a mensagem da regra quebrada (a API devolve 422).
    Idempotente: mover para o estágio atual não grava histórico duplicado.
    """
    from .funil import ESTAGIOS, estagio_valido

    if not estagio_valido(estagio):
        raise ValueError(
            f"Estágio inválido: {estagio!r}. Valores: {', '.join(ESTAGIOS)}"
        )
    lead = buscar_lead(lead_id)
    if not lead:
        raise ValueError("Lead não encontrado")
    if lead["estagio"] == estagio:
        return lead
    if estagio == "qualificado":
        if not lead["ligacao_feita"]:
            raise ValueError(
                "Para mover para Qualificado o lead precisa de ligação "
                "registrada (botão 'Registrar ligação')."
            )
        if not lead["ligacao_virou_lead"]:
            raise ValueError(
                "Para mover para Qualificado a ligação precisa ter marcado "
                "'virou lead'."
            )
    if estagio == "perdido" and not (motivo_perda or "").strip():
        raise ValueError(
            "Para mover para Perdido é preciso informar o motivo da perda."
        )
    if estagio == "negociacao" and lead["estagio"] == "qualificado" and not (
        observacao or ""
    ).strip():
        raise ValueError(
            "Para virar negociação, explique por que essa oportunidade é real."
        )
    agora = agora_iso()
    with _conexao() as con:
        if estagio == "perdido":
            # motivo só é gravado ao ENTRAR em perdido (item 28); reabertura
            # (itens 29/30) preserva o motivo original no lead.
            con.execute(
                "UPDATE leads SET estagio = ?, data_estagio_atual = ?, "
                "responsavel_atual = ?, motivo_perda = ?, "
                "data_ultima_interacao = ? WHERE id = ?",
                [estagio, agora, usuario, (motivo_perda or "").strip(), agora, lead_id],
            )
        else:
            con.execute(
                "UPDATE leads SET estagio = ?, data_estagio_atual = ?, "
                "responsavel_atual = ?, data_ultima_interacao = ? WHERE id = ?",
                [estagio, agora, usuario, agora, lead_id],
            )
        con.execute(
            "INSERT INTO historico_estagios (lead_id, estagio, data, "
            "usuario_responsavel, observacao) VALUES (?, ?, ?, ?, ?)",
            [lead_id, estagio, agora, usuario, (observacao or "").strip()],
        )
        # timeline comercial na MESMA transação (itens 26/27/28/59)
        tipo_atividade = "estagio"
        descricao = (observacao or "").strip()
        if estagio == "fechado":
            descricao = "✅ Lead fechado" + (f" — {descricao}" if descricao else "")
        elif estagio == "perdido":
            motivo = (motivo_perda or "").strip()
            obs = (observacao or "").strip()
            descricao = f"❌ Perdido — motivo: {motivo}" + (f" — {obs}" if obs else "")
        elif estagio == "negociacao" and lead["estagio"] == "qualificado":
            # V3 (5.3): passagem pra negociação é evento explícito — a
            # observação é obrigatória e entra como atividade própria.
            tipo_atividade = "oportunidade"
            obs = (observacao or "").strip()
            descricao = "🎯 Virou oportunidade" + (f" — {obs}" if obs else "")
        _registrar_atividade(
            con, lead_id, tipo_atividade, descricao, usuario,
            lead["estagio"], estagio,
        )
    return buscar_lead(lead_id)


def registrar_ligacao(
    lead_id: int,
    feita: bool,
    virou_lead: bool = False,
    observacao: str = "",
    usuario: str = "",
) -> dict:
    """Registra a ligação da SDR: feita?, virou lead?, observação.

    O responsável atual passa a ser quem registrou a ligação. Gera atividade
    tipo 'ligacao' e atualiza data_ultima_interacao (itens 19/22) na MESMA
    transação (item 59).
    """
    if not buscar_lead(lead_id):
        raise ValueError("Lead não encontrado")
    agora = agora_iso()
    with _conexao() as con:
        con.execute(
            "UPDATE leads SET ligacao_feita = ?, ligacao_virou_lead = ?, "
            "ligacao_observacao = ?, data_ligacao = ?, responsavel_atual = ?, "
            "data_ultima_interacao = ? WHERE id = ?",
            [1 if feita else 0, 1 if virou_lead else 0,
             (observacao or "").strip(), agora, usuario, agora, lead_id],
        )
        descricao = "📞 Ligação registrada" + (
            " — virou lead" if virou_lead else " — não virou lead"
        )
        if (observacao or "").strip():
            descricao += f" — {(observacao or '').strip()}"
        _registrar_atividade(con, lead_id, "ligacao", descricao, usuario)
    return buscar_lead(lead_id)


def salvar_proxima_acao(
    lead_id: int,
    acao: str,
    data: str = "",
    observacao: str = "",
    usuario: str = "",
) -> dict:
    """Próxima ação do lead (item 21): ação + data + observação.

    Atualiza as 3 colunas, gera atividade tipo 'proxima_acao' e atualiza
    data_ultima_interacao — MESMA transação (item 59)."""
    if not buscar_lead(lead_id):
        raise ValueError("Lead não encontrado")
    agora = agora_iso()
    acao = (acao or "").strip()
    data = (data or "").strip()
    observacao = (observacao or "").strip()
    with _conexao() as con:
        con.execute(
            "UPDATE leads SET proxima_acao = ?, data_proxima_acao = ?, "
            "proxima_acao_observacao = ?, data_ultima_interacao = ? "
            "WHERE id = ?",
            [acao, data, observacao, agora, lead_id],
        )
        if acao:
            # V3 (5.2): uma próxima ação agendada por vez — a pendente
            # anterior (tipo proxima_acao e ainda 'agendada') vira cancelada.
            con.execute(
                "UPDATE lead_atividades SET status = 'cancelada' "
                "WHERE lead_id = ? AND tipo = 'proxima_acao' AND status = 'agendada'",
                [lead_id],
            )
            descricao = acao
            if data:
                descricao += f" em {data}"
            if observacao:
                descricao += f" — {observacao}"
            _registrar_atividade(
                con, lead_id, "proxima_acao", descricao, usuario,
                status="agendada",
            )
        else:
            # limpar a próxima ação também cancela a agendada pendente
            con.execute(
                "UPDATE lead_atividades SET status = 'cancelada' "
                "WHERE lead_id = ? AND tipo = 'proxima_acao' AND status = 'agendada'",
                [lead_id],
            )
    return buscar_lead(lead_id)


def salvar_valor_estimado(lead_id: int, valor: float) -> dict:
    """V3 (5.1): valor estimado do negócio, em R$. Não gera atividade —
    é um dado do lead, não uma mudança de estado. Não mexe no estágio."""
    if not buscar_lead(lead_id):
        raise ValueError("Lead não encontrado")
    valor = max(0.0, round(float(valor or 0), 2))
    with _conexao() as con:
        con.execute(
            "UPDATE leads SET valor_estimado = ? WHERE id = ?", [valor, lead_id]
        )
    return buscar_lead(lead_id)


def registrar_responsavel(lead_id: int, usuario: str) -> dict:
    """V3 (5.5): fixa o responsável atual de um lead (ex.: ao criar).

    Gera atividade de trilha para manter rastro de toda mudança de dono."""
    lead = buscar_lead(lead_id)
    if not lead:
        raise ValueError("Lead não encontrado")
    usuario = (usuario or "").strip()
    with _conexao() as con:
        con.execute(
            "UPDATE leads SET responsavel_atual = ?, data_ultima_interacao = ? "
            "WHERE id = ?",
            [usuario, agora_iso(), lead_id],
        )
        _registrar_atividade(
            con, lead_id, "observacao",
            f"👤 Lead atribuído a {usuario}" if usuario else "👤 Lead atribuído",
            usuario,
        )
    return buscar_lead(lead_id)


def registrar_interacao(
    lead_id: int,
    tipo: str,
    descricao: str = "",
    usuario: str = "",
) -> dict:
    """[+ Registrar interação] (item 25): whatsapp/email/proposta/
    observacao/outro entram no histórico comercial geral."""
    from .funil import TIPOS_ATIVIDADE

    if not buscar_lead(lead_id):
        raise ValueError("Lead não encontrado")
    if tipo not in TIPOS_ATIVIDADE:
        raise ValueError(
            f"Tipo de atividade inválido: {tipo!r}. Valores: {', '.join(TIPOS_ATIVIDADE)}"
        )
    with _conexao() as con:
        _registrar_atividade(con, lead_id, tipo, descricao, usuario)
    return buscar_lead(lead_id)


def historico_do_lead(lead_id: int) -> list[dict]:
    """Linha do tempo das mudanças de estágio (mais antiga primeiro)."""
    with _conexao() as con:
        linhas = con.execute(
            "SELECT estagio, data, usuario_responsavel, observacao "
            "FROM historico_estagios WHERE lead_id = ? ORDER BY id",
            [lead_id],
        ).fetchall()
        return [_para_dict(l) for l in linhas]


def buscar_lead_funil(lead_id: int) -> dict | None:
    """Lead + cartão + histórico + timeline geral — usado no detalhe do funil."""
    lead = buscar_lead_completo(lead_id)
    if lead is None:
        return None
    lead["historico"] = historico_do_lead(lead_id)
    lead["atividades"] = atividades_do_lead(lead_id)
    # V3 (5.2): 🔔 no detalhe segue a MESMA regra do kanban (agendada pendente)
    lead["tem_acao_agendada"] = bool(_atividades_agendadas_por_lead([lead_id]).get(lead_id))
    return lead


def listar_funil(
    busca: str = "",
    responsavel: str = "",
    estagio: str = "",
    origem: str = "",
    de: str | None = None,
    ate: str | None = None,
    sem_contato: bool = False,
    atrasados: bool = False,
    retorno_hoje: bool = False,
    limite: int = 500,
) -> list[dict]:
    """Leads do kanban com o cartão (miniatura) e o tempo no estágio.

    Filtros V2 (itens 31–34): origem, sem_contato (ligacao_feita=0),
    atrasados (próxima ação vencida, fora de fechado/perdido) e retorno_hoje
    (data_proxima_acao = hoje). A busca também cobre telefone e e-mail.

    O tempo no estágio usa data_estagio_atual; quando o lead nunca foi
    movido (captura direta), usa criado_em como início."""
    sql = "SELECT * FROM leads WHERE 1=1"
    params: list = []
    if busca:
        sql += (
            " AND (nome_empresa LIKE ? OR nome_contato LIKE ? OR whatsapp LIKE ? "
            "OR telefone LIKE ? OR email LIKE ?)"
        )
        like = f"%{busca}%"
        params += [like, like, like, like, like]
    if responsavel:
        sql += " AND responsavel_atual = ?"
        params.append(responsavel)
    if estagio:
        sql += " AND estagio = ?"
        params.append(estagio)
    if origem:
        sql += " AND origem = ?"
        params.append(origem)
    if sem_contato:
        sql += " AND ligacao_feita = 0"
    if atrasados:
        sql += (
            " AND data_proxima_acao != '' AND data_proxima_acao < ? "
            "AND estagio NOT IN ('fechado', 'perdido')"
        )
        params.append(agora_iso())
    if retorno_hoje:
        sql += " AND date(data_proxima_acao) = date('now')"
    if de:
        sql += " AND date(criado_em) >= ?"
        params.append(de)
    if ate:
        sql += " AND date(criado_em) <= ?"
        params.append(ate)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limite), 2000)))
    with _conexao() as con:
        linhas = con.execute(sql, params).fetchall()
        leads = [_para_dict(l) for l in linhas]

    cartoes = leads_com_cartao([l["id"] for l in leads])
    from datetime import datetime, timezone

    agora = datetime.now(timezone.utc)
    from .funil import DIAS_ESTAGNADO

    ids = [l["id"] for l in leads]
    # V3 (5.2): 🔔 só aparece com próxima ação AGENDADA pendente — some
    # quando a atividade vira realizada/cancelada.
    agendadas = _atividades_agendadas_por_lead(ids) if ids else {}
    for l in leads:
        l["cartao"] = cartoes.get(l["id"])
        l["tem_cartao"] = bool(cartoes.get(l["id"]))
        l["tem_acao_agendada"] = bool(agendadas.get(l["id"]))
        inicio = l["data_estagio_atual"] or l["criado_em"]
        try:
            dias = (agora - datetime.fromisoformat(inicio)).total_seconds() / 86400
        except (ValueError, TypeError):
            dias = 0.0
        l["tempo_no_estagio_dias"] = round(dias, 1)
        l["estagnado"] = dias > DIAS_ESTAGNADO
    return leads


def _atividades_agendadas_por_lead(ids: list[int]) -> dict[int, int]:
    """V3 (5.2): atividade 'agendada' pendente por lead (tipo proxima_acao)."""
    marcadores = ",".join("?" * len(ids))
    with _conexao() as con:
        linhas = con.execute(
            f"SELECT lead_id, COUNT(*) AS n FROM lead_atividades "
            f"WHERE lead_id IN ({marcadores}) AND tipo = 'proxima_acao' "
            f"AND status = 'agendada' GROUP BY lead_id",
            list(ids),
        ).fetchall()
        return {int(l["lead_id"]): int(l["n"]) for l in linhas}


def metricas_funil(
    de: str | None = None,
    ate: str | None = None,
    responsavel: str = "",
) -> dict:
    """Métricas leves: contagem por estágio, conversão, tempo médio e —
    V3 (5.1) — valor esperado do funil. `responsavel` restringe tudo a um
    responsável (a visibilidade por papel é aplicada na rota, no backend).

    O valor esperado é calculado NO SQL (ROUND(SUM(valor*prob), 2)), com o
    mesmo arredondamento de uma consulta direta — nenhum número da tela foge
    do que um `SELECT` cru no banco devolveria."""
    from .funil import PROBABILIDADE_ESTAGIO

    where = "WHERE 1=1"
    params: list = []
    if de:
        where += " AND date(criado_em) >= ?"
        params.append(de)
    if ate:
        where += " AND date(criado_em) <= ?"
        params.append(ate)
    if responsavel:
        where += " AND responsavel_atual = ?"
        params.append(responsavel)
    case_prob = _case_probabilidade(PROBABILIDADE_ESTAGIO)
    with _conexao() as con:
        linhas = con.execute(
            f"SELECT estagio, COUNT(*) AS n, SUM(valor_estimado) AS soma, "
            f"ROUND(SUM(valor_estimado * {case_prob}), 2) AS esperado "
            f"FROM leads {where} GROUP BY estagio",
            params,
        ).fetchall()
        # valor esperado dos leads ABERTOS (fora de fechado/perdido)
        esperado_total = con.execute(
            f"SELECT COALESCE(ROUND(SUM(valor_estimado * {case_prob}), 2), 0) "
            f"FROM leads {where} AND estagio NOT IN ('fechado', 'perdido')",
            params,
        ).fetchone()[0]
    contagem = {l["estagio"]: int(l["n"]) for l in linhas}
    esperado_por_estagio = {
        l["estagio"]: float(l["esperado"]) for l in linhas if l["esperado"]
    }
    total = sum(contagem.values())
    fechados = contagem.get("fechado", 0)
    conversao = round(fechados / total * 100, 1) if total else 0.0
    especificos = _tempo_medio_especifico(de, ate, responsavel)
    return {
        "por_estagio": contagem,
        "total": total,
        "conversao_percent": conversao,
        "tempo_medio_dias": _tempo_medio_por_estagio(de, ate, responsavel),
        "valor_esperado_total": float(esperado_total),
        "valor_esperado_por_estagio": esperado_por_estagio,
        **especificos,
    }


def _case_probabilidade(probs: dict[str, int]) -> str:
    """Expressão SQL `CASE estagio WHEN 'novo' THEN 0.05 ... END`."""
    partes = " ".join(
        f"WHEN '{est}' THEN {prob / 100}"
        for est, prob in probs.items()
    )
    return f"CASE estagio {partes} ELSE 0 END"


def relatorio_perdas(
    de: str | None = None,
    ate: str | None = None,
    responsavel: str = "",
) -> dict:
    """V3 (5.4): contagem de leads perdidos cruzando motivo × origem ×
    responsável. Sem tabela nova — lê de `leads` com estagio='perdido'.

    Retorna {'total': n, 'linhas': [ {motivo_perda, origem,
    responsavel_atual, quantidade, valor_estimado}, ... ]} ordenado por
    quantidade desc. O período filtra por criado_em do lead."""
    where = "WHERE estagio = 'perdido'"
    params: list = []
    if de:
        where += " AND date(criado_em) >= ?"
        params.append(de)
    if ate:
        where += " AND date(criado_em) <= ?"
        params.append(ate)
    if responsavel:
        where += " AND responsavel_atual = ?"
        params.append(responsavel)
    sql = (
        "SELECT motivo_perda, origem, responsavel_atual, "
        "COUNT(*) AS quantidade, SUM(valor_estimado) AS valor_estimado "
        f"FROM leads {where} GROUP BY motivo_perda, origem, responsavel_atual "
        "ORDER BY quantidade DESC, motivo_perda"
    )
    with _conexao() as con:
        linhas = con.execute(sql, params).fetchall()
    dados = []
    for l in linhas:
        dados.append({
            "motivo_perda": l["motivo_perda"] or "—",
            "origem": l["origem"] or "—",
            "responsavel_atual": l["responsavel_atual"] or "—",
            "quantidade": int(l["quantidade"]),
            "valor_estimado": round(float(l["valor_estimado"] or 0), 2),
        })
    return {"total": sum(d["quantidade"] for d in dados), "linhas": dados}


def _tempo_medio_especifico(
    de: str | None = None,
    ate: str | None = None,
    responsavel: str = "",
) -> dict[str, float | None]:
    """Métricas específicas do item 37 (None quando não há dados — o front
    mostra '—'):

    - qualificacao_dias: do início (criado_em) até entrar em qualificado;
    - negociacao_dias: permanência total em negociação (até sair ou agora);
    - fechamento_dias: do início até entrar em fechado.
    """
    sql = (
        "SELECT l.id AS lead_id, l.criado_em, h.estagio, h.data "
        "FROM historico_estagios h JOIN leads l ON l.id = h.lead_id WHERE 1=1"
    )
    params: list = []
    if de:
        sql += " AND date(l.criado_em) >= ?"
        params.append(de)
    if ate:
        sql += " AND date(l.criado_em) <= ?"
        params.append(ate)
    if responsavel:
        sql += " AND l.responsavel_atual = ?"
        params.append(responsavel)
    sql += " ORDER BY h.lead_id, h.id"
    with _conexao() as con:
        linhas = con.execute(sql, params).fetchall()

    from datetime import datetime, timezone

    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    criados: dict[int, str] = {}
    seq_por_lead: dict[int, list[tuple[str, str]]] = {}
    for l in linhas:
        lid = int(l["lead_id"])
        criados.setdefault(lid, l["criado_em"])
        seq_por_lead.setdefault(lid, []).append((l["estagio"], l["data"]))

    def _dias(inicio: str, fim: str) -> float | None:
        try:
            d = datetime.fromisoformat(fim) - datetime.fromisoformat(inicio)
            return max(0.0, d.total_seconds() / 86400)
        except (ValueError, TypeError):
            return None

    qualificacoes: list[float] = []
    fechamentos: list[float] = []
    negociacoes: list[float] = []
    for lid, seq in seq_por_lead.items():
        criado = criados.get(lid)
        for i, (est, data) in enumerate(seq):
            if est == "qualificado" and criado:
                d = _dias(criado, data)
                if d is not None:
                    qualificacoes.append(d)
            if est == "fechado" and criado:
                d = _dias(criado, data)
                if d is not None:
                    fechamentos.append(d)
            if est == "negociacao":
                fim = seq[i + 1][1] if i + 1 < len(seq) else agora
                d = _dias(data, fim)
                if d is not None:
                    negociacoes.append(d)

    def _media(valores: list[float]) -> float | None:
        return round(sum(valores) / len(valores), 1) if valores else None

    return {
        "tempo_medio_qualificacao_dias": _media(qualificacoes),
        "tempo_medio_negociacao_dias": _media(negociacoes),
        "tempo_medio_fechamento_dias": _media(fechamentos),
    }

def _tempo_medio_por_estagio(
    de: str | None = None, ate: str | None = None, responsavel: str = ""
) -> dict[str, float]:
    """Duração média (dias) em cada estágio, a partir do histórico.

    Para cada entrada do histórico: a duração vai até a próxima mudança do
    MESMO lead; a última (estágio atual) vai até agora.
    """
    sql = (
        "SELECT h.lead_id, h.estagio, h.data "
        "FROM historico_estagios h JOIN leads l ON l.id = h.lead_id WHERE 1=1"
    )
    params: list = []
    if de:
        sql += " AND date(l.criado_em) >= ?"
        params.append(de)
    if ate:
        sql += " AND date(l.criado_em) <= ?"
        params.append(ate)
    if responsavel:
        sql += " AND l.responsavel_atual = ?"
        params.append(responsavel)
    sql += " ORDER BY h.lead_id, h.id"
    with _conexao() as con:
        linhas = con.execute(sql, params).fetchall()
    por_lead: dict[int, list[tuple[str, str]]] = {}
    for l in linhas:
        por_lead.setdefault(int(l["lead_id"]), []).append((l["estagio"], l["data"]))
    acum: dict[str, float] = {}
    n: dict[str, int] = {}
    from datetime import datetime, timezone

    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for seq in por_lead.values():
        for i, (est, data) in enumerate(seq):
            fim = seq[i + 1][1] if i + 1 < len(seq) else agora
            try:
                inicio = datetime.fromisoformat(data)
                fim_dt = datetime.fromisoformat(fim)
                dias = max(0.0, (fim_dt - inicio).total_seconds() / 86400)
            except (ValueError, TypeError):
                continue
            acum[est] = acum.get(est, 0.0) + dias
            n[est] = n.get(est, 0) + 1
    return {est: round(acum[est] / n[est], 1) for est in acum if n[est]}


def agora_iso() -> str:
    """Timestamp em UTC, sempre o mesmo fuso (predictável pro filtro de datas)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
