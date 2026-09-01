"""Testes do pré-processamento de imagem (Fase 5.3 do PLANO-V2).

Cobre o item 11: correção EXIF/orientação, escala (1600–1800px pro OCR,
1024px pro VLM), cinza/contraste/nitidez e degradação graciosa p/ imagem
inválida. Só Pillow — nada de OpenCV/numpy.
"""

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="leadscan-test-img-")
os.environ["DATA_DIR"] = _TMP

from PIL import Image  # noqa: E402

from app import imagem as img_mod  # noqa: E402


def _jpeg(largura: int, altura: int, cor: str = "white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (largura, altura), cor).save(buf, format="JPEG")
    return buf.getvalue()


class TestAbrir(unittest.TestCase):
    def test_imagem_invalida_levanta_value_error(self):
        with self.assertRaises(ValueError):
            img_mod.abrir(b"isto nao e uma imagem")

    def test_arquivo_vazio(self):
        with self.assertRaises(ValueError):
            img_mod.abrir(b"")

    def test_corrige_orientacao_exif(self):
        """Foto de celular deitada (EXIF 6) abre já rotacionada (item 11)."""
        buf = io.BytesIO()
        img = Image.new("RGB", (100, 200), "red")
        exif = Image.Exif()
        exif[0x0112] = 6  # orientação: 90° no sentido horário
        img.save(buf, format="JPEG", exif=exif)
        aberta = img_mod.abrir(buf.getvalue())
        try:
            self.assertEqual(aberta.width, 200)   # transposto
            self.assertEqual(aberta.height, 100)
            self.assertEqual(aberta.mode, "RGB")
        finally:
            aberta.close()


class TestEscalar(unittest.TestCase):
    def test_teto_max_lado(self):
        img = Image.new("RGB", (2000, 1000))
        try:
            menor = img_mod.escalar(img, 1024)
            try:
                self.assertLessEqual(menor.width, 1024)
                self.assertEqual(menor.width, 1024)   # proporção mantida
                self.assertEqual(menor.height, 512)
            finally:
                menor.close()
        finally:
            img.close()

    def test_piso_min_lado(self):
        img = Image.new("RGB", (200, 100))
        try:
            maior = img_mod.escalar(img, 1800, 1100)
            try:
                # nunca ampliar mais que 3x
                self.assertEqual(maior.width, 600)
                self.assertEqual(maior.height, 300)
            finally:
                maior.close()
        finally:
            img.close()

    def test_nao_mexe_em_imagem_ja_no_limite(self):
        img = Image.new("RGB", (800, 600))
        try:
            copia = img_mod.escalar(img, 1024)
            try:
                self.assertEqual((copia.width, copia.height), (800, 600))
            finally:
                copia.close()
        finally:
            img.close()


class TestPreparar(unittest.TestCase):
    def test_vlm_jpeg_max_1024(self):
        prep = img_mod.preparar(_jpeg(2400, 1200), "frente")
        try:
            from PIL import Image as PI
            vlm = PI.open(io.BytesIO(prep.vlm_jpeg))
            try:
                self.assertLessEqual(max(vlm.width, vlm.height), 1024)
                self.assertEqual(prep.largura, 2400)
                self.assertEqual(prep.altura, 1200)
            finally:
                vlm.close()
        finally:
            prep.liberar()

    def test_variantes_ocr_tem_cinza(self):
        prep = img_mod.preparar(_jpeg(1200, 800, "white"), "frente")
        try:
            nomes = [nome for nome, _ in prep.variantes_ocr]
            self.assertIn("cinza", nomes)
            self.assertEqual(prep.lado, "frente")
        finally:
            prep.liberar()

    def test_liberar_fecha_variantes(self):
        prep = img_mod.preparar(_jpeg(800, 600), "verso")
        prep.liberar()
        self.assertEqual(prep.variantes_ocr, [])

    def test_imagem_invalida_na_preparar(self):
        with self.assertRaises(ValueError):
            img_mod.preparar(b"lixo")

    def test_para_jpeg_redondo(self):
        img = Image.new("RGB", (100, 100), "blue")
        try:
            jpeg = img_mod.para_jpeg(img)
            self.assertTrue(jpeg.startswith(b"\xff\xd8"))  # magic JPEG
        finally:
            img.close()


if __name__ == "__main__":
    unittest.main()
