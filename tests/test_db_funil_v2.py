"""Testes do funil V2 no banco (Fase D1 do funil_implement_v2.md).

Cobre as lacunas da rodada 1 (Fase A + B):
- origem: manual/cartao; cartão depois NÃO muda origem; migração de lead antigo;
- próxima ação: salvar + filtros atrasados/retorno hoje;
- lead_atividades: tipos, data_ultima_interacao, timeline; cartão capturado;
- reabertura perdido→funil e fechado→funil preservando motivo/histórico;
- PRAGMA foreign_keys ativa;
- métricas específicas (qualificação/negociação/fechamento).
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="leadscan-test-funilv2-")
os.environ["DATA_DIR"] = _TMP

from app import db  # noqa: E402

# unittest ordena as classes alfabeticamente — garante o banco pronto ANTES
# de qualquer teste (TestAtividades roda antes de TestMigracaoV2).
db.init_db()


class TestMigracaoV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_colunas_v2_existem(self):
        with db._conexao() as con:
            cols = {r["name"] for r in con.execute("PRAGMA table_info(leads)").fetchall()}
        for col in (
            "origem",
            "data_ultima_interacao",
            "proxima_acao",
            "data_proxima_acao",
            "proxima_acao_observacao",
        ):
            self.assertIn(col, cols)

    def test_tabela_lead_atividades_existe(self):
        with db._conexao() as con:
            n = con.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name='lead_atividades'"
            ).fetchone()[0]
        self.assertEqual(n, 1)

    def test_foreign_keys_ativas(self):
        """Item 39: lead_atividades respeita a FK de leads."""
        with db._conexao() as con:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO lead_atividades (lead_id, tipo, descricao, data_hora) "
                    "VALUES (999999, 'outro', 'x', '2026-01-01T00:00:00')"
                )

    def test_migracao_origem_lead_antigo_com_cartao(self):
        """Item 61: lead antigo que já tem cartão ganha origem='cartao'."""
        lid = db.salvar_lead({"nome_empresa": "Antigo"})
        db.salvar_cartao(lid, {"empresa": {"nome": "Antigo"}})
        with db._conexao() as con:
            db._migrar_origem(con)
        self.assertEqual(db.buscar_lead(lid)["origem"], "cartao")


class TestOrigem(unittest.TestCase):
    def test_default_manual(self):
        lid = db.salvar_lead({"nome_empresa": "Manual"})
        self.assertEqual(db.buscar_lead(lid)["origem"], "manual")

    def test_origem_cartao_explicita(self):
        lid = db.salvar_lead({"nome_empresa": "Cartao"}, origem="cartao")
        self.assertEqual(db.buscar_lead(lid)["origem"], "cartao")

    def test_cartao_depois_nao_muda_origem(self):
        """Item 47: lead manual que recebe cartão depois NÃO muda de origem."""
        lid = db.salvar_lead({"nome_empresa": "Manual+"})
        db.salvar_cartao(lid, {"empresa": {"nome": "Manual+"}})
        self.assertEqual(db.buscar_lead(lid)["origem"], "manual")

    def test_edicao_nao_muda_origem(self):
        lid = db.salvar_lead({"nome_empresa": "X"}, origem="cartao")
        db.atualizar_lead(lid, {"nome_empresa": "X2", "whatsapp": "11999990000"})
        self.assertEqual(db.buscar_lead(lid)["origem"], "cartao")


class TestProximaAcao(unittest.TestCase):
    def setUp(self):
        self.lid = db.salvar_lead({"nome_empresa": "P.Ação"})

    def test_salvar_proxima_acao(self):
        db.salvar_proxima_acao(self.lid, "Ligar", "2026-09-03", "de manhã", "SDR 1")
        lead = db.buscar_lead(self.lid)
        self.assertEqual(lead["proxima_acao"], "Ligar")
        self.assertEqual(lead["data_proxima_acao"], "2026-09-03")
        self.assertEqual(lead["proxima_acao_observacao"], "de manhã")
        self.assertNotEqual(lead["data_ultima_interacao"], "")
        ats = db.atividades_do_lead(self.lid)
        self.assertEqual(ats[0]["tipo"], "proxima_acao")
        self.assertIn("Ligar", ats[0]["descricao"])

    def test_filtro_atrasados(self):
        """Item 33: próxima ação vencida aparece no filtro."""
        db.salvar_proxima_acao(self.lid, "Retornar", "2000-01-01T00:00:00")
        achou = db.listar_funil(atrasados=True)
        self.assertIn(self.lid, [l["id"] for l in achou])

    def test_filtro_atrasados_ignora_fechado_e_perdido(self):
        lid2 = db.salvar_lead({"nome_empresa": "P2"})
        db.salvar_proxima_acao(lid2, "X", "2000-01-01T00:00:00")
        db.mudar_estagio(lid2, "perdido", usuario="SDR 1", motivo_perda="Preço")
        achou = db.listar_funil(atrasados=True)
        self.assertNotIn(lid2, [l["id"] for l in achou])

    def test_filtro_retorno_hoje(self):
        """Item 34: retorno hoje (data_proxima_acao = hoje)."""
        hoje = db.agora_iso()
        db.salvar_proxima_acao(self.lid, "Apresentar", hoje)
        achou = db.listar_funil(retorno_hoje=True)
        self.assertIn(self.lid, [l["id"] for l in achou])

    def test_filtro_origem_e_sem_contato(self):
        lid = db.salvar_lead({"nome_empresa": "SC"})
        achou = db.listar_funil(origem="manual", sem_contato=True)
        self.assertIn(lid, [l["id"] for l in achou])
        db.registrar_ligacao(lid, True, False, "", "SDR 1")
        achou2 = db.listar_funil(sem_contato=True)
        self.assertNotIn(lid, [l["id"] for l in achou2])

    def test_lista_traz_campos_v2(self):
        lid = db.salvar_lead({"nome_empresa": "V2"})
        db.salvar_cartao(lid, {"empresa": {"nome": "V2"}})
        db.salvar_proxima_acao(lid, "Ligar", "2026-09-03")
        lead = db.listar_funil(busca="V2")[0]
        self.assertIn("tem_cartao", lead)
        self.assertTrue(lead["tem_cartao"])
        self.assertEqual(lead["proxima_acao"], "Ligar")
        self.assertEqual(lead["origem"], "manual")  # cartão depois não muda origem


class TestAtividades(unittest.TestCase):
    def setUp(self):
        self.lid = db.salvar_lead({"nome_empresa": "Ativ"})

    def test_ligacao_gera_atividade_e_atualiza_ultima_interacao(self):
        db.registrar_ligacao(self.lid, True, True, "Interessado", "SDR 1")
        ats = db.atividades_do_lead(self.lid)
        self.assertEqual(ats[0]["tipo"], "ligacao")
        self.assertIn("virou lead", ats[0]["descricao"])
        self.assertNotEqual(db.buscar_lead(self.lid)["data_ultima_interacao"], "")

    def test_mudanca_de_estagio_gera_atividade(self):
        db.registrar_ligacao(self.lid, True, True, "", "SDR 1")
        db.mudar_estagio(self.lid, "qualificado", usuario="SDR 1", observacao="ok")
        ats = db.atividades_do_lead(self.lid)
        self.assertEqual(ats[0]["tipo"], "estagio")
        self.assertEqual(ats[0]["estagio_anterior"], "novo")
        self.assertEqual(ats[0]["estagio_novo"], "qualificado")
        # timeline decrescente: estágio mais recente que a ligação
        self.assertEqual([a["tipo"] for a in ats], ["estagio", "ligacao"])

    def test_fechado_gera_atividade_lead_fechado(self):
        db.registrar_ligacao(self.lid, True, True, "", "SDR 1")
        db.mudar_estagio(self.lid, "qualificado", usuario="SDR 1")
        db.mudar_estagio(self.lid, "fechado", usuario="SDR 1", observacao="Contratou")
        ats = db.atividades_do_lead(self.lid)
        self.assertIn("✅ Lead fechado", ats[0]["descricao"])
        self.assertIn("Contratou", ats[0]["descricao"])

    def test_perdido_gera_atividade_com_motivo(self):
        db.mudar_estagio(self.lid, "perdido", usuario="SDR 2", motivo_perda="Sem orçamento")
        ats = db.atividades_do_lead(self.lid)
        self.assertIn("Sem orçamento", ats[0]["descricao"])

    def test_registrar_interacao_tipos_validos(self):
        db.registrar_interacao(self.lid, "whatsapp", "Enviei apresentação", "SDR 1")
        db.registrar_interacao(self.lid, "observacao", "nada", "SDR 1")
        ats = db.atividades_do_lead(self.lid)
        self.assertEqual([a["tipo"] for a in ats], ["observacao", "whatsapp"])

    def test_registrar_interacao_tipo_invalido(self):
        with self.assertRaises(ValueError):
            db.registrar_interacao(self.lid, "nao_existe", "x")

    def test_cartao_capturado_gera_atividade(self):
        lid = db.salvar_lead({"nome_empresa": "C"})
        db.salvar_cartao(lid, {"empresa": {"nome": "C"}})
        ats = db.atividades_do_lead(lid)
        self.assertEqual(ats[0]["tipo"], "cartao")
        self.assertIn("Cartão", ats[0]["descricao"])

    def test_buscar_lead_funil_inclui_atividades(self):
        db.registrar_interacao(self.lid, "outro", "x", "SDR 1")
        lead = db.buscar_lead_funil(self.lid)
        self.assertIn("atividades", lead)
        self.assertEqual(lead["atividades"][0]["tipo"], "outro")


class TestReabertura(unittest.TestCase):
    def setUp(self):
        self.lid = db.salvar_lead({"nome_empresa": "Reabre"})
        db.registrar_ligacao(self.lid, True, True, "", "SDR 1")
        db.mudar_estagio(self.lid, "qualificado", usuario="SDR 1")

    def test_perdido_reaberto_preserva_motivo(self):
        """Itens 29/30: reabrir perdido mantém motivo e histórico."""
        db.mudar_estagio(self.lid, "perdido", usuario="SDR 1", motivo_perda="Preço")
        self.assertEqual(db.buscar_lead(self.lid)["motivo_perda"], "Preço")
        db.mudar_estagio(self.lid, "negociacao", usuario="SDR 1")
        lead = db.buscar_lead(self.lid)
        self.assertEqual(lead["estagio"], "negociacao")
        self.assertEqual(lead["motivo_perda"], "Preço")  # preservado
        ats = db.atividades_do_lead(self.lid)
        self.assertEqual(ats[0]["estagio_anterior"], "perdido")
        self.assertEqual(ats[0]["estagio_novo"], "negociacao")
        hist = db.historico_do_lead(self.lid)
        self.assertEqual(
            [h["estagio"] for h in hist], ["qualificado", "perdido", "negociacao"]
        )

    def test_fechado_reaberto_mantem_historico(self):
        db.mudar_estagio(self.lid, "fechado", usuario="SDR 1")
        db.mudar_estagio(self.lid, "negociacao", usuario="SDR 1")
        hist = db.historico_do_lead(self.lid)
        self.assertEqual(
            [h["estagio"] for h in hist], ["qualificado", "fechado", "negociacao"]
        )


class TestMetricasEspecificas(unittest.TestCase):
    def test_chaves_existem(self):
        m = db.metricas_funil()
        self.assertIn("tempo_medio_qualificacao_dias", m)
        self.assertIn("tempo_medio_negociacao_dias", m)
        self.assertIn("tempo_medio_fechamento_dias", m)

    def test_com_dados_retorna_valores(self):
        lid = db.salvar_lead({"nome_empresa": "Métricas V2"})
        db.registrar_ligacao(lid, True, True, "", "SDR 1")
        db.mudar_estagio(lid, "qualificado", usuario="SDR 1")
        db.mudar_estagio(lid, "negociacao", usuario="SDR 1", observacao="oportunidade real")
        db.mudar_estagio(lid, "fechado", usuario="SDR 1")
        m = db.metricas_funil()
        self.assertIsNotNone(m["tempo_medio_qualificacao_dias"])
        self.assertIsNotNone(m["tempo_medio_negociacao_dias"])
        self.assertIsNotNone(m["tempo_medio_fechamento_dias"])


if __name__ == "__main__":
    unittest.main()