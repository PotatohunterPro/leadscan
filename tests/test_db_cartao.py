"""Testes da persistência do cartão no SQLite (Fase 5.4 do PLANO-V2).

Cobre os itens 17/18/21: lead único com cartão (1:1 em lead_cartao),
atualização sem duplicar, preservação do texto OCR e — o mais importante —
salvar o cartão NUNCA altera os campos manuais do lead.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="leadscan-test-dbcard-")
os.environ["DATA_DIR"] = _TMP

from app import db  # noqa: E402


def _info(empresa: str = "Arte & Tear") -> dict:
    return {
        "versao": 1,
        "empresa": {"nome": empresa, "nome_fantasia": "", "ramo_atividade": ""},
        "pessoa": {"nome": "João da Silva", "cargo": "Proprietário"},
        "telefones": [{"numero": "(16) 3341-2520", "tipo": "fixo", "origem": "ocr"}],
        "emails": [],
        "sites": [],
        "redes_sociais": [],
        "endereco": {"logradouro": "Rua Daniel de Freitas", "numero": "645",
                     "complemento": "", "bairro": "Centro", "cidade": "Ibitinga",
                     "uf": "SP", "cep": "14940-145", "texto": ""},
        "documentos": {"cnpj": ""},
        "outras_informacoes": [],
        "ocr": {"disponivel": True, "texto": "Arte & Tear\n(16) 3341-2520",
                "frente": "Arte & Tear", "verso": "", "confianca": 90.0},
        "vlm": {"disponivel": True, "erro": "", "bruto": {}},
        "avisos": [],
        "imagens": {"frente": "fotos/x-frente.jpg", "verso": ""},
        "sugestoes": [],
    }


class TestCartaoDb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_salvar_e_buscar_cartao(self):
        lead_id = db.salvar_lead({"nome_empresa": "Loja"})
        db.salvar_cartao(lead_id, _info())
        cartao = db.buscar_cartao(lead_id)
        self.assertIsNotNone(cartao)
        self.assertEqual(cartao["empresa"]["nome"], "Arte & Tear")
        self.assertEqual(cartao["pessoa"]["nome"], "João da Silva")
        self.assertEqual(cartao["_meta"]["lead_id"], lead_id)

    def test_um_cartao_por_lead_atualiza(self):
        """Item 17/18: 1:1 — atualizar NÃO cria um segundo registro."""
        lead_id = db.salvar_lead({"nome_empresa": "Loja"})
        db.salvar_cartao(lead_id, _info("Arte & Tear"))
        db.salvar_cartao(lead_id, _info("Arte & Tear II"))
        cartao = db.buscar_cartao(lead_id)
        self.assertEqual(cartao["empresa"]["nome"], "Arte & Tear II")
        with db._conexao() as con:
            n = con.execute(
                "SELECT COUNT(*) FROM lead_cartao WHERE lead_id = ?", [lead_id]
            ).fetchone()[0]
        self.assertEqual(n, 1)

    def test_preserva_ocr_texto(self):
        lead_id = db.salvar_lead({"nome_empresa": "Loja"})
        db.salvar_cartao(lead_id, _info())
        cartao = db.buscar_cartao(lead_id)
        self.assertEqual(
            cartao["ocr"]["texto"], "Arte & Tear\n(16) 3341-2520"
        )

    def test_salvar_cartao_nao_altera_manuais(self):
        """REGRA ABSOLUTA (itens 4/21): cartão não toca nos campos do lead."""
        lead_id = db.salvar_lead({
            "nome_empresa": "Loja",
            "nome_contato": "Carlos",
            "cargo": "Proprietário",
            "anotacoes": "Está insatisfeito com o suporte.",
            "whatsapp": "(16) 99999-9999",
        })
        db.salvar_cartao(lead_id, _info())
        lead = db.buscar_lead(lead_id)
        self.assertEqual(lead["nome_contato"], "Carlos")      # NÃO virou João
        self.assertEqual(lead["cargo"], "Proprietário")
        self.assertEqual(lead["anotacoes"], "Está insatisfeito com o suporte.")
        self.assertEqual(lead["whatsapp"], "(16) 99999-9999")
        # e o cartão guardou o que a IA leu, sem conflito
        cartao = db.buscar_cartao(lead_id)
        self.assertEqual(cartao["pessoa"]["nome"], "João da Silva")

    def test_buscar_lead_completo(self):
        lead_id = db.salvar_lead({"nome_empresa": "Loja"})
        db.salvar_cartao(lead_id, _info())
        completo = db.buscar_lead_completo(lead_id)
        self.assertEqual(completo["nome_empresa"], "Loja")
        self.assertIn("cartao", completo)
        self.assertEqual(completo["cartao"]["empresa"]["nome"], "Arte & Tear")

    def test_buscar_lead_completo_sem_cartao(self):
        lead_id = db.salvar_lead({"nome_empresa": "Só Manual"})
        completo = db.buscar_lead_completo(lead_id)
        self.assertIsNone(completo["cartao"])

    def test_leads_com_cartao(self):
        l1 = db.salvar_lead({"nome_empresa": "A"})
        l2 = db.salvar_lead({"nome_empresa": "B"})
        db.salvar_cartao(l1, _info("Cartão A"))
        cartoes = db.leads_com_cartao([l1, l2])
        self.assertIn(l1, cartoes)
        self.assertEqual(cartoes[l1]["empresa"]["nome"], "Cartão A")
        self.assertNotIn(l2, cartoes)

    def test_json_corrompido_vira_dict_vazio(self):
        lead_id = db.salvar_lead({"nome_empresa": "X"})
        with db._conexao() as con:
            con.execute(
                "INSERT INTO lead_cartao (lead_id, dados_json, ocr_texto, "
                "criado_em, atualizado_em) VALUES (?, '{{quebrado', ?, ?, ?)",
                [lead_id, "texto", db.agora_iso(), db.agora_iso()],
            )
        cartao = db.buscar_cartao(lead_id)
        self.assertEqual(cartao["ocr"]["texto"], "texto")  # fallback p/ ocr_texto


if __name__ == "__main__":
    unittest.main()
