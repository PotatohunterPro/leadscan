"""
OCR local com Tesseract (pytesseract) — roda dentro do container, sem rede.

Papel do OCR no pipeline: ler com precisão o que é TEXTO/NÚMERO (telefone,
CEP, e-mail, URL, endereço). A interpretação (qual é o nome da empresa, o que
é cargo, como o endereço se organiza) continua com o LFM2.5-VL-450M.

Se o binário do Tesseract não estiver instalado, nada quebra: as funções
devolvem texto vazio e um aviso — o VLM continua funcionando sozinho.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger("leadscan.ocr")

IDIOMAS_OCR = os.environ.get("OCR_LANGS", "por+eng")
OCR_PSM = os.environ.get("OCR_PSM", "6")          # bloco uniforme de texto
OCR_TIMEOUT = int(os.environ.get("OCR_TIMEOUT", "40"))
OCR_ATIVO = os.environ.get("OCR_ATIVO", "1") not in ("0", "false", "no")

_disponivel: bool | None = None
_idiomas_ok: str | None = None


@dataclass
class ResultadoOCR:
    texto: str = ""
    confianca: float = 0.0
    variante: str = ""
    rotacao: int = 0
    disponivel: bool = False
    avisos: list = field(default_factory=list)


def _pytesseract():
    try:
        import pytesseract  # import tardio: sem Tesseract o app continua de pé
        return pytesseract
    except Exception as exc:  # pragma: no cover - ambiente sem a lib
        logger.warning("pytesseract indisponível: %s", exc)
        return None


def disponivel() -> bool:
    """True se pytesseract + binário do tesseract estão utilizáveis (cacheado)."""
    global _disponivel
    if _disponivel is not None:
        return _disponivel
    if not OCR_ATIVO:
        _disponivel = False
        return False
    pt = _pytesseract()
    if pt is None:
        _disponivel = False
        return False
    caminho = os.environ.get("TESSERACT_CMD")
    if caminho:
        pt.pytesseract.tesseract_cmd = caminho
    if not shutil.which(pt.pytesseract.tesseract_cmd or "tesseract"):
        logger.warning("Binário do tesseract não encontrado — OCR desligado")
        _disponivel = False
        return False
    try:
        pt.get_tesseract_version()
        _disponivel = True
    except Exception as exc:  # pragma: no cover
        logger.warning("Tesseract não respondeu: %s", exc)
        _disponivel = False
    return _disponivel


def idiomas() -> str:
    """Usa por+eng quando o pacote de português existe; senão cai para eng."""
    global _idiomas_ok
    if _idiomas_ok is not None:
        return _idiomas_ok
    _idiomas_ok = IDIOMAS_OCR
    pt = _pytesseract()
    if pt is None:
        return _idiomas_ok
    try:
        instalados = set(pt.get_languages(config=""))
        pedidos = [i for i in IDIOMAS_OCR.split("+") if i in instalados]
        if pedidos:
            _idiomas_ok = "+".join(pedidos)
        elif instalados:
            _idiomas_ok = "eng" if "eng" in instalados else sorted(instalados)[0]
    except Exception:  # pragma: no cover
        pass
    logger.info("OCR usando idiomas: %s", _idiomas_ok)
    return _idiomas_ok


def _pontuar(texto: str, confianca: float) -> float:
    """Pontua uma leitura: confiança média + volume de caracteres úteis."""
    uteis = sum(1 for c in texto if c.isalnum())
    return confianca + min(uteis, 400) / 10.0


def _ler_imagem(img, config_extra: str = "") -> tuple[str, float]:
    pt = _pytesseract()
    if pt is None:
        return "", 0.0
    config = f"--oem 3 --psm {OCR_PSM} {config_extra}".strip()
    try:
        dados = pt.image_to_data(
            img,
            lang=idiomas(),
            config=config,
            output_type=pt.Output.DICT,
            timeout=OCR_TIMEOUT,
        )
    except Exception as exc:
        logger.warning("Falha no OCR: %s", exc)
        return "", 0.0

    palavras = dados.get("text", [])
    confiancas = dados.get("conf", [])
    linhas: dict[tuple, list[str]] = {}
    validas: list[float] = []
    for i, palavra in enumerate(palavras):
        texto = (palavra or "").strip()
        try:
            conf = float(confiancas[i])
        except (TypeError, ValueError, IndexError):
            conf = -1.0
        if not texto or conf < 0:
            continue
        chave = (
            dados.get("block_num", [0] * len(palavras))[i],
            dados.get("par_num", [0] * len(palavras))[i],
            dados.get("line_num", [0] * len(palavras))[i],
        )
        linhas.setdefault(chave, []).append(texto)
        validas.append(conf)

    texto_final = "\n".join(" ".join(p) for _, p in sorted(linhas.items()))
    media = sum(validas) / len(validas) if validas else 0.0
    return texto_final.strip(), media


def ler(preparada, tentar_rotacoes: bool = True) -> ResultadoOCR:
    """Roda o OCR nas variantes da imagem e devolve a MELHOR leitura.

    'preparada' é um app.imagem.ImagemPreparada. Rotações só são testadas
    quando a primeira leitura vem fraca (economia de CPU/memória).
    """
    if not disponivel():
        return ResultadoOCR(
            disponivel=False,
            avisos=["OCR indisponível (Tesseract não instalado) — usei só a IA de visão."],
        )

    melhor = ResultadoOCR(disponivel=True)
    melhor_pontos = -1.0

    for nome, img in preparada.variantes_ocr:
        texto, conf = _ler_imagem(img)
        pontos = _pontuar(texto, conf)
        logger.info(
            "OCR %s/%s: %d chars, conf %.1f", preparada.lado, nome, len(texto), conf
        )
        if pontos > melhor_pontos:
            melhor_pontos = pontos
            melhor = ResultadoOCR(
                texto=texto, confianca=conf, variante=nome, disponivel=True
            )

    # leitura fraca? a foto pode estar deitada/de cabeça pra baixo
    if tentar_rotacoes and melhor_pontos < 40 and preparada.variantes_ocr:
        base = preparada.variantes_ocr[0][1]
        for graus in (90, 180, 270):
            girada = base.rotate(-graus, expand=True)
            try:
                texto, conf = _ler_imagem(girada)
                pontos = _pontuar(texto, conf)
                logger.info("OCR %s rotacionado %d°: %d chars, conf %.1f",
                            preparada.lado, graus, len(texto), conf)
                if pontos > melhor_pontos:
                    melhor_pontos = pontos
                    melhor = ResultadoOCR(
                        texto=texto, confianca=conf,
                        variante="rotacao", rotacao=graus, disponivel=True,
                    )
            finally:
                girada.close()

    if not melhor.texto:
        melhor.avisos.append(
            "O OCR não conseguiu ler texto nesta foto (iluminação/foco?)."
        )
    return melhor
