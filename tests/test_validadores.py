"""Testes dos validadores determinísticos (Fase 5.1 do PLANO-V2).

Regras do V2 (item 13): telefone/CEP/e-mail/URL/rede passam por validação
determinística; a IA nunca inventa número; número parcial não é completado.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="leadscan-test-val-")
os.environ["DATA_DIR"] = _TMP

from app import validadores as val  # noqa: E402


class TestTelefone(unittest.TestCase):
    def test_fixo_valido_com_ddd(self):
        tel = val.normalizar_telefone("(16) 3341-2520")
        self.assertIsNotNone(tel)
        self.assertEqual(tel["digitos"], "1633412520")
        self.assertEqual(tel["tipo"], "fixo")
        self.assertEqual(tel["numero"], "(16) 3341-2520")
        self.assertFalse(tel["parcial"])

    def test_celular_valido_com_ddd(self):
        tel = val.normalizar_telefone("(16) 99726-9098")
        self.assertIsNotNone(tel)
        self.assertEqual(tel["digitos"], "16997269098")
        self.assertEqual(tel["tipo"], "celular")
        self.assertEqual(tel["numero"], "(16) 99726-9098")

    def test_ddd_invalido(self):
        self.assertIsNone(val.normalizar_telefone("(10) 3341-2520"))
        self.assertIsNone(val.normalizar_telefone("(00) 3341-2520"))

    def test_digitos_repetidos_eh_lixo(self):
        self.assertIsNone(val.normalizar_telefone("99999-9999"))
        self.assertIsNone(val.normalizar_telefone("(16) 0000-0000"))

    def test_sem_ddd_fica_parcial_nunca_completado(self):
        tel = val.normalizar_telefone("3341-2520")
        self.assertIsNotNone(tel)
        self.assertTrue(tel["parcial"])
        self.assertEqual(tel["digitos"], "33412520")
        # NUNCA completa com DDD
        self.assertEqual(tel["e164"], "")

    def test_celular_sem_nove_descartado(self):
        # 11 dígitos cujo 9º dígito não é 9 = número inventado/lixo
        self.assertIsNone(val.normalizar_telefone("(16) 53412-5200"))

    def test_ddi_55_removido(self):
        tel = val.normalizar_telefone("+55 16 99726-9098")
        self.assertEqual(tel["digitos"], "16997269098")
        self.assertEqual(tel["e164"], "+5516997269098")

    def test_e164(self):
        tel = val.normalizar_telefone("16 99726 9098")
        self.assertEqual(tel["e164"], "+5516997269098")

    def test_multiplos_telefones_no_mesmo_texto(self):
        texto = (
            "Tel: (16) 3341-2520\n"
            "WhatsApp: (16) 99726-9098\n"
            "Celular: (16) 99796-5265"
        )
        tels = val.extrair_telefones(texto)
        self.assertEqual(len(tels), 3)
        digitos = {t["digitos"] for t in tels}
        self.assertEqual(
            digitos, {"1633412520", "16997269098", "16997965265"}
        )

    def test_tipo_pelo_contexto(self):
        texto = (
            "WhatsApp: (16) 99726-9098\n"
            "Tel: (16) 3341-2520\n"
            "Cel: (16) 99796-5265\n"
            "(16) 99711-2233"
        )
        tels = {t["digitos"]: t["tipo"] for t in val.extrair_telefones(texto)}
        self.assertEqual(tels["16997269098"], "whatsapp")
        self.assertEqual(tels["1633412520"], "fixo")
        self.assertEqual(tels["16997965265"], "celular")
        self.assertEqual(tels["16997112233"], "celular")  # sem palavra = base

    def test_cep_nao_vira_telefone(self):
        texto = "CEP 14940-145\n(16) 3341-2520"
        tels = val.extrair_telefones(texto)
        self.assertEqual(len(tels), 1)
        self.assertEqual(tels[0]["digitos"], "1633412520")

    def test_duplicado_nao_repete(self):
        texto = "(16) 3341-2520\n(16) 3341-2520"
        self.assertEqual(len(val.extrair_telefones(texto)), 1)


class TestCep(unittest.TestCase):
    def test_cep_valido(self):
        self.assertEqual(val.normalizar_cep("14940-145"), "14940-145")
        self.assertEqual(val.normalizar_cep("14940145"), "14940-145")

    def test_cep_invalido(self):
        self.assertEqual(val.normalizar_cep("123"), "")
        self.assertEqual(val.normalizar_cep("11111-111"), "")  # repetido

    def test_extrair_cep_do_texto(self):
        self.assertEqual(val.extrair_ceps("Centro, CEP 14940-145"), ["14940-145"])


class TestEmail(unittest.TestCase):
    def test_email_valido(self):
        self.assertEqual(
            val.normalizar_email("contato@artetear.com.br"),
            "contato@artetear.com.br",
        )
        self.assertEqual(val.normalizar_email(" Contato@Loja.com "), "contato@loja.com")

    def test_email_sem_dominio(self):
        self.assertEqual(val.normalizar_email("contato@"), "")
        self.assertEqual(val.normalizar_email("sem arroba"), "")

    def test_extrair_emails(self):
        texto = "E-mail: contato@artetear.com.br ou suporte@loja.com.br"
        self.assertEqual(
            val.extrair_emails(texto),
            ["contato@artetear.com.br", "suporte@loja.com.br"],
        )


class TestUrlRedes(unittest.TestCase):
    def test_normalizar_url(self):
        self.assertEqual(
            val.normalizar_url("https://www.artetear.com.br"),
            "www.artetear.com.br",
        )
        self.assertEqual(val.normalizar_url("www.artetear.com.br"), "www.artetear.com.br")

    def test_url_invalida(self):
        self.assertEqual(val.normalizar_url("não é site"), "")
        self.assertEqual(val.normalizar_url("contato@loja.com"), "")  # é e-mail

    def test_site_vs_rede_social(self):
        texto = (
            "www.artetear.com.br\n"
            "facebook.com/artetear\n"
            "instagram.com/artetear"
        )
        sites, redes = val.extrair_urls(texto)
        self.assertEqual(sites, ["www.artetear.com.br"])
        self.assertEqual(len(redes), 2)
        por_rede = {r["rede"]: r["valor"] for r in redes}
        self.assertEqual(por_rede["facebook"], "facebook.com/artetear")
        self.assertEqual(por_rede["instagram"], "instagram.com/artetear")
        self.assertEqual(redes[0]["usuario"], "artetear")

    def test_arroba_perfil(self):
        arrobas = val.extrair_arrobas("Siga @artetear no instagram")
        self.assertEqual(len(arrobas), 1)
        self.assertEqual(arrobas[0]["valor"], "@artetear")
        self.assertEqual(arrobas[0]["rede"], "instagram")


class TestEndereco(unittest.TestCase):
    def test_cidade_uf(self):
        cidade, uf = val.extrair_cidade_uf("Rua Daniel de Freitas, 645\nCentro\nIbitinga - SP")
        self.assertEqual(cidade, "Ibitinga")
        self.assertEqual(uf, "SP")

    def test_cidade_uf_inexistente(self):
        self.assertEqual(val.extrair_cidade_uf("qualquer coisa"), ("", ""))

    def test_logradouro_numero_complemento(self):
        res = val.extrair_logradouro(
            "Rua Daniel de Freitas, 645"
        )
        self.assertEqual(res["logradouro"], "Rua Daniel de Freitas")
        self.assertEqual(res["numero"], "645")
        self.assertEqual(res["complemento"], "")
        # complemento explícito fica registrado como tal
        res2 = val.extrair_logradouro("Rua Daniel de Freitas, 645 - Loja 2")
        self.assertEqual(res2["complemento"], "Loja 2")

    def test_cep_nao_vira_complemento(self):
        res = val.extrair_logradouro(
            "Av. Brasil, 1000 CEP 14940-145"
        )
        self.assertEqual(res["numero"], "1000")
        self.assertEqual(res["complemento"], "")


class TestCnpj(unittest.TestCase):
    def test_cnpj_valido(self):
        self.assertEqual(
            val.extrair_cnpj("CNPJ 12.345.678/0001-90"),
            "12.345.678/0001-90",
        )

    def test_cnpj_inexistente(self):
        self.assertEqual(val.extrair_cnpj("sem cnpj aqui"), "")


class TestSuporteOcr(unittest.TestCase):
    def test_digitos_suportados(self):
        self.assertTrue(val.suportado_pelo_ocr("16997269098", "16997269098"))
        self.assertFalse(val.suportado_pelo_ocr("16997965265", "16997269098"))

    def test_texto_suportado(self):
        ocr = "Arte & Tear\nRua Daniel de Freitas, 645\nIbitinga - SP"
        self.assertTrue(val.texto_suportado_pelo_ocr("Rua Daniel de Freitas", ocr))
        self.assertFalse(val.texto_suportado_pelo_ocr("Padaria Pão Dourado", ocr))


if __name__ == "__main__":
    unittest.main()
