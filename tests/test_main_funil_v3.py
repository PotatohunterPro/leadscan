"""Testes da V3 do funil (docs/especificacao V3 — rodadas R0+).

R0: POST /funil (+ Novo Lead na tela) e página com os motivos de perda
    (modal com lista — nunca prompt()).
R1: 5.1 valor estimado/valor esperado + 5.5 visibilidade por papel (backend).
    Os demais itens (R2/R3) entram nos blocos seguintes do arquivo.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="leadscan-test-v3-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("SESSION_SECRET", "chave-de-teste-leadscan")

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, db  # noqa: E402
from app.main import app  # noqa: E402

db.init_db()


def _login(client: TestClient, usuario: str | None = None) -> None:
    client.cookies.set(auth.SESSION_COOKIE, auth.criar_cookie_valor(usuario))


class TestR0NovoLead(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_post_funil_cria_lead_novo_manual(self):
        r = self.client.post(
            "/funil",
            json={"nome_empresa": "Padaria do Zé", "nome_contato": "Zé",
                  "whatsapp": "11988887777"},
        )
        self.assertEqual(r.status_code, 200)
        lid = r.json()["id"]
        lead = r.json()["lead"]
        self.assertEqual(lead["estagio"], "novo")
        self.assertEqual(lead["origem"], "manual")
        # aparece no kanban
        r2 = self.client.get("/api/funil", params={"busca": "Padaria do Zé"})
        self.assertIn(lid, [l["id"] for l in r2.json()["leads"]])

    def test_post_funil_sem_empresa_nem_contato_422(self):
        r = self.client.post("/funil", json={"whatsapp": "11999999999"})
        self.assertEqual(r.status_code, 422)
        self.assertFalse(r.json()["success"])

    def test_post_funil_exige_sessao(self):
        c2 = TestClient(app)
        c2.__enter__()
        try:
            r = c2.post("/funil", json={"nome_empresa": "X"})
            self.assertEqual(r.status_code, 401)
        finally:
            c2.__exit__(None, None, None)

    def test_pagina_traz_motivos_de_perda_na_ui(self):
        """Modal de perdido usa lista curta de motivos — nunca prompt()."""
        r = self.client.get("/funil")
        self.assertEqual(r.status_code, 200)
        # MOTIVOS_PERDA vai pro JS via tojson (acentos viram \u00e7 etc.)
        self.assertIn("MOTIVOS_PERDA", r.text)
        self.assertIn("Sem interesse", r.text)
        self.assertIn("Registrar ligação", r.text)
        self.assertNotIn("prompt(", r.text)


class TestR1ValorEstimado(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_novo_lead_com_valor(self):
        r = self.client.post(
            "/funil",
            json={"nome_empresa": "Loja R1", "valor_estimado": 3000},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["lead"]["valor_estimado"], 3000)

    def test_endpoint_dados_atualiza_valor(self):
        lid = self.client.post("/funil", json={"nome_empresa": "V"}).json()["id"]
        r = self.client.post(f"/api/funil/{lid}/dados", json={"valor_estimado": 999})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["lead"]["valor_estimado"], 999)
        r2 = self.client.post(f"/api/funil/{lid}/dados", json={"valor_estimado": -5})
        self.assertEqual(r2.json()["lead"]["valor_estimado"], 0)

    def test_metricas_trazem_valor_esperado(self):
        r = self.client.get("/api/funil/metricas")
        m = r.json()["metricas"]
        self.assertIn("valor_esperado_total", m)
        self.assertIn("valor_esperado_por_estagio", m)


class TestR1Visibilidade(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def _lead_responsavel(self, resp, empresa):
        lid = self.client.post("/funil", json={"nome_empresa": empresa}).json()["id"]
        self.client.post(
            f"/api/funil/{lid}/ligacao",
            json={"feita": True, "virou_lead": True, "usuario": resp},
        )
        return lid

    def test_legado_admin_ve_tudo(self):
        """Cookie antigo ('admin') = gestor — continua vendo todos."""
        self._lead_responsavel("SDR 1", "Lead A")
        self._lead_responsavel("SDR 2", "Lead B")
        r = self.client.get("/api/funil")
        empresas = {l["nome_empresa"] for l in r.json()["leads"]}
        self.assertIn("Lead A", empresas)
        self.assertIn("Lead B", empresas)

    def test_bdr_ve_so_os_dela(self):
        """Item 5.5: papel bdr/sdr filtra por responsável na QUERY."""
        self._lead_responsavel("SDR 1", "Lead A")
        self._lead_responsavel("SDR 2", "Lead B")
        c2 = TestClient(app)
        c2.__enter__()
        try:
            _login(c2, "SDR 1")
            r = c2.get("/api/funil")
            leads = r.json()["leads"]
            self.assertTrue(leads)
            self.assertTrue(all(l["responsavel_atual"] == "SDR 1" for l in leads))
            # nem pedindo responsavel=SDR 2 ele enxerga
            r2 = c2.get("/api/funil", params={"responsavel": "SDR 2"})
            self.assertTrue(all(l["responsavel_atual"] == "SDR 1" for l in r2.json()["leads"]))
        finally:
            c2.__exit__(None, None, None)

    def test_bdr_nao_abre_detalhe_de_lead_alheio(self):
        lid = self._lead_responsavel("SDR 2", "Lead Alheio")
        c2 = TestClient(app)
        c2.__enter__()
        try:
            _login(c2, "SDR 1")
            r = c2.get(f"/api/funil/{lid}")
            self.assertEqual(r.status_code, 404)
        finally:
            c2.__exit__(None, None, None)

    def test_metricas_filtradas_por_papel(self):
        """O total das métricas de bdr/sdr bate com a listagem visível a ela."""
        self._lead_responsavel("SDR 1", "Lead M1")
        self._lead_responsavel("SDR 2", "Lead M2")
        c2 = TestClient(app)
        c2.__enter__()
        try:
            _login(c2, "SDR 1")
            lista = c2.get("/api/funil").json()["leads"]
            m = c2.get("/api/funil/metricas").json()["metricas"]
            # números consistentes: métrica visível = leads visíveis
            self.assertEqual(m["total"], len(lista))
            self.assertTrue(all(l["responsavel_atual"] == "SDR 1" for l in lista))
        finally:
            c2.__exit__(None, None, None)


class TestR1Login(unittest.TestCase):
    def test_login_com_usuario_limita_visao(self):
        """POST /admin/login com usuário grava sessão com o nome — e a
        visibilidade no funil passa a ser restrita a esse usuário."""
        import bcrypt
        from app import auth as auth_mod
        auth_mod.ADMIN_PASSWORD_HASH = bcrypt.hashpw(b"segredo", bcrypt.gensalt()).decode()
        c2 = TestClient(app)
        c2.__enter__()
        try:
            # cria lead de outro responsável antes do login restrito
            admin = TestClient(app)
            admin.__enter__()
            try:
                _login(admin)
                lid = admin.post("/funil", json={"nome_empresa": "Alheio"}).json()["id"]
                admin.post(f"/api/funil/{lid}/ligacao", json={"feita": True, "virou_lead": True, "usuario": "SDR 2"})
            finally:
                admin.__exit__(None, None, None)

            r = c2.post("/admin/login", data={"senha": "segredo", "usuario": "SDR 1"}, follow_redirects=False)
            self.assertEqual(r.status_code, 303)
            # sessão guarda o nome do usuário
            class Req:
                def __init__(self, cookies):
                    self.cookies = cookies
            cookie = c2.cookies.get(auth_mod.SESSION_COOKIE)
            self.assertEqual(auth_mod.usuario_da_sessao(Req({auth_mod.SESSION_COOKIE: cookie})), "SDR 1")
            # e a listagem só mostra os leads dele
            r2 = c2.get("/api/funil")
            self.assertTrue(all(l["responsavel_atual"] == "SDR 1" for l in r2.json()["leads"]))
        finally:
            c2.__exit__(None, None, None)

    def test_login_usuario_inexistente_401(self):
        import bcrypt
        from app import auth as auth_mod
        auth_mod.ADMIN_PASSWORD_HASH = bcrypt.hashpw(b"segredo", bcrypt.gensalt()).decode()
        c2 = TestClient(app)
        c2.__enter__()
        try:
            r = c2.post("/admin/login", data={"senha": "segredo", "usuario": "Ninguém"})
            self.assertEqual(r.status_code, 401)
        finally:
            c2.__exit__(None, None, None)


class TestR3RelatorioPerdas(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_relatorio_na_api(self):
        # banco é compartilhado entre arquivos de teste → compara delta
        antes = self.client.get("/api/funil/relatorio-perdas").json()["relatorio"]
        lid = self.client.post("/funil", json={"nome_empresa": "Perdido R3"}).json()["id"]
        self.client.post(
            f"/api/funil/{lid}/estagio",
            json={"estagio": "perdido", "motivo_perda": "Preço", "usuario": "SDR 1"},
        )
        r = self.client.get("/api/funil/relatorio-perdas")
        self.assertEqual(r.status_code, 200)
        rel = r.json()["relatorio"]
        self.assertEqual(rel["total"], antes["total"] + 1)
        # delta na combinação Preço/SDR 1 (pode já existir de outros testes)
        def quantidade(relatorio):
            return sum(
                x["quantidade"]
                for x in relatorio["linhas"]
                if x["motivo_perda"] == "Preço" and x["responsavel_atual"] == "SDR 1"
            )
        self.assertEqual(quantidade(rel), quantidade(antes) + 1)


class TestR2AtividadeAgendada(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_proxima_acao_agendada_e_concluir(self):
        lid = self.client.post("/funil", json={"nome_empresa": "R2"}).json()["id"]
        self.client.post(
            f"/api/funil/{lid}/proxima-acao",
            json={"acao": "Ligar", "data": "2026-09-10", "usuario": "SDR 1"},
        )
        lead = self.client.get(f"/api/funil/{lid}").json()["lead"]
        agendada = [a for a in lead["atividades"] if a["tipo"] == "proxima_acao"]
        self.assertEqual(agendada[0]["status"], "agendada")
        aid = agendada[0]["id"]
        # aparece no kanban com 🔔
        lista = self.client.get("/api/funil", params={"busca": "R2"}).json()["leads"]
        self.assertTrue(lista[0]["tem_acao_agendada"])
        # concluir por id
        r = self.client.post(f"/api/funil/{lid}/atividade/{aid}/concluir")
        self.assertEqual(r.status_code, 200)
        lead2 = r.json()["lead"]
        concluida = [a for a in lead2["atividades"] if a["id"] == aid]
        self.assertEqual(concluida[0]["status"], "realizada")
        lista2 = self.client.get("/api/funil", params={"busca": "R2"}).json()["leads"]
        self.assertFalse(lista2[0]["tem_acao_agendada"])

    def test_cancelar_atividade(self):
        lid = self.client.post("/funil", json={"nome_empresa": "R2b"}).json()["id"]
        self.client.post(f"/api/funil/{lid}/proxima-acao", json={"acao": "X", "usuario": "SDR 1"})
        aid = self.client.get(f"/api/funil/{lid}").json()["lead"]["atividades"][0]["id"]
        r = self.client.post(f"/api/funil/{lid}/atividade/{aid}/cancelar")
        self.assertEqual(r.status_code, 200)
        status = [a for a in r.json()["lead"]["atividades"] if a["id"] == aid][0]["status"]
        self.assertEqual(status, "cancelada")

    def test_oportunidade_na_api(self):
        lid = self.client.post("/funil", json={"nome_empresa": "R2c"}).json()["id"]
        self.client.post(f"/api/funil/{lid}/ligacao", json={"feita": True, "virou_lead": True, "usuario": "SDR 1"})
        self.client.post(f"/api/funil/{lid}/estagio", json={"estagio": "qualificado", "usuario": "SDR 1"})
        # sem observação → 422
        r = self.client.post(f"/api/funil/{lid}/estagio", json={"estagio": "negociacao", "usuario": "SDR 1"})
        self.assertEqual(r.status_code, 422)
        # com observação → atividade oportunidade
        r = self.client.post(
            f"/api/funil/{lid}/estagio",
            json={"estagio": "negociacao", "usuario": "SDR 1", "observacao": "pediu proposta"},
        )
        self.assertEqual(r.status_code, 200)
        det = self.client.get(f"/api/funil/{lid}").json()["lead"]
        self.assertEqual(det["atividades"][0]["tipo"], "oportunidade")


class TestR4Smoke(unittest.TestCase):
    """R4: fluxo end-to-end — captura→kanban→ligação→qualificado→próxima
    ação→negociação→fechado; perdido com motivo; reabertura; valor esperado
    batendo com o banco."""

    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_fluxo_completo_ate_fechado(self):
        lid = self.client.post(
            "/funil", json={"nome_empresa": "Smoke", "valor_estimado": 5000}
        ).json()["id"]

        # aparece no kanban como novo
        r = self.client.get("/api/funil", params={"busca": "Smoke"})
        lead = r.json()["leads"][0]
        self.assertEqual(lead["estagio"], "novo")
        self.assertEqual(lead["valor_estimado"], 5000)

        # ligação → virou lead → qualificado
        self.client.post(f"/api/funil/{lid}/ligacao", json={"feita": True, "virou_lead": True, "usuario": "SDR 1"})
        self.client.post(f"/api/funil/{lid}/estagio", json={"estagio": "qualificado", "usuario": "SDR 1"})

        # próxima ação agendada
        self.client.post(f"/api/funil/{lid}/proxima-acao", json={"acao": "Apresentar", "data": "2026-09-10", "usuario": "SDR 1"})

        # negociação exige observação (5.3)
        self.client.post(f"/api/funil/{lid}/estagio", json={"estagio": "negociacao", "usuario": "SDR 1", "observacao": "quer pilotar"})
        # fechado
        r = self.client.post(f"/api/funil/{lid}/estagio", json={"estagio": "fechado", "usuario": "SDR 1", "observacao": "Contratou"})
        self.assertEqual(r.json()["lead"]["estagio"], "fechado")
        ats = self.client.get(f"/api/funil/{lid}").json()["lead"]["atividades"]
        self.assertIn("✅ Lead fechado", ats[0]["descricao"])

        # valor esperado: fechado sai do pipeline (é valor realizado)
        m = self.client.get("/api/funil/metricas").json()["metricas"]
        with db._conexao() as con:
            direto = con.execute(
                "SELECT COALESCE(ROUND(SUM(valor_estimado * "
                "CASE estagio WHEN 'novo' THEN 0.05 WHEN 'ligacao_feita' THEN 0.10 "
                "WHEN 'qualificado' THEN 0.25 WHEN 'negociacao' THEN 0.60 "
                "WHEN 'fechado' THEN 1.00 WHEN 'perdido' THEN 0.00 ELSE 0 END), 2), 0) "
                "FROM leads WHERE estagio NOT IN ('fechado', 'perdido')"
            ).fetchone()[0]
        # número da tela bate com consulta direta no banco (itens sólidos)
        self.assertEqual(m["valor_esperado_total"], float(direto))

    def test_perdido_com_motivo_e_reabertura(self):
        lid = self.client.post("/funil", json={"nome_empresa": "SmokeP"}).json()["id"]
        self.client.post(f"/api/funil/{lid}/ligacao", json={"feita": True, "virou_lead": True, "usuario": "SDR 1"})
        self.client.post(f"/api/funil/{lid}/estagio", json={"estagio": "qualificado", "usuario": "SDR 1"})
        r = self.client.post(f"/api/funil/{lid}/estagio", json={"estagio": "perdido", "motivo_perda": "Preço", "usuario": "SDR 1"})
        self.assertEqual(r.json()["lead"]["motivo_perda"], "Preço")
        # reabertura preserva motivo e histórico
        r = self.client.post(f"/api/funil/{lid}/estagio", json={"estagio": "qualificado", "usuario": "SDR 1"})
        self.assertEqual(r.json()["lead"]["motivo_perda"], "Preço")
        det = self.client.get(f"/api/funil/{lid}").json()["lead"]
        self.assertEqual([h["estagio"] for h in det["historico"]], ["qualificado", "perdido", "qualificado"])

    def test_perdido_sem_motivo_422(self):
        lid = self.client.post("/funil", json={"nome_empresa": "SmokeX"}).json()["id"]
        r = self.client.post(f"/api/funil/{lid}/estagio", json={"estagio": "perdido", "usuario": "SDR 1"})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
