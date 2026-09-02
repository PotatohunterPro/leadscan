"""
Pré-processamento de imagem para OCR e para o modelo de visão (LFM2.5-VL).

Regras do projeto (máquina com ~1 GB de RAM):
  * nada de OpenCV/numpy/PyTorch — só Pillow;
  * frente e verso são processados SEQUENCIALMENTE (nunca em paralelo);
  * a imagem do OCR NÃO é reduzida para 1024px: OCR precisa de resolução
    (1600–1800px no maior lado), enquanto o VLM continua recebendo 1024px
    para não estourar o timeout/memória do modelo.

Pipeline:  FOTO -> EXIF/orientação -> escala -> cinza/contraste/nitidez
           -> (threshold quando necessário) -> OCR
                                            \-> versão 1024px -> VLM
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

logger = logging.getLogger("leadscan.imagem")

# ---------------------------------------------------------------- limites
MAX_LADO_VLM = 1024          # entrada do modelo de visão local (LFM2.5-VL)
MAX_LADO_OCR = 1800          # teto para o Tesseract (mantém memória sob controle)
MIN_LADO_OCR = 1100          # upscale de fotos pequenas: texto minúsculo não é lido
QUALIDADE_JPEG = 80
MAX_PIXELS = 40_000_000      # trava anti-bomba de descompressão (~40MP)


@dataclass
class ImagemPreparada:
    """Resultado do pré-processamento de UMA foto (frente ou verso)."""

    lado: str
    vlm_jpeg: bytes                       # 1024px, colorida — vai pro modelo de visão
    arquivo_jpeg: bytes                   # versão para guardar em data/fotos
    largura: int = 0
    altura: int = 0
    variantes_ocr: list = field(default_factory=list)   # [(nome, PIL.Image)]

    def liberar(self) -> None:
        """Fecha as imagens do OCR — importante com 1 GB de RAM."""
        for _, img in self.variantes_ocr:
            try:
                img.close()
            except Exception:  # pragma: no cover - defensivo
                pass
        self.variantes_ocr = []


def abrir(imagem_bytes: bytes) -> Image.Image:
    """Abre a imagem corrigindo EXIF/orientação. Levanta ValueError se inválida."""
    if not imagem_bytes:
        raise ValueError("Arquivo enviado está vazio")
    try:
        img = Image.open(io.BytesIO(imagem_bytes))
        img.load()
    except UnidentifiedImageError as exc:
        raise ValueError("Arquivo enviado não é uma imagem válida") from exc
    except OSError as exc:
        raise ValueError(f"Não consegui ler a imagem: {exc}") from exc

    if img.width * img.height > MAX_PIXELS:
        raise ValueError("Imagem com resolução alta demais (máximo ~40 megapixels)")

    # exif_transpose devolve uma nova imagem já rotacionada conforme o EXIF
    corrigida = ImageOps.exif_transpose(img)
    if corrigida is not img:
        img.close()
        img = corrigida
    return img.convert("RGB")


def escalar(img: Image.Image, max_lado: int, min_lado: int = 0) -> Image.Image:
    """Redimensiona mantendo proporção: teto em max_lado, piso em min_lado."""
    maior = max(img.width, img.height)
    if maior == 0:
        return img.copy()
    fator = 1.0
    if maior > max_lado:
        fator = max_lado / maior
    elif min_lado and maior < min_lado:
        fator = min(min_lado / maior, 3.0)   # nunca ampliar mais que 3x
    if abs(fator - 1.0) < 0.01:
        return img.copy()
    novo = (max(1, round(img.width * fator)), max(1, round(img.height * fator)))
    filtro = Image.Resampling.LANCZOS if fator < 1 else Image.Resampling.BICUBIC
    return img.resize(novo, filtro)


def para_jpeg(img: Image.Image, qualidade: int = QUALIDADE_JPEG) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=qualidade, optimize=True)
    return buf.getvalue()


def realcar(img: Image.Image) -> Image.Image:
    """Cinza + autocontraste + nitidez — base do OCR."""
    cinza = ImageOps.grayscale(img)
    cinza = ImageOps.autocontrast(cinza, cutoff=1)
    cinza = ImageEnhance.Contrast(cinza).enhance(1.35)
    cinza = cinza.filter(ImageFilter.UnsharpMask(radius=1.6, percent=140, threshold=3))
    return cinza


def limiar_otsu(cinza: Image.Image) -> int:
    """Calcula o limiar de Otsu a partir do histograma (sem numpy)."""
    hist = cinza.histogram()[:256]
    total = sum(hist) or 1
    soma_total = sum(i * h for i, h in enumerate(hist))
    soma_b = 0.0
    peso_b = 0
    melhor_var = -1.0
    melhor_limiar = 128
    for i in range(256):
        peso_b += hist[i]
        if peso_b == 0:
            continue
        peso_f = total - peso_b
        if peso_f == 0:
            break
        soma_b += i * hist[i]
        media_b = soma_b / peso_b
        media_f = (soma_total - soma_b) / peso_f
        var = peso_b * peso_f * (media_b - media_f) ** 2
        if var > melhor_var:
            melhor_var = var
            melhor_limiar = i
    return melhor_limiar


def binarizar(cinza: Image.Image) -> Image.Image:
    """Threshold global (Otsu). Usado só como variante — cartão colorido
    costuma ler melhor em cinza, mas foto com pouca luz melhora muito aqui."""
    limiar = limiar_otsu(cinza)
    return cinza.point(lambda p, t=limiar: 255 if p > t else 0, mode="L")


def _contraste_baixo(cinza: Image.Image) -> bool:
    """Heurística barata de 'pouca iluminação': desvio pequeno no histograma."""
    hist = cinza.histogram()[:256]
    total = sum(hist) or 1
    media = sum(i * h for i, h in enumerate(hist)) / total
    var = sum(h * (i - media) ** 2 for i, h in enumerate(hist)) / total
    return var ** 0.5 < 45 or media < 70 or media > 200


def preparar(imagem_bytes: bytes, lado: str = "frente") -> ImagemPreparada:
    """Roda o pipeline completo de UMA foto e devolve as versões prontas."""
    original = abrir(imagem_bytes)
    try:
        # --- versão para o modelo de visão (1024px, colorida)
        vlm = escalar(original, MAX_LADO_VLM)
        vlm_jpeg = para_jpeg(vlm)
        arquivo_jpeg = vlm_jpeg          # é a mesma coisa que já era salva antes
        vlm.close()

        # --- versão para OCR (até 1800px, cinza realçado)
        grande = escalar(original, MAX_LADO_OCR, MIN_LADO_OCR)
        cinza = realcar(grande)
        grande.close()

        variantes: list[tuple[str, Image.Image]] = [("cinza", cinza)]
        if _contraste_baixo(cinza):
            variantes.append(("threshold", binarizar(cinza)))
            logger.info("Foto %s com contraste baixo — variante threshold ativada", lado)

        return ImagemPreparada(
            lado=lado,
            vlm_jpeg=vlm_jpeg,
            arquivo_jpeg=arquivo_jpeg,
            largura=original.width,
            altura=original.height,
            variantes_ocr=variantes,
        )
    finally:
        original.close()
