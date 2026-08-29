"""Testes do parse defensivo de JSON da resposta do Ollama."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ollama_client import CAMPOS_ESPERADOS, extrair_json_da_resposta


class TestExtrairJson(unittest.TestCase):
    def test_json_puro(self):
        dados = extrair_json_da_resposta(
            '{"nome_empresa": "Padaria Pão Dourado", "whatsapp": "(11) 99999-9999"}'
        )
        self.assertEqual(dados["nome_empresa"], "Padaria Pão Dourado")
        # campos ausentes viram string vazia
        for campo in CAMPOS_ESPERADOS:
            self.assertIn(campo, dados)
        self.assertEqual(dados["email"], "")

    def test_json_envolto_em_code_block(self):
        texto = "Aqui está:```json\n{\"nome_empresa\": \"X\"}\n```\nEspero ter ajudado."
        dados = extrair_json_da_resposta(texto)
        self.assertEqual(dados["nome_empresa"], "X")

    def test_code_block_sem_marcador_json(self):
        texto = "```\n{\"nome_contato\": \"Maria\"}\n```"
        dados = extrair_json_da_resposta(texto)
        self.assertEqual(dados["nome_contato"], "Maria")

    def test_json_com_texto_antes_e_depois(self):
        texto = "Resultado: {\"cidade\": \"São Paulo\"} Fim."
        dados = extrair_json_da_resposta(texto)
        self.assertEqual(dados["cidade"], "São Paulo")

    def test_resposta_vazia_levanta_value_error(self):
        with self.assertRaises(ValueError):
            extrair_json_da_resposta("")
        with self.assertRaises(ValueError):
            extrair_json_da_resposta("   \n  ")

    def test_resposta_sem_json_levanta_value_error(self):
        with self.assertRaises(ValueError):
            extrair_json_da_resposta("Desculpe, não consegui ler o cartão.")

    def test_json_invalido_levanta_value_error(self):
        with self.assertRaises(ValueError):
            extrair_json_da_resposta('{"nome_empresa": "sem fechamento')

    def test_nao_objeto_levanta_value_error(self):
        with self.assertRaises(ValueError):
            extrair_json_da_resposta("[1, 2, 3]")

    def test_valores_nulos_viram_string_vazia(self):
        dados = extrair_json_da_resposta('{"nome_empresa": null, "whatsapp": 123}')
        self.assertEqual(dados["nome_empresa"], "")
        self.assertEqual(dados["whatsapp"], "123")

    def test_trim_de_espacos(self):
        dados = extrair_json_da_resposta('{"email": "  x@y.com  "}')
        self.assertEqual(dados["email"], "x@y.com")


if __name__ == "__main__":
    unittest.main()
