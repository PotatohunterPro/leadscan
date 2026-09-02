"""
Cliente do Ollama — integração com o modelo de visão local.

Fonte única de verdade para endereço/modelo do Ollama. O container alcança o
Ollama do host via host.docker.internal:11434 (configurado no docker-compose.yml
com extra_hosts). Os endereços/modelo podem ser sobrescritos por variáveis de
ambiente (útil em dev local e no status do admin).
"""

import base64
import json
import logging
import os
import re

import httpx

logger = logging.getLogger("leadscan.ollama")

OLLAMA_URL = os.environ.get(
    "OLLAMA_URL", "http://127.0.0.1:11434/api/generate"
)
OLLAMA_TAGS_URL = os.environ.get(
    "OLLAMA_TAGS_URL", "http://127.0.0.1:11434/api/tags"
)
OLLAMA_MODEL = os.environ.get(
    "OLLAMA_MODEL", "hf.co/LiquidAI/LFM2.5-VL-450M-Extract-GGUF:F16"
)
TIMEOUT_SEGUNDOS = float(os.environ.get("OLLAMA_TIMEOUT", "90"))

CAMPOS_ESPERADOS = [
    "nome_empresa",
    "nome_contato",
    "telefone",
    "whatsapp",
    "email",
    "site",
    "endereco",
    "cidade",
    "ramo_atividade",
    "redes_sociais",
]

PROMPT = (
    "Examine a imagem (cartão de visita) e responda em JSON estrito, "
    "sem texto adicional, com as chaves: nome_empresa, nome_contato, "
    "telefone, whatsapp, email, site, endereco, cidade, ramo_atividade, "
    "redes_sociais. Deixe vazio (string vazia) o que não encontrar."
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extrair_json_da_resposta(texto: str) -> dict:
    """Extrai e valida o objeto JSON da resposta crua do modelo.

    O modelo às vezes envolve o JSON em ```json ... ```, às vezes vem com
    texto antes/depois. Tratamos de forma defensiva e levantamos ValueError
    com mensagem clara quando não dá para extrair (resposta vazia,
    malformada, ou que não é um objeto).
    """
    if not texto or not texto.strip():
        raise ValueError("Ollama retornou resposta vazia")

    candidato = texto.strip()
    m = _FENCE_RE.search(candidato)
    if m:
        candidato = m.group(1).strip()

    dados = None
    try:
        dados = json.loads(candidato)
    except json.JSONDecodeError:
        inicio, fim = candidato.find("{"), candidato.rfind("}")
        if inicio != -1 and fim > inicio:
            try:
                dados = json.loads(candidato[inicio : fim + 1])
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Resposta do Ollama não é JSON válido: {exc}"
                ) from exc
        else:
            trecho = texto[:200] if texto.strip() else "<vazio>"
            raise ValueError(
                "Resposta do Ollama não contém um objeto JSON: " + trecho
            )

    if not isinstance(dados, dict):
        raise ValueError(
            "Resposta do Ollama não é um objeto JSON "
            f"(recebido: {type(dados).__name__})"
        )

    # normaliza: tudo string, chaves vazias quando ausentes/nulas
    dados = {
        chave: (str(valor).strip() if valor is not None else "")
        for chave, valor in dados.items()
    }
    for campo in CAMPOS_ESPERADOS:
        dados.setdefault(campo, "")
    return dados


async def extrair_dados(imagens: list[bytes]) -> dict:
    """Envia uma ou mais imagens ao modelo de visão local e devolve os campos.

    A primeira imagem deve ser a frente; a segunda (se houver) o verso.

    Levanta httpx.HTTPError se o Ollama não responder (o chamador converte
    em 502) e ValueError se a resposta não for JSON válido (o chamador
    converte em 422). Nunca retorna campos obrigatórios ausentes.
    """
    imgs_b64 = [base64.b64encode(im).decode("ascii") for im in imagens]
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": PROMPT,
        "images": imgs_b64,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    logger.info(
        "Chamando Ollama modelo=%s imagens=%d total=%d bytes",
        OLLAMA_MODEL, len(imagens), sum(len(i) for i in imagens),
    )
    async with httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS) as client:
        resp = await client.post(OLLAMA_URL, json=payload)
        resp.raise_for_status()
        texto = resp.json().get("response", "")
    logger.info("Ollama respondeu (%d caracteres)", len(texto))
    return extrair_json_da_resposta(texto)


async def listar_modelos() -> list[str]:
    """Consulta /api/tags do Ollama — usado pelo status do painel admin.

    Levanta httpx.HTTPError se o Ollama estiver inacessível.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(OLLAMA_TAGS_URL)
        resp.raise_for_status()
        modelos = resp.json().get("models", [])
        return [m.get("name", "") for m in modelos]

# --------------------------------------------------------------- cartão (novo)

# Campos que o modelo tenta preencher na análise do cartão. Continua sendo um
# modelo local pequeno (LFM2.5-VL): o prompt é curto de propósito e a
# validação pesada acontece depois, em app/validadores.py.
CAMPOS_CARTAO = [
    "nome_empresa",
    "nome_fantasia",
    "nome_contato",
    "cargo",
    "telefones",
    "whatsapp",
    "email",
    "site",
    "endereco",
    "bairro",
    "cidade",
    "uf",
    "cep",
    "redes_sociais",
    "ramo_atividade",
    "outras_informacoes",
]

PROMPT_CARTAO = (
    "Você está lendo a foto de um cartão de visita brasileiro (frente e, se "
    "houver, verso da MESMA empresa). Responda SOMENTE com um objeto JSON, sem "
    "explicações, usando exatamente estas chaves: nome_empresa, nome_fantasia, "
    "nome_contato, cargo, telefones, whatsapp, email, site, endereco, bairro, "
    "cidade, uf, cep, redes_sociais, ramo_atividade, outras_informacoes.\n"
    "Regras: 'telefones' e 'outras_informacoes' são listas; copie os textos "
    "exatamente como aparecem; NUNCA invente ou complete números; use string "
    "vazia quando não encontrar; em 'outras_informacoes' coloque frases do "
    "cartão que não cabem nos outros campos (slogan, 'desde 1998', "
    "'representante', horários etc.)."
)


def _texto_ocr_para_prompt(texto_ocr: str, limite: int = 1200) -> str:
    texto = (texto_ocr or "").strip()
    if not texto:
        return ""
    if len(texto) > limite:
        texto = texto[:limite] + "…"
    return (
        "\n\nO OCR leu o seguinte texto nesta imagem (use como apoio, ele é "
        "confiável para números e endereços):\n" + texto
    )


async def extrair_dados_cartao(imagens: list[bytes], texto_ocr: str = "") -> dict:
    """Interpretação visual do cartão pelo modelo local.

    Recebe a frente (e o verso, quando houver) como UM cartão só e o texto do
    OCR como apoio. Devolve o JSON já normalizado (strings/listas), sem
    validar números — quem valida é app/validadores.py.
    """
    imgs_b64 = [base64.b64encode(im).decode("ascii") for im in imagens]
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": PROMPT_CARTAO + _texto_ocr_para_prompt(texto_ocr),
        "images": imgs_b64,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    logger.info(
        "Chamando Ollama (cartão) modelo=%s imagens=%d ocr=%d chars",
        OLLAMA_MODEL, len(imagens), len(texto_ocr or ""),
    )
    async with httpx.AsyncClient(timeout=TIMEOUT_SEGUNDOS) as client:
        resp = await client.post(OLLAMA_URL, json=payload)
        resp.raise_for_status()
        texto = resp.json().get("response", "")
    logger.info("Ollama respondeu (%d caracteres)", len(texto))
    return normalizar_json_cartao(extrair_json_bruto(texto))


def extrair_json_bruto(texto: str) -> dict:
    """Igual a extrair_json_da_resposta, mas sem forçar os campos antigos.

    Mantida separada para não mexer no contrato de /extract legado.
    """
    if not texto or not texto.strip():
        raise ValueError("Ollama retornou resposta vazia")
    candidato = texto.strip()
    m = _FENCE_RE.search(candidato)
    if m:
        candidato = m.group(1).strip()
    try:
        dados = json.loads(candidato)
    except json.JSONDecodeError:
        inicio, fim = candidato.find("{"), candidato.rfind("}")
        if inicio != -1 and fim > inicio:
            try:
                dados = json.loads(candidato[inicio : fim + 1])
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Resposta do Ollama não é JSON válido: {exc}"
                ) from exc
        else:
            trecho = texto[:200] if texto.strip() else "<vazio>"
            raise ValueError(
                "Resposta do Ollama não contém um objeto JSON: " + trecho
            )
    if not isinstance(dados, dict):
        raise ValueError(
            "Resposta do Ollama não é um objeto JSON "
            f"(recebido: {type(dados).__name__})"
        )
    return dados


def normalizar_json_cartao(dados: dict) -> dict:
    """Normaliza o JSON do modelo: strings limpas e listas de strings.

    O modelo pequeno erra o formato com frequência (manda string onde devia
    ser lista, dicionário aninhado, null...). Aqui isso vira algo previsível
    em vez de exceção.
    """
    saida: dict = {}
    for chave, valor in (dados or {}).items():
        chave = str(chave).strip()
        if isinstance(valor, list):
            saida[chave] = [
                str(v).strip() for v in _achatar(valor) if str(v).strip()
            ]
        elif isinstance(valor, dict):
            saida[chave] = [
                f"{k}: {v}".strip() for k, v in valor.items() if str(v).strip()
            ]
        elif valor is None:
            saida[chave] = ""
        else:
            saida[chave] = str(valor).strip()
    for campo in CAMPOS_CARTAO:
        if campo not in saida:
            saida[campo] = [] if campo in ("telefones", "outras_informacoes", "redes_sociais") else ""
    return saida


def _achatar(valores: list) -> list:
    plano: list = []
    for v in valores:
        if isinstance(v, list):
            plano.extend(_achatar(v))
        elif isinstance(v, dict):
            plano.extend(str(x) for x in v.values())
        else:
            plano.append(v)
    return plano

