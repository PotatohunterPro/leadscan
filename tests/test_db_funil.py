"""Testes do funil de vendas no banco (Fase 4.1 do funil_implement.md).

Cobre as regras do funildevendas.md:
- lead novo entra no estágio 'novo' (DEFAULT, sem tocar no fluxo de captura);
- 'qualificado' exige ligação feita + virou lead;
- 'perdido' exige motivo_perda;
- toda mudança grava em historico_estagios (auditoria com usuário/data);
- métricas leves (contagem, conversão, tempo médio).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="leadscan-test-funil-")
os.environ["DATA_DIR"] = _TMP

from app import db  # noqa: E402


class TestMigracao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_colunas_funil_existem(self):
        with db._conexao() as con:
            cols = {r["name"] for r in con.execute("PRAGMA table_info(leads)").fetchall()}
        for coluna in db.FUNIL_COLUNAS:
            self.assertIn(coluna, cols)

    def test_tabela_historico_existe(self):
        with db._conexao() as con:
            n = con.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' AND name='historico_estagios'"
            ).fetchone()[0]
        self.assertEqual(n, 1)

    def test_lead_capturado_entra_como_novo(self):
        """Captura (POST /leads) não envia estagio — nasce 'novo' por DEFAULT."""
        lid = db.salvar_lead({"nome_empresa": "Loja Captura"})
        lead = db.buscar_lead(lid)
        self.assertEqual(lead["estagio"], "novo")
        self.assertEqual(lead["ligacao_feita"], 0)
        self.assertEqual(lead["responsavel_atual"], "")


class TestTransicoes(unittest.TestCase):
    def setUp(self):
        self.lid = db.salvar_lead({"nome_empresa": "Loja Transição"})

    def test_qualificado_sem_ligacao_falha(self):
        with self.assertRaises(ValueError) as ctx:
            db.mudar_estagio(self.lid, "qualificado", usuario="SDR 1")
        self.assertIn("ligação", str(ctx.exception))

    def test_qualificado_com_ligacao_ok(self):
        db.registrar_ligacao(self.lid, True, True, "Interessado", "SDR 1")
        lead = db.mudar_estagio(self.lid, "qualificado", usuario="SDR 1")
        self.assertEqual(lead["estagio"], "qualificado")

    def test_qualificado_ligacao_sem_virou_lead_falha(self):
        db.registrar_ligacao(self.lid, True, False, "", "SDR 1")
        with self.assertRaises(ValueError):
            db.mudar_estagio(self.lid, "qualificado", usuario="SDR 1")

    def test_perdido_sem_motivo_falha(self):
        with self.assertRaises(ValueError) as ctx:
            db.mudar_estagio(self.lid, "perdido", usuario="SDR 1")
        self.assertIn("motivo", str(ctx.exception))

    def test_perdido_com_motivo_ok(self):
        lead = db.mudar_estagio(
            self.lid, "perdido", usuario="SDR 1", motivo_perda="Sem orçamento"
        )
        self.assertEqual(lead["estagio"], "perdido")
        self.assertEqual(lead["motivo_perda"], "Sem orçamento")

    def test_estagio_invalido_falha(self):
        with self.assertRaises(ValueError):
            db.mudar_estagio(self.lid, "nao_existe")

    def test_historico_gravado_a_cada_mudanca(self):
        db.registrar_ligacao(self.lid, True, True, "", "SDR 1")
        db.mudar_estagio(self.lid, "qualificado", usuario="SDR 1", observacao="ok")
        # V3 (5.3): qualificado→negociacao exige observação
        db.mudar_estagio(self.lid, "negociacao", usuario="SDR 1", observacao="pediu proposta")
        hist = db.historico_do_lead(self.lid)
        self.assertEqual([h["estagio"] for h in hist], ["qualificado", "negociacao"])
        self.assertEqual(hist[0]["usuario_responsavel"], "SDR 1")
        self.assertEqual(hist[0]["observacao"], "ok")

    def test_mover_para_mesmo_estagio_nao_duplica_historico(self):
        db.mudar_estagio(self.lid, "ligacao_feita", usuario="SDR 1")
        antes = len(db.historico_do_lead(self.lid))
        db.mudar_estagio(self.lid, "ligacao_feita", usuario="SDR 1")
        self.assertEqual(len(db.historico_do_lead(self.lid)), antes)

    def test_ligacao_registra_responsavel(self):
        db.registrar_ligacao(self.lid, True, False, "Não agora", "SDR 2")
        lead = db.buscar_lead(self.lid)
        self.assertEqual(lead["ligacao_feita"], 1)
        self.assertEqual(lead["ligacao_virou_lead"], 0)
        self.assertEqual(lead["ligacao_observacao"], "Não agora")
        self.assertEqual(lead["responsavel_atual"], "SDR 2")

    def test_buscar_lead_funil_inclui_historico_e_cartao(self):
        db.mudar_estagio(self.lid, "ligacao_feita", usuario="SDR 1")
        db.salvar_cartao(self.lid, {"empresa": {"nome": "Loja"}})
        lead = db.buscar_lead_funil(self.lid)
        self.assertIn("historico", lead)
        self.assertEqual(lead["historico"][0]["estagio"], "ligacao_feita")
        self.assertIsNotNone(lead["cartao"])


class TestMetricas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_contagem_e_conversao(self):
        # a suíte compartilha o DATA_DIR entre arquivos — usa delta (antes/depois)
        antes = db.metricas_funil()
        l1 = db.salvar_lead({"nome_empresa": "A"})
        l2 = db.salvar_lead({"nome_empresa": "B"})
        db.registrar_ligacao(l1, True, True, "", "SDR 1")
        db.mudar_estagio(l1, "qualificado", usuario="SDR 1")
        db.mudar_estagio(l1, "negociacao", usuario="SDR 1", observacao="oportunidade real")
        db.mudar_estagio(l1, "fechado", usuario="SDR 1")
        db.mudar_estagio(l2, "perdido", usuario="SDR 2", motivo_perda="x")
        depois = db.metricas_funil()
        self.assertEqual(depois["total"], antes["total"] + 2)
        self.assertEqual(
            depois["por_estagio"].get("fechado", 0),
            antes["por_estagio"].get("fechado", 0) + 1,
        )
        self.assertEqual(
            depois["por_estagio"].get("perdido", 0),
            antes["por_estagio"].get("perdido", 0) + 1,
        )
        self.assertIn("fechado", depois["tempo_medio_dias"])

    def test_listar_funil_filtros_e_tempo(self):
        l = db.salvar_lead({"nome_empresa": "Filtrável"})
        db.registrar_ligacao(l, True, True, "", "SDR 3")
        db.mudar_estagio(l, "qualificado", usuario="SDR 3")
        db.salvar_cartao(l, {"empresa": {"nome": "Filtrável"}, "telefones": []})
        por_resp = db.listar_funil(responsavel="SDR 3")
        self.assertTrue(all(x["responsavel_atual"] == "SDR 3" for x in por_resp))
        por_est = db.listar_funil(responsavel="SDR 3", estagio="qualificado")
        self.assertTrue(all(x["estagio"] == "qualificado" for x in por_est))
        self.assertTrue(por_est)
        lead = por_est[0]
        self.assertIn("tempo_no_estagio_dias", lead)
        self.assertIn("estagnado", lead)
        self.assertIsNotNone(lead["cartao"])
        self.assertEqual(lead["cartao"]["empresa"]["nome"], "Filtrável")


if __name__ == "__main__":
    unittest.main()
