"""Testes de CRUD do SQLite (banco temporário)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# DATA_DIR precisa existir ANTES de importar app.db
_TMP = tempfile.mkdtemp(prefix="leadscan-test-")
os.environ["DATA_DIR"] = _TMP

from app import db  # noqa: E402


class TestDb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_salvar_e_buscar(self):
        lead_id = db.salvar_lead(
            {"nome_empresa": "Loja Teste", "nome_contato": "João", "whatsapp": "5511999998888"}
        )
        self.assertIsInstance(lead_id, int)
        lead = db.buscar_lead(lead_id)
        self.assertEqual(lead["nome_empresa"], "Loja Teste")
        self.assertEqual(lead["nome_contato"], "João")
        self.assertIn("criado_em", lead)

    def test_campos_desconhecidos_sao_ignorados(self):
        lead_id = db.salvar_lead({"campo_que_nao_existe": "x", "nome_empresa": "Y"})
        lead = db.buscar_lead(lead_id)
        self.assertEqual(lead["nome_empresa"], "Y")
        self.assertNotIn("campo_que_nao_existe", lead)

    def test_atualizar_lead(self):
        lead_id = db.salvar_lead({"nome_empresa": "Antes"})
        ok = db.atualizar_lead(lead_id, {"nome_empresa": "Depois", "anotacoes": "nota"})
        self.assertTrue(ok)
        lead = db.buscar_lead(lead_id)
        self.assertEqual(lead["nome_empresa"], "Depois")
        self.assertEqual(lead["anotacoes"], "nota")

    def test_atualizar_lead_inexistente(self):
        self.assertFalse(db.atualizar_lead(999999, {"nome_empresa": "X"}))

    def test_listar_com_busca(self):
        db.salvar_lead({"nome_empresa": "Farmácia Saúde", "whatsapp": "1111"})
        db.salvar_lead({"nome_empresa": "Padaria Pão", "whatsapp": "2222"})
        resultado = db.listar_leads(busca="farm")
        self.assertTrue(resultado)
        self.assertEqual(resultado[0]["nome_empresa"], "Farmácia Saúde")

    def test_ultima_extracao(self):
        db.salvar_lead({"nome_empresa": "Última"})
        self.assertIsNotNone(db.ultima_extracao_sucesso())


if __name__ == "__main__":
    unittest.main()
