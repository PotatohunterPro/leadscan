"""Testes da fusão OCR + VLM e das sugestões "Usar no Lead" (Fase 5.2).

Cobre os itens 12, 13 e 14 do V2:
  - múltiplos telefones preservados (nunca sobrescrever um pelo outro);
  - número que a IA disse mas NÃO aparece no OCR é descartado (regra 13);
  - linhas que não viraram campo vão para "outras_informacoes" (item 14);
  - o info é SÓ do cartão — não toca em nada do lead.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="leadscan-test-cartao-")
os.environ["DATA_DIR"] = _TMP

from app import cartao  # noqa: E402
from app.cartao import fundir, montar_sugestoes, para_campos_legado  # noqa: E402


TEXTO_OCR = (
    "Arte & Tear\n"
    "João da Silva\n"
    "Proprietário\n"
    "(16) 3341-2520\n"
    "(16) 99726-9098\n"
    "www.artetear.com.br\n"
    "Desde 1998"
)

BRUTO_VLM = {
    "nome_empresa": "Arte & Tear",
    "nome_contato": "João da Silva",
    "cargo": "Proprietário",
    "telefones": ["(16) 3341-2520", "(16) 99796-5265"],  # 2º NÃO está no OCR
    "whatsapp": "(16) 99726-9098",
    "site": "www.artetear.com.br",
}


class TestFundir(unittest.TestCase):
    def setUp(self):
        self.info = fundir(
            texto_ocr=TEXTO_OCR,
            bruto_vlm=BRUTO_VLM,
            ocr_ok=True,
            texto_frente=TEXTO_OCR,
        )

    def test_multiplos_telefones_preservados(self):
        """Item 12: todos os telefones do cartão coexistem."""
        digitos = {t["digitos"] for t in self.info["telefones"]}
        self.assertEqual(
            digitos, {"1633412520", "16997269098"}
        )
        # o VLM não sobrescreveu o fixo do OCR
        fixo = next(t for t in self.info["telefones"] if t["digitos"] == "1633412520")
        self.assertEqual(fixo["tipo"], "fixo")

    def test_numero_inventado_pelo_vlm_descartado(self):
        """Item 13: (16) 99796-5265 não aparece no OCR → descartado."""
        digitos = {t["digitos"] for t in self.info["telefones"]}
        self.assertNotIn("16997965265", digitos)

    def test_whatsapp_do_vlm_confirmado_pelo_ocr(self):
        wpp = next(t for t in self.info["telefones"] if t["digitos"] == "16997269098")
        self.assertEqual(wpp["tipo"], "whatsapp")
        self.assertIn("vlm", wpp["origem"])

    def test_vlm_sem_ocr_aceita_numero(self):
        """Sem OCR para conferir, o número do VLM entra com confiança menor."""
        info = fundir(
            texto_ocr="",
            bruto_vlm={"telefones": ["(16) 99726-9098"]},
            ocr_ok=False,
        )
        self.assertEqual(len(info["telefones"]), 1)
        self.assertEqual(info["telefones"][0]["confianca"], 0.5)

    def test_outras_informacoes_guardam_linhas_sobrando(self):
        """Item 14: "Desde 1998" não virou campo → vai para outras_informacoes."""
        textos = [o["texto"] for o in self.info["outras_informacoes"]]
        self.assertIn("Desde 1998", textos)
        # linhas que viraram campo NÃO repetem aqui
        for usada in ("Arte & Tear", "(16) 3341-2520", "(16) 99726-9098"):
            self.assertNotIn(usada, textos)

    def test_empresa_e_pessoa_interpretados(self):
        self.assertEqual(self.info["empresa"]["nome"], "Arte & Tear")
        self.assertEqual(self.info["pessoa"]["nome"], "João da Silva")
        self.assertEqual(self.info["pessoa"]["cargo"], "Proprietário")

    def test_info_eh_so_do_cartao(self):
        """O info NÃO contém campos do lead — nada é tocado por engano."""
        self.assertNotIn("anotacoes", self.info)
        self.assertNotIn("qual_sistema", self.info)
        self.assertNotIn("aceita_demonstracao", self.info)

    def test_avisos_chegam_ao_cartao(self):
        info = fundir(
            texto_ocr="texto qualquer",
            bruto_vlm={},
            ocr_ok=True,
            avisos=["A IA de visão não respondeu (TimeoutError)."],
        )
        self.assertIn("A IA de visão não respondeu (TimeoutError).", info["avisos"])


class TestSugestoes(unittest.TestCase):
    def setUp(self):
        self.info = fundir(
            texto_ocr=TEXTO_OCR,
            bruto_vlm=BRUTO_VLM,
            ocr_ok=True,
            texto_frente=TEXTO_OCR,
        )
        self.sugestoes = self.info["sugestoes"]

    def test_pares_campo_valor(self):
        pares = {s["campo"]: s["valor"] for s in self.sugestoes}
        self.assertEqual(pares["nome_empresa"], "Arte & Tear")
        self.assertEqual(pares["nome_contato"], "João da Silva")
        self.assertEqual(pares["cargo"], "Proprietário")
        self.assertEqual(pares["whatsapp"], "(16) 99726-9098")
        self.assertEqual(pares["telefone"], "(16) 3341-2520")

    def test_sugestoes_sao_rotulos_de_acao(self):
        for s in self.sugestoes:
            self.assertTrue(s["rotulo"].startswith("Usar"))
            self.assertTrue(s["valor"])

    def test_montar_sugestoes_direto(self):
        info = cartao.info_vazia()
        info["empresa"]["nome"] = "X"
        info["pessoa"]["nome"] = "Maria"
        info["pessoa"]["cargo"] = "Gerente"
        info["telefones"] = [{"numero": "(11) 99999-8888", "tipo": "whatsapp"}]
        info["emails"] = [{"valor": "m@x.com"}]
        info["sites"] = [{"valor": "www.x.com"}]
        info["redes_sociais"] = [{"valor": "instagram.com/x"}]
        info["endereco"]["texto"] = "Rua A, 1"
        info["endereco"]["cidade"] = "São Paulo"
        sugs = montar_sugestoes(info)
        campos = {s["campo"] for s in sugs}
        self.assertEqual(
            campos,
            {"nome_empresa", "nome_contato", "cargo", "whatsapp", "email",
             "site", "redes_sociais", "endereco", "cidade"},
        )


class TestLegado(unittest.TestCase):
    def test_para_campos_legado_formato_antigo(self):
        info = fundir(
            texto_ocr=TEXTO_OCR,
            bruto_vlm=BRUTO_VLM,
            ocr_ok=True,
        )
        legado = para_campos_legado(info)
        self.assertEqual(legado["nome_empresa"], "Arte & Tear")
        self.assertEqual(legado["nome_contato"], "João da Silva")
        self.assertEqual(legado["telefone"], "(16) 3341-2520")
        self.assertEqual(legado["whatsapp"], "(16) 99726-9098")
        self.assertEqual(legado["site"], "www.artetear.com.br")


if __name__ == "__main__":
    unittest.main()
