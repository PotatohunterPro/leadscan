"""Funil de vendas — estágios, responsáveis e regras (funildevendas.md).

A spec pede estágios e a lista de SDR/vendedores configuráveis NO CÓDIGO,
não em tela de admin. O sistema continua com senha única compartilhada
(sem login por usuário): o responsável é escolhido pelo time entre os nomes
de RESPONSAVEIS.
"""

# ------------------------------------------------------------------ estágios

ESTAGIO_NOVO = "novo"
ESTAGIO_LIGACAO = "ligacao_feita"
ESTAGIO_QUALIFICADO = "qualificado"
ESTAGIO_NEGOCIACAO = "negociacao"
ESTAGIO_FECHADO = "fechado"
ESTAGIO_PERDIDO = "perdido"

# Ordem do funil — usada no kanban e nas transições.
ESTAGIOS = [
    ESTAGIO_NOVO,
    ESTAGIO_LIGACAO,
    ESTAGIO_QUALIFICADO,
    ESTAGIO_NEGOCIACAO,
    ESTAGIO_FECHADO,
    ESTAGIO_PERDIDO,
]

ROTULOS_ESTAGIOS = {
    ESTAGIO_NOVO: "🆕 Novo",
    ESTAGIO_LIGACAO: "📞 Ligação feita",
    ESTAGIO_QUALIFICADO: "✅ Qualificado",
    ESTAGIO_NEGOCIACAO: "🤝 Em negociação",
    ESTAGIO_FECHADO: "🏆 Fechado (ganho)",
    ESTAGIO_PERDIDO: "❌ Perdido",
}

# ------------------------------------------------------- responsáveis (SDR)

# SDR/vendedores do time — configurável aqui (sem gestão de usuários).
RESPONSAVEIS = [
    "SDR 1",
    "SDR 2",
    "SDR 3",
]

# ------------------------------------------------- papéis (V3 — item 5.5)
# O sistema continua com senha única compartilhada; o papel define o que a
# pessoa VÊ (aplicado na query do backend, nunca só na UI):
#   bdr/sdr -> só os leads em que é o responsável atual;
#   gestor  -> todos, com filtro opcional "Meus leads".
# Ajustar aqui conforme o time real — sem tela de admin.
PAPEIS = ("bdr", "sdr", "gestor")
PAPEL_RESPONSAVEL = {
    "SDR 1": "bdr",
    "SDR 2": "sdr",
    "SDR 3": "gestor",
}

# ------------------------------------- probabilidade por estágio (V3 — 5.1)
# Usada no valor esperado do funil: valor_estimado × probabilidade/100.
# perdido=0 (fora do funil); fechado=100 (valor realizado).
PROBABILIDADE_ESTAGIO = {
    ESTAGIO_NOVO: 5,
    ESTAGIO_LIGACAO: 10,
    ESTAGIO_QUALIFICADO: 25,
    ESTAGIO_NEGOCIACAO: 60,
    ESTAGIO_FECHADO: 100,
    ESTAGIO_PERDIDO: 0,
}

# Após quantos dias parado no estágio o card ganha destaque visual.
DIAS_ESTAGNADO = 3

# Tipos padronizados do histórico comercial geral (item 24 da spec) — usados
# em lead_atividades.tipo e no formulário "[+ Registrar interação]" (item 25).
TIPOS_ATIVIDADE = [
    "estagio",
    "ligacao",
    "whatsapp",
    "email",
    "proposta",
    "observacao",
    "proxima_acao",
    "oportunidade",
    "cartao",
    "outro",
]

# Motivos de perda (item 20 da spec) — "Outro" abre campo livre no frontend.
MOTIVOS_PERDA = [
    "Sem interesse",
    "Já possui solução",
    "Preço",
    "Sem orçamento",
    "Sem necessidade",
    "Concorrente",
    "Contato inválido",
    "Outro",
]


def estagio_valido(valor: str) -> bool:
    return valor in ESTAGIOS
