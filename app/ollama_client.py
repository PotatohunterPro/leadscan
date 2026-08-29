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
    "OLLAMA_MODEL", "hf.co/LiquidAI/LFM2.5-VL-450M-GGUF:Q8_0"
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


async def extrair_dados(imagem_bytes: bytes) -> dict:
    """Envia a imagem ao modelo de visão local e devolve os campos extraídos.

    Levanta httpx.HTTPError se o Ollama não responder (o chamador converte
    em 502) e ValueError se a resposta não for JSON válido (o chamador
    converte em 422). Nunca retorna campos obrigatórios ausentes.
    """
    img_b64 = base64.b64encode(imagem_bytes).decode("ascii")
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": PROMPT,
        "images": [img_b64],
        "stream": False,
        "options": {"temperature": 0.1},
    }
    logger.info(
        "Chamando Ollama modelo=%s imagem=%d bytes", OLLAMA_MODEL, len(imagem_bytes)
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
