"""
Validação determinística dos dados do cartão.

A IA (VLM) NUNCA decide sozinha se um número é válido: tudo que é número,
e-mail, URL, CEP ou rede social passa por estas funções. Regras:

  * nada de completar número parcialmente legível — se não dá, é descartado
    (ou marcado como parcial, nunca "consertado");
  * telefone só é aceito com DDD brasileiro válido (10 ou 11 dígitos);
  * o que a IA disser e não aparecer no texto do OCR é marcado com
    confiança menor (e descartado quando o OCR leu bem a imagem).

Tudo aqui é puro Python/regex — sem dependências, sem rede.
"""

from __future__ import annotations

import re
import unicodedata

# ------------------------------------------------------------------ tabelas

DDDS_VALIDOS = {
    11, 12, 13, 14, 15, 16, 17, 18, 19,
    21, 22, 24, 27, 28,
    31, 32, 33, 34, 35, 37, 38,
    41, 42, 43, 44, 45, 46, 47, 48, 49,
    51, 53, 54, 55,
    61, 62, 63, 64, 65, 66, 67, 68, 69,
    71, 73, 74, 75, 77, 79,
    81, 82, 83, 84, 85, 86, 87, 88, 89,
    91, 92, 93, 94, 95, 96, 97, 98, 99,
}

UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

PALAVRAS_WHATSAPP = ("whatsapp", "whats", "wpp", "zap", "wats")
PALAVRAS_CELULAR = ("celular", "cel.", "cel ", "cel:", "movel", "móvel")
PALAVRAS_FIXO = ("telefone", "tel.", "tel:", "tel ", "fone", "fixo", "fax")

TIPOS_LOGRADOURO = (
    "rua", "r.", "avenida", "av.", "av ", "alameda", "al.", "travessa", "tv.",
    "praca", "praça", "pça", "rodovia", "rod.", "estrada", "est.", "largo",
    "viela", "vila", "quadra", "q.", "servidao",
)

REDES = {
    "instagram": ("instagram.com", "instagr.am"),
    "facebook": ("facebook.com", "fb.com", "fb.me"),
    "linkedin": ("linkedin.com", "lnkd.in"),
    "tiktok": ("tiktok.com"),
    "youtube": ("youtube.com", "youtu.be"),
    "twitter": ("twitter.com", "x.com"),
    "telegram": ("t.me", "telegram.me"),
}

# ------------------------------------------------------------------ regex

_RE_TELEFONE = re.compile(
    r"(?:\+?\s?55[\s.\-]?)?"          # DDI opcional
    r"(?:\(?\s?\d{2}\s?\)?[\s.\-]?)?"  # DDD opcional
    r"9?\d{4}[\s.\-]?\d{4}"            # número
)
_RE_CEP = re.compile(r"\b(\d{5})[\s.\-]?(\d{3})\b")
_RE_EMAIL = re.compile(
    r"[A-Za-z0-9._%+\-]+\s?@\s?[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)
_RE_URL = re.compile(
    r"(?:https?://)?(?:www\.)?"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+"
    r"(?:com|net|org|br|io|app|info|biz|shop|store|me|tv|co|edu|gov|com\.br|"
    r"net\.br|org\.br|ind\.br|adv\.br|eco\.br|art\.br|agr\.br)"
    r"(?:\.br)?(?:/[^\s,;)\]]*)?",
    re.IGNORECASE,
)
_RE_ARROBA = re.compile(r"@([A-Za-z0-9._]{3,32})\b")
_RE_CIDADE_UF = re.compile(
    r"([A-Za-zÀ-ÿ'\.][A-Za-zÀ-ÿ'\. \t]{1,39}?)\s*[-–/,]\s*(" + "|".join(sorted(UFS)) + r")\b"
)
_RE_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")


# ------------------------------------------------------------------ helpers

def apenas_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )


def normalizar_espacos(texto: str) -> str:
    return re.sub(r"[ \t]+", " ", (texto or "").strip())


# ------------------------------------------------------------------ telefone

def normalizar_telefone(bruto: str) -> dict | None:
    """Valida e formata um telefone brasileiro.

    Devolve None quando o número não é aproveitável (curto demais, DDD
    inexistente, dígitos repetidos). NUNCA inventa dígitos que faltam.
    """
    digitos = apenas_digitos(bruto)
    if not digitos:
        return None

    # DDI 55 só é removido quando sobra um número plausível (10 ou 11 dígitos)
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) == 11 and digitos.startswith("0"):   # 0XX
        digitos = digitos[1:]

    if len(set(digitos)) == 1:            # 0000-0000 / 9999-9999 = lixo do OCR
        return None

    if len(digitos) in (10, 11):
        ddd = int(digitos[:2])
        if ddd not in DDDS_VALIDOS:
            return None
        local = digitos[2:]
        if len(local) == 9 and not local.startswith("9"):
            return None                    # celular brasileiro começa com 9
        if len(local) == 8 and local[0] in "01":
            return None
        celular = len(local) == 9
        formatado = (
            f"({digitos[:2]}) {local[:5]}-{local[5:]}" if celular
            else f"({digitos[:2]}) {local[:4]}-{local[4:]}"
        )
        return {
            "numero": formatado,
            "digitos": digitos,
            "e164": "+55" + digitos,
            "tipo": "celular" if celular else "fixo",
            "parcial": False,
        }

    if len(digitos) in (8, 9):
        # sem DDD: não completamos nada — fica marcado como parcial
        if digitos[0] in "01":
            return None
        if len(digitos) == 9 and not digitos.startswith("9"):
            return None
        formatado = (
            f"{digitos[:5]}-{digitos[5:]}" if len(digitos) == 9
            else f"{digitos[:4]}-{digitos[4:]}"
        )
        return {
            "numero": formatado,
            "digitos": digitos,
            "e164": "",
            "tipo": "celular" if len(digitos) == 9 else "fixo",
            "parcial": True,
        }

    return None


def _tipo_pelo_contexto(contexto: str, tipo_base: str) -> str:
    ctx = sem_acento(contexto).lower()
    if any(p in ctx for p in PALAVRAS_WHATSAPP):
        return "whatsapp"
    if any(p in ctx for p in PALAVRAS_CELULAR):
        return "celular"
    if any(p in ctx for p in PALAVRAS_FIXO):
        return "fixo"
    return tipo_base


def extrair_telefones(texto: str, origem: str = "ocr") -> list[dict]:
    """Acha todos os telefones do texto, preservando TODOS (nunca sobrescreve).

    O tipo (fixo/celular/whatsapp) leva em conta as palavras da mesma linha.
    """
    encontrados: list[dict] = []
    vistos: set[str] = set()
    for linha in (texto or "").splitlines():
        # evita confundir CEP (00000-000) com telefone
        linha_limpa = _RE_CEP.sub(" ", linha)
        linha_limpa = _RE_CNPJ.sub(" ", linha_limpa)
        for m in _RE_TELEFONE.finditer(linha_limpa):
            tel = normalizar_telefone(m.group(0))
            if not tel:
                continue
            if tel["parcial"] and not _linha_parece_telefone(linha):
                continue
            if tel["digitos"] in vistos:
                continue
            vistos.add(tel["digitos"])
            tel["tipo"] = _tipo_pelo_contexto(linha, tel["tipo"])
            tel["origem"] = origem
            tel["confianca"] = 0.55 if tel["parcial"] else 0.9
            encontrados.append(tel)
    return encontrados


def _linha_parece_telefone(linha: str) -> bool:
    ctx = sem_acento(linha).lower()
    return any(
        p in ctx
        for p in PALAVRAS_WHATSAPP + PALAVRAS_CELULAR + PALAVRAS_FIXO
    )


# ------------------------------------------------------------------ CEP

def normalizar_cep(bruto: str) -> str:
    digitos = apenas_digitos(bruto)
    if len(digitos) != 8 or len(set(digitos)) == 1:
        return ""
    return f"{digitos[:5]}-{digitos[5:]}"


def extrair_ceps(texto: str) -> list[str]:
    saida: list[str] = []
    for m in _RE_CEP.finditer(texto or ""):
        cep = normalizar_cep(m.group(0))
        if cep and cep not in saida:
            saida.append(cep)
    return saida


# ------------------------------------------------------------------ e-mail

def normalizar_email(bruto: str) -> str:
    valor = (bruto or "").strip().strip(".,;:()[]<>").replace(" ", "").lower()
    if not valor or valor.count("@") != 1:
        return ""
    local, dominio = valor.split("@")
    if not local or "." not in dominio:
        return ""
    if len(dominio.rsplit(".", 1)[-1]) < 2:
        return ""
    if not re.fullmatch(r"[a-z0-9._%+\-]+", local):
        return ""
    if not re.fullmatch(r"[a-z0-9.\-]+", dominio):
        return ""
    return valor


def extrair_emails(texto: str) -> list[str]:
    saida: list[str] = []
    for m in _RE_EMAIL.finditer(texto or ""):
        email = normalizar_email(m.group(0))
        if email and email not in saida:
            saida.append(email)
    return saida


# ------------------------------------------------------------------ URL / redes

def _rede_da_url(url: str) -> str:
    baixo = url.lower()
    for rede, dominios in REDES.items():
        alvos = (dominios,) if isinstance(dominios, str) else dominios
        if any(d in baixo for d in alvos):
            return rede
    return ""


def normalizar_url(bruto: str) -> str:
    valor = (bruto or "").strip().strip(".,;:()[]<>").replace(" ", "")
    if not valor:
        return ""
    valor = re.sub(r"^https?://", "", valor, flags=re.IGNORECASE)
    if "@" in valor:                 # é e-mail, não site
        return ""
    if not _RE_URL.fullmatch(valor):
        return ""
    return valor.lower().rstrip("/")


def extrair_urls(texto: str) -> tuple[list[str], list[dict]]:
    """Devolve (sites, redes_sociais) — separados, cada um sem duplicata."""
    sites: list[str] = []
    redes: list[dict] = []
    vistos_rede: set[str] = set()
    for m in _RE_URL.finditer(texto or ""):
        bruto = m.group(0)
        # ignora quando o casamento faz parte de um e-mail
        inicio = m.start()
        if inicio > 0 and (texto[inicio - 1] == "@" or texto[inicio - 1].isalnum()):
            continue
        url = normalizar_url(bruto)
        if not url:
            continue
        rede = _rede_da_url(url)
        if rede:
            if url not in vistos_rede:
                vistos_rede.add(url)
                redes.append({"rede": rede, "valor": url, "usuario": _usuario_da_url(url)})
        elif url not in sites:
            sites.append(url)
    return sites, redes


def _usuario_da_url(url: str) -> str:
    partes = url.split("/")
    for parte in partes[1:]:
        parte = parte.strip()
        if parte and parte not in ("in", "company", "pages", "profile", "c", "user", "@"):
            return parte.lstrip("@")
    return ""


def extrair_arrobas(texto: str) -> list[dict]:
    """Perfis escritos como @usuario — rede indeterminada (não chutamos)."""
    saida: list[dict] = []
    vistos: set[str] = set()
    for linha in (texto or "").splitlines():
        sem_email = _RE_EMAIL.sub(" ", linha)
        for m in _RE_ARROBA.finditer(sem_email):
            usuario = m.group(1)
            if usuario.lower() in vistos:
                continue
            ctx = sem_acento(linha).lower()
            rede = ""
            for nome in REDES:
                if nome in ctx:
                    rede = nome
                    break
            vistos.add(usuario.lower())
            saida.append({"rede": rede or "perfil", "valor": "@" + usuario, "usuario": usuario})
    return saida


# ------------------------------------------------------------------ endereço

def extrair_cidade_uf(texto: str) -> tuple[str, str]:
    """Acha 'Ibitinga - SP' / 'Ibitinga/SP' no texto. ('', '') se não achar."""
    for m in _RE_CIDADE_UF.finditer(texto or ""):
        cidade = normalizar_espacos(m.group(1)).strip(" -–,.")
        uf = m.group(2).upper()
        # descarta ruído tipo "Fone SP" (cidade curta demais) ou linha inteira
        cidade = cidade.split("  ")[-1].strip()
        if len(cidade) >= 3 and not cidade.isdigit():
            return cidade, uf
    return "", ""


def extrair_logradouro(texto: str) -> dict:
    """Extrai rua/número/complemento a partir de uma linha de endereço."""
    vazio = {"logradouro": "", "numero": "", "complemento": ""}
    for linha in (texto or "").splitlines():
        limpa = normalizar_espacos(linha)
        if not limpa:
            continue
        baixo = sem_acento(limpa).lower()
        if not any(baixo.startswith(t) or f" {t}" in baixo[:24] for t in TIPOS_LOGRADOURO):
            continue
        m = re.search(r"(.+?),?\s*(?:n[ºo°.]?\s*)?(\d{1,6})\b(.*)$", limpa)
        if m:
            complemento = normalizar_espacos(m.group(3)).strip(" -–,")
            # não deixa o resto da linha (cidade/CEP) virar complemento
            if _RE_CEP.search(complemento) or len(complemento) > 40:
                complemento = ""
            return {
                "logradouro": normalizar_espacos(m.group(1)).strip(" ,-"),
                "numero": m.group(2),
                "complemento": complemento,
            }
        return {"logradouro": limpa, "numero": "", "complemento": ""}
    return vazio


def extrair_cnpj(texto: str) -> str:
    m = _RE_CNPJ.search(texto or "")
    if not m:
        return ""
    d = apenas_digitos(m.group(0))
    if len(d) != 14 or len(set(d)) == 1:
        return ""
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


# ------------------------------------------------------------------ suporte OCR

def digitos_do_texto(texto: str) -> str:
    """Sequência com todos os dígitos do texto — usada para conferir se um
    número que a IA disse realmente aparece na imagem."""
    return re.sub(r"\D", "", texto or "")


def suportado_pelo_ocr(digitos: str, digitos_ocr: str) -> bool:
    """True se a sequência de dígitos aparece no que o OCR leu."""
    if not digitos:
        return False
    if digitos in digitos_ocr:
        return True
    # tolera o DDI/zero na frente
    return digitos.lstrip("0") in digitos_ocr


def texto_suportado_pelo_ocr(valor: str, texto_ocr: str, minimo: float = 0.6) -> bool:
    """True se a maioria das palavras do valor aparece no texto do OCR."""
    if not valor:
        return False
    alvo = sem_acento(texto_ocr).lower()
    palavras = [p for p in re.split(r"\W+", sem_acento(valor).lower()) if len(p) > 2]
    if not palavras:
        return False
    acertos = sum(1 for p in palavras if p in alvo)
    return acertos / len(palavras) >= minimo
