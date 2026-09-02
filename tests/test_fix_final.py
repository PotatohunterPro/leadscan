"""Testes da rodada de correção da auditoria (docs/fix_final.md).

Cobre os achados corrigidos:
  C1  — POST /leads com lead_id exige sessão de admin (e 5.5 na edição);
  A1  — sem SESSION_SECRET o login/sessão ficam desativados (fail-closed);
  A2  — visibilidade 5.5 nas APIs /api/leads, export e detalhe;
  A3  — BDR/SDR não mutam lead de outro responsável (404);
  A4  — "Atrasados" não conta ação de HOJE como vencida;
  A5  — fechar/perder cancela a próxima ação agendada;
  M8  — CSV injection: valores com =,+,-,@ ganham ' na frente;
  M11 — lead inexistente em rota de mutação devolve 404 (não 422);
  M12 — filtros inválidos (estágio/origem/data) devolvem 422;
  M13 — motivo de perda fora da lista vira "Outro: <texto>";
  B16 — página de login não expõe a lista de usuários (etapa 2 só com senha).
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="leadscan-test-fix-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("SESSION_SECRET", "chave-de-teste-leadscan")

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, db  # noqa: E402
from app.main import app  # noqa: E402

db.init_db()


def _login(client: TestClient, usuario: str | None = None) -> None:
    client.cookies.set(auth.SESSION_COOKIE, auth.criar_cookie_valor(usuario))


def _lead_responsavel(client: TestClient, empresa: str, resp: str) -> int:
    """Cria um lead e o atribui a um responsável (via ligação)."""
    lid = client.post("/funil", json={"nome_empresa": empresa}).json()["id"]
    client.post(
        f"/api/funil/{lid}/ligacao",
        json={"feita": True, "virou_lead": True, "usuario": resp},
    )
    return lid


class TestC1EdicaoProtegida(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_edicao_sem_sessao_401(self):
        lid = self.client.post("/leads", data={"nome_empresa": "Alvo"}).json()["id"]
        c2 = TestClient(app)
        c2.__enter__()
        try:
            r = c2.post("/leads", data={"lead_id": str(lid), "nome_empresa": "Hack"})
            self.assertEqual(r.status_code, 401)
            # nada foi sobrescrito
            self.assertEqual(db.buscar_lead(lid)["nome_empresa"], "Alvo")
        finally:
            c2.__exit__(None, None, None)

    def test_edicao_de_lead_alheio_por_bdr_404(self):
        lid = _lead_responsavel(self.client, "Alheio", "SDR 2")
        c2 = TestClient(app)
        c2.__enter__()
        try:
            _login(c2, "SDR 1")
            r = c2.post("/leads", data={"lead_id": str(lid), "nome_empresa": "Hack"})
            self.assertEqual(r.status_code, 404)
        finally:
            c2.__exit__(None, None, None)

    def test_captura_publica_sem_lead_id_continua_ok(self):
        """Fluxo público de criação (sem lead_id) não pede sessão."""
        c2 = TestClient(app)
        c2.__enter__()
        try:
            r = c2.post("/leads", data={"nome_empresa": "Público"})
            self.assertEqual(r.status_code, 200)
        finally:
            c2.__exit__(None, None, None)

    def test_edicao_do_proprio_lead_por_bdr_ok(self):
        lid = _lead_responsavel(self.client, "Meu", "SDR 1")
        c2 = TestClient(app)
        c2.__enter__()
        try:
            _login(c2, "SDR 1")
            r = c2.post("/leads", data={"lead_id": str(lid), "nome_empresa": "Meu editado"})
            self.assertEqual(r.status_code, 200)
        finally:
            c2.__exit__(None, None, None)


class TestA3MutuacoesVisiveis(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def _bdr(self):
        c2 = TestClient(app)
        c2.__enter__()
        _login(c2, "SDR 1")
        return c2

    def test_bdr_nao_muda_estagio_de_lead_alheio(self):
        lid = _lead_responsavel(self.client, "Alheio", "SDR 2")
        c2 = self._bdr()
        try:
            r = c2.post(f"/api/funil/{lid}/estagio", json={"estagio": "ligacao_feita", "usuario": "SDR 1"})
            self.assertEqual(r.status_code, 404)
        finally:
            c2.__exit__(None, None, None)

    def test_bdr_nao_registra_ligacao_em_lead_alheio(self):
        lid = _lead_responsavel(self.client, "Alheio2", "SDR 2")
        c2 = self._bdr()
        try:
            r = c2.post(f"/api/funil/{lid}/ligacao", json={"feita": True, "usuario": "SDR 1"})
            self.assertEqual(r.status_code, 404)
        finally:
            c2.__exit__(None, None, None)

    def test_bdr_nao_agenda_acao_em_lead_alheio(self):
        lid = _lead_responsavel(self.client, "Alheio3", "SDR 2")
        c2 = self._bdr()
        try:
            r = c2.post(f"/api/funil/{lid}/proxima-acao", json={"acao": "Ligar", "usuario": "SDR 1"})
            self.assertEqual(r.status_code, 404)
        finally:
            c2.__exit__(None, None, None)

    def test_bdr_nao_edita_valor_de_lead_alheio(self):
        lid = _lead_responsavel(self.client, "Alheio4", "SDR 2")
        c2 = self._bdr()
        try:
            r = c2.post(f"/api/funil/{lid}/dados", json={"valor_estimado": 1000})
            self.assertEqual(r.status_code, 404)
        finally:
            c2.__exit__(None, None, None)

    def test_bdr_mexe_no_proprio_lead_ok(self):
        lid = _lead_responsavel(self.client, "Meu2", "SDR 1")
        c2 = self._bdr()
        try:
            r = c2.post(f"/api/funil/{lid}/ligacao", json={"feita": True, "virou_lead": True, "usuario": "SDR 1"})
            self.assertEqual(r.status_code, 200)
        finally:
            c2.__exit__(None, None, None)

    def test_mutacao_em_lead_inexistente_404(self):
        """M11: 'lead não encontrado' é 404 (antes virava 422 genérico)."""
        r = self.client.post("/api/funil/999999/estagio", json={"estagio": "fechado", "usuario": "SDR 1"})
        self.assertEqual(r.status_code, 404)
        r = self.client.post("/api/funil/999999/ligacao", json={"feita": True})
        self.assertEqual(r.status_code, 404)


class TestA2VisibilidadeApisLeads(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_api_leads_de_bdr_so_traz_os_dela(self):
        _lead_responsavel(self.client, "A2 A", "SDR 1")
        _lead_responsavel(self.client, "A2 B", "SDR 2")
        c2 = TestClient(app)
        c2.__enter__()
        try:
            _login(c2, "SDR 1")
            r = c2.get("/api/leads")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["leads"])
            self.assertTrue(all(l["responsavel_atual"] == "SDR 1" for l in r.json()["leads"]))
            # export idem
            r2 = c2.get("/api/leads/export")
            texto = r2.content.decode("utf-8-sig")
            self.assertIn("A2 A", texto)
            self.assertNotIn("A2 B", texto)
            # detalhe de lead alheio: 404
            lid_outro = None
            for l in self.client.get("/api/leads").json()["leads"]:
                if l["nome_empresa"] == "A2 B":
                    lid_outro = l["id"]
            self.assertIsNotNone(lid_outro)
            r3 = c2.get(f"/api/leads/{lid_outro}")
            self.assertEqual(r3.status_code, 404)
        finally:
            c2.__exit__(None, None, None)


class TestA1FailClosed(unittest.TestCase):
    def test_sem_secret_sessao_desativada(self):
        original = auth._serializer
        try:
            auth._serializer = None
            self.assertFalse(auth.sessao_disponivel())
            self.assertEqual(auth.criar_cookie_valor("SDR 1"), "")
            self.assertFalse(auth.cookie_valido("qualquer-coisa"))
            self.assertFalse(auth.token_login_valido("qualquer-coisa"))
            # login pela rota é recusado (não gera sessão)
            c2 = TestClient(app)
            c2.__enter__()
            try:
                r = c2.post("/admin/login", data={"senha": "x", "usuario": "SDR 1"}, follow_redirects=False)
                self.assertNotEqual(r.status_code, 303)
                self.assertIsNone(c2.cookies.get(auth.SESSION_COOKIE))
            finally:
                c2.__exit__(None, None, None)
        finally:
            auth._serializer = original


class TestA4AtrasadosPorDia(unittest.TestCase):
    def test_acao_de_hoje_nao_e_atrasada(self):
        lid = db.salvar_lead({"nome_empresa": "Hoje"})
        hoje_utc = db.agora_iso()[:10]  # date('now') do SQLite é UTC
        db.salvar_proxima_acao(lid, "Ligar hoje", hoje_utc, "", "SDR 1")
        achou = db.listar_funil(atrasados=True)
        self.assertNotIn(lid, [l["id"] for l in achou])
        # e aparece em "Retorno hoje"
        retorno = db.listar_funil(retorno_hoje=True)
        self.assertIn(lid, [l["id"] for l in retorno])

    def test_acao_de_ontem_e_atrasada(self):
        lid = db.salvar_lead({"nome_empresa": "Ontem"})
        db.salvar_proxima_acao(lid, "Ligar ontem", "2000-01-01", "", "SDR 1")
        achou = db.listar_funil(atrasados=True)
        self.assertIn(lid, [l["id"] for l in achou])


class TestA5FecharCancelaProximaAcao(unittest.TestCase):
    def _lead_com_acao(self, empresa, estagio_final):
        lid = db.salvar_lead({"nome_empresa": empresa})
        db.salvar_proxima_acao(lid, "Apresentar", "2026-09-10", "", "SDR 1")
        db.registrar_ligacao(lid, True, True, "", "SDR 1")
        db.mudar_estagio(lid, "qualificado", usuario="SDR 1")
        db.mudar_estagio(lid, estagio_final, usuario="SDR 1",
                         motivo_perda="Preço" if estagio_final == "perdido" else "")
        return lid

    def test_fechado_cancela_proxima_acao(self):
        lid = self._lead_com_acao("Fecha", "fechado")
        lead = db.buscar_lead(lid)
        self.assertEqual(lead["proxima_acao"], "")
        self.assertEqual(lead["data_proxima_acao"], "")
        agendadas = [a for a in db.atividades_do_lead(lid) if a["tipo"] == "proxima_acao"]
        self.assertEqual(agendadas[0]["status"], "cancelada")
        lista = db.listar_funil()
        self.assertFalse(next(l for l in lista if l["id"] == lid)["tem_acao_agendada"])

    def test_perdido_cancela_proxima_acao(self):
        lid = self._lead_com_acao("Perde", "perdido")
        lead = db.buscar_lead(lid)
        self.assertEqual(lead["proxima_acao"], "")
        self.assertEqual(lead["data_proxima_acao"], "")
        # e não reaparece nos filtros de retorno/atrasado (M1)
        achou = db.listar_funil(atrasados=True, retorno_hoje=True)
        self.assertNotIn(lid, [l["id"] for l in achou])


class TestM8CsvInjection(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_export_prefixa_formula(self):
        self.client.post("/leads", data={
            "nome_empresa": "=2+2",
            "whatsapp": "+5511999999999",
            "anotacoes": "@SUM(A1)",
        })
        r = self.client.get("/api/leads/export")
        texto = r.content.decode("utf-8-sig")
        self.assertIn("'=2+2", texto)
        self.assertIn("'@SUM(A1)", texto)


class TestM12FiltrosInvalidos(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_estagio_invalido_422(self):
        r = self.client.get("/api/funil", params={"estagio": "xpto"})
        self.assertEqual(r.status_code, 422)

    def test_origem_invalida_422(self):
        r = self.client.get("/api/funil", params={"origem": "xpto"})
        self.assertEqual(r.status_code, 422)

    def test_data_invalida_422(self):
        r = self.client.get("/api/funil", params={"de": "nao-e-uma-data"})
        self.assertEqual(r.status_code, 422)


class TestM13MotivoNormalizado(unittest.TestCase):
    def test_motivo_livre_vira_outro(self):
        lid = db.salvar_lead({"nome_empresa": "Perdido livre"})
        db.registrar_ligacao(lid, True, True, "", "SDR 1")
        db.mudar_estagio(lid, "qualificado", usuario="SDR 1")
        db.mudar_estagio(lid, "perdido", usuario="SDR 1", motivo_perda="não tinha verba")
        self.assertEqual(db.buscar_lead(lid)["motivo_perda"], "Outro: não tinha verba")

    def test_motivo_da_lista_nao_muda(self):
        lid = db.salvar_lead({"nome_empresa": "Perdido lista"})
        db.registrar_ligacao(lid, True, True, "", "SDR 1")
        db.mudar_estagio(lid, "qualificado", usuario="SDR 1")
        db.mudar_estagio(lid, "perdido", usuario="SDR 1", motivo_perda="Preço")
        self.assertEqual(db.buscar_lead(lid)["motivo_perda"], "Preço")


class TestB16LoginDuasEtapas(unittest.TestCase):
    def setUp(self):
        import bcrypt
        auth.ADMIN_PASSWORD_HASH = bcrypt.hashpw(b"segredo", bcrypt.gensalt()).decode()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_pagina_login_nao_expoe_usuarios(self):
        r = self.client.get("/admin/login")
        self.assertEqual(r.status_code, 200)
        # B16: a lista de usuários não vai mais para a página aberta
        self.assertNotIn("SDR 1", r.text)
        self.assertNotIn("Quem está entrando", r.text)

    def test_senha_correta_mostra_etapa_de_usuario(self):
        r = self.client.post("/admin/login", data={"senha": "segredo"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("SDR 1", r.text)  # agora sim, com a senha conferida
        m = re.search(r'name="token" value="([^"]+)"', r.text)
        self.assertIsNotNone(m)
        r2 = self.client.post(
            "/admin/login", data={"token": m.group(1), "usuario": "SDR 1"},
            follow_redirects=False,
        )
        self.assertEqual(r2.status_code, 303)
        self.assertIsNotNone(self.client.cookies.get(auth.SESSION_COOKIE))

    def test_senha_errada_nao_expoe_usuarios(self):
        r = self.client.post("/admin/login", data={"senha": "errada"})
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("SDR 1", r.text)

    def test_token_invalido_401(self):
        r = self.client.post("/admin/login", data={"token": "lixo", "usuario": "SDR 1"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
