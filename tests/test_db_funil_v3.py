"""Testes da V3 do funil no banco (R1: 5.1 valor esperado, 5.5 papéis;
R2: 5.2 atividade agendada/realizada, 5.3 evento oportunidade;
R3: 5.4 relatório de perdas).

Cada número exibido na tela deve bater com consulta direta no banco —
as métricas e o relatório são conferidos aqui contra SQL cru.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="leadscan-test-v3db-")
os.environ["DATA_DIR"] = _TMP

from app import db  # noqa: E402
from app.funil import PROBABILIDADE_ESTAGIO  # noqa: E402

db.init_db()


def _vivo(con: sqlite3.Connection, sql: str, params=()):
    return con.execute(sql, params).fetchone()[0]


class TestValorEsperado(unittest.TestCase):
    def test_coluna_valor_estimado_existe(self):
        with db._conexao() as con:
            cols = {r["name"] for r in con.execute("PRAGMA table_info(leads)").fetchall()}
        self.assertIn("valor_estimado", cols)

    def test_default_zero(self):
        lid = db.salvar_lead({"nome_empresa": "Sem valor"})
        self.assertEqual(db.buscar_lead(lid)["valor_estimado"], 0)

    def test_salvar_valor_estimado(self):
        lid = db.salvar_lead({"nome_empresa": "V"})
        db.salvar_valor_estimado(lid, 1250.5)
        self.assertEqual(db.buscar_lead(lid)["valor_estimado"], 1250.5)

    def test_valor_esperado_bate_com_sql_direto(self):
        lid = db.salvar_lead({"nome_empresa": "Negócio"})
        db.salvar_valor_estimado(lid, 1000)
        m = db.metricas_funil()
        prob = PROBABILIDADE_ESTAGIO["novo"] / 100
        # consulta direta: soma de valor_estimado * probabilidade, leads abertos
        with db._conexao() as con:
            esperado_direto = round(_vivo(
                con,
                "SELECT SUM(valor_estimado * ?) FROM leads "
                "WHERE estagio NOT IN ('fechado', 'perdido')",
                [prob],
            ), 2)
        self.assertEqual(m["valor_esperado_total"], esperado_direto)
        self.assertGreater(m["valor_esperado_total"], 0)

    def test_valor_esperado_por_estagio(self):
        lid = db.salvar_lead({"nome_empresa": "N2"})
        db.salvar_valor_estimado(lid, 500)
        m = db.metricas_funil()
        self.assertIn("valor_esperado_por_estagio", m)
        self.assertGreater(m["valor_esperado_por_estagio"]["novo"], 0)

    def test_valor_esperado_muda_ao_mover_estagio(self):
        """Fechado sai do esperado total (é valor realizado); probabilidades
        mudam com o estágio — bater com SQL direto em cada passo."""
        lid = db.salvar_lead({"nome_empresa": "Fechará"})
        db.salvar_valor_estimado(lid, 2000)
        db.registrar_ligacao(lid, True, True, "", "SDR 1")
        db.mudar_estagio(lid, "qualificado", usuario="SDR 1")
        m = db.metricas_funil()
        with db._conexao() as con:
            # replica a regra de _valor_esperado: soma bruta única + round
            direto = con.execute(
                "SELECT COALESCE(ROUND(SUM(valor_estimado * "
                "CASE estagio WHEN 'novo' THEN 0.05 WHEN 'ligacao_feita' THEN 0.10 "
                "WHEN 'qualificado' THEN 0.25 WHEN 'negociacao' THEN 0.60 "
                "WHEN 'fechado' THEN 1.00 WHEN 'perdido' THEN 0.00 ELSE 0 END), 2), 0) "
                "FROM leads WHERE estagio NOT IN ('fechado', 'perdido')"
            ).fetchone()[0]
        self.assertEqual(m["valor_esperado_total"], float(direto))


class TestUsuariosPapel(unittest.TestCase):
    def test_tabela_usuarios_existe(self):
        with db._conexao() as con:
            n = _vivo(
                con,
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='usuarios'",
            )
        self.assertEqual(n, 1)

    def test_semeados_do_codigo(self):
        usuarios = {u["nome"]: u["papel"] for u in db.listar_usuarios()}
        self.assertIn("SDR 1", usuarios)
        self.assertIn("SDR 2", usuarios)

    def test_papel_default_sdr(self):
        with db._conexao() as con:
            col = con.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='usuarios'"
            ).fetchone()[0]
        self.assertIn("'sdr'", col)

    def test_buscar_usuario(self):
        u = db.buscar_usuario("SDR 1")
        self.assertIsNotNone(u)
        self.assertEqual(u["nome"], "SDR 1")
        self.assertIsNone(db.buscar_usuario("Não existe"))


class TestVisibilidade(unittest.TestCase):
    def setUp(self):
        self.bdr = db.salvar_lead({"nome_empresa": "Da BDR"})
        self.outro = db.salvar_lead({"nome_empresa": "De outra"})
        db.registrar_responsavel(self.bdr, "SDR 1")
        db.registrar_responsavel(self.outro, "SDR 2")

    def test_filtra_por_responsavel(self):
        # mesmo filtro que a rota aplica pra bdr/sdr
        leads = db.listar_funil(responsavel="SDR 1")
        ids = [l["id"] for l in leads]
        self.assertIn(self.bdr, ids)
        self.assertNotIn(self.outro, ids)

    def test_sem_filtro_gestor_ve_tudo(self):
        leads = db.listar_funil()
        ids = [l["id"] for l in leads]
        self.assertIn(self.bdr, ids)
        self.assertIn(self.outro, ids)


class TestAtividadeAgendada(unittest.TestCase):
    def setUp(self):
        self.lid = db.salvar_lead({"nome_empresa": "Agend"})

    def test_proxima_acao_gera_agendada(self):
        db.salvar_proxima_acao(self.lid, "Ligar", "2026-09-10", "manhã", "SDR 1")
        ats = db.atividades_do_lead(self.lid)
        self.assertEqual(ats[0]["tipo"], "proxima_acao")
        self.assertEqual(ats[0]["status"], "agendada")

    def test_tem_acao_agendada_no_kanban(self):
        db.salvar_proxima_acao(self.lid, "Ligar", "2026-09-10")
        lead = db.listar_funil(busca="Agend")[0]
        self.assertTrue(lead["tem_acao_agendada"])

    def test_concluir_vira_realizada_e_some_o_sino(self):
        db.salvar_proxima_acao(self.lid, "Ligar", "2026-09-10")
        aid = db.atividades_do_lead(self.lid)[0]["id"]
        db.concluir_atividade(self.lid, aid, "SDR 1")
        ats = db.atividades_do_lead(self.lid)
        self.assertEqual(ats[1]["status"], "realizada")
        lead = db.listar_funil(busca="Agend")[0]
        self.assertFalse(lead["tem_acao_agendada"])
        self.assertEqual(lead["proxima_acao"], "")

    def test_nova_proxima_acao_cancela_anterior(self):
        db.salvar_proxima_acao(self.lid, "Ligar", "2026-09-10")
        db.salvar_proxima_acao(self.lid, "Enviar proposta", "2026-09-12")
        ats = db.atividades_do_lead(self.lid)
        # B6: a troca registra "Ação cancelada — substituída" na timeline;
        # a atividade antiga (tipo proxima_acao, 2ª no histórico) fica
        # cancelada e a nova segue agendada.
        status_por_tipo = [a for a in ats if a["tipo"] == "proxima_acao"]
        self.assertEqual(status_por_tipo[0]["status"], "agendada")  # nova
        self.assertEqual(status_por_tipo[1]["status"], "cancelada")  # antiga
        self.assertIn("Ação cancelada — substituída", ats[1]["descricao"])
        # só uma agendada pendente → 🔔 continua presente
        lead = db.listar_funil(busca="Agend")[0]
        self.assertTrue(lead["tem_acao_agendada"])

    def test_cancelar_atividade(self):
        db.salvar_proxima_acao(self.lid, "Ligar", "2026-09-10")
        aid = db.atividades_do_lead(self.lid)[0]["id"]
        db.cancelar_atividade(self.lid, aid, "SDR 1")
        lead = db.listar_funil(busca="Agend")[0]
        self.assertFalse(lead["tem_acao_agendada"])

    def test_concluir_sem_lead_erro(self):
        with self.assertRaises(ValueError):
            db.concluir_atividade(999999, 1)


class TestOportunidade(unittest.TestCase):
    def setUp(self):
        self.lid = db.salvar_lead({"nome_empresa": "Op"})
        db.registrar_ligacao(self.lid, True, True, "", "SDR 1")
        db.mudar_estagio(self.lid, "qualificado", usuario="SDR 1")

    def test_qualificado_para_negociacao_exige_obs(self):
        with self.assertRaises(ValueError):
            db.mudar_estagio(self.lid, "negociacao", usuario="SDR 1")

    def test_evento_oportunidade_na_timeline(self):
        db.mudar_estagio(self.lid, "negociacao", usuario="SDR 1", observacao="pediu proposta")
        ats = db.atividades_do_lead(self.lid)
        self.assertEqual(ats[0]["tipo"], "oportunidade")
        self.assertIn("🎯 Virou oportunidade", ats[0]["descricao"])
        self.assertIn("pediu proposta", ats[0]["descricao"])
        self.assertEqual(ats[0]["estagio_anterior"], "qualificado")
        self.assertEqual(ats[0]["estagio_novo"], "negociacao")

    def test_reabertura_nao_exige_obs(self):
        """Só a passagem QUALIFICADO→NEGOCIACAO exige observação; reabrir
        perdido/fechado pra negociação não (preserva fluxos antigos)."""
        db.mudar_estagio(self.lid, "perdido", usuario="SDR 1", motivo_perda="Preço")
        db.mudar_estagio(self.lid, "negociacao", usuario="SDR 1")
        self.assertEqual(db.buscar_lead(self.lid)["estagio"], "negociacao")


class TestRelatorioPerdas(unittest.TestCase):
    def setUp(self):
        db.init_db()

    def test_relatorio_cruza_motivo_origem_responsavel(self):
        antes = db.relatorio_perdas()
        l1 = db.salvar_lead({"nome_empresa": "P1"})
        l2 = db.salvar_lead({"nome_empresa": "P2"})
        l3 = db.salvar_lead({"nome_empresa": "P3"})
        db.registrar_responsavel(l1, "SDR 1")
        db.registrar_responsavel(l2, "SDR 1")
        db.registrar_responsavel(l3, "SDR 2")
        db.mudar_estagio(l1, "perdido", usuario="SDR 1", motivo_perda="Preço")
        db.mudar_estagio(l2, "perdido", usuario="SDR 1", motivo_perda="Preço")
        db.mudar_estagio(l3, "perdido", usuario="SDR 2", motivo_perda="Sem orçamento")
        r = db.relatorio_perdas()
        self.assertEqual(r["total"], antes["total"] + 3)
        chave = {(x["motivo_perda"], x["responsavel_atual"]): x["quantidade"] for x in r["linhas"]}
        # deltas por combinação (banco compartilhado entre módulos de teste)
        for x in antes["linhas"]:
            chave[(x["motivo_perda"], x["responsavel_atual"])] -= x["quantidade"]
        self.assertEqual(chave[("Preço", "SDR 1")], 2)
        self.assertEqual(chave[("Sem orçamento", "SDR 2")], 1)

    def test_relatorio_filtra_por_responsavel(self):
        antes = db.relatorio_perdas(responsavel="SDR 1")
        l1 = db.salvar_lead({"nome_empresa": "Q1"})
        l2 = db.salvar_lead({"nome_empresa": "Q2"})
        db.registrar_responsavel(l1, "SDR 1")
        db.registrar_responsavel(l2, "SDR 2")
        db.mudar_estagio(l1, "perdido", usuario="SDR 1", motivo_perda="Preço")
        db.mudar_estagio(l2, "perdido", usuario="SDR 2", motivo_perda="Preço")
        r = db.relatorio_perdas(responsavel="SDR 1")
        self.assertEqual(r["total"], antes["total"] + 1)
        self.assertTrue(all(x["responsavel_atual"] == "SDR 1" for x in r["linhas"]))


if __name__ == "__main__":
    unittest.main()
