"""Testes dos endpoints do funil (Fase 4.2 do funil_implement.md).

Mesmo padrão do test_main_extract.py: TestClient do FastAPI com a sessão do
admin (o funil usa o mesmo cookie). O fluxo de captura (/extract, /leads)
não é tocado — aqui só o módulo novo.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="leadscan-test-apifunil-")
os.environ["DATA_DIR"] = _TMP

from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
from app.main import app  # noqa: E402


def _login(client: TestClient) -> None:
    client.cookies.set(auth.SESSION_COOKIE, auth.criar_cookie_valor())


class TestFunilApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def _lead(self) -> int:
        resp = self.client.post(
            "/leads",
            data={"nome_empresa": "Loja Funil", "nome_contato": "C", "whatsapp": "11999990000"},
        )
        return resp.json()["id"]

    def test_pagina_funil_exige_sessao(self):
        c2 = TestClient(app)
        c2.__enter__()
        try:
            r = c2.get("/funil", follow_redirects=False)
            self.assertEqual(r.status_code, 303)  # redireciona pro login
        finally:
            c2.__exit__(None, None, None)

    def test_pagina_funil_ok(self):
        r = self.client.get("/funil")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Funil", r.text)
        self.assertIn("kanban", r.text)
        self.assertIn("sel-usuario", r.text)

    def test_qualificado_sem_ligacao_422(self):
        lid = self._lead()
        r = self.client.post(
            f"/api/funil/{lid}/estagio", json={"estagio": "qualificado", "usuario": "SDR 1"}
        )
        self.assertEqual(r.status_code, 422)
        self.assertFalse(r.json()["success"])
        self.assertIn("ligação", r.json()["error"])

    def test_perdido_sem_motivo_422(self):
        lid = self._lead()
        r = self.client.post(f"/api/funil/{lid}/estagio", json={"estagio": "perdido"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("motivo", r.json()["error"])

    def test_estagio_invalido_422(self):
        lid = self._lead()
        r = self.client.post(f"/api/funil/{lid}/estagio", json={"estagio": "xpto"})
        self.assertEqual(r.status_code, 422)

    def test_fluxo_feliz_ate_fechado(self):
        lid = self._lead()
        r = self.client.post(
            f"/api/funil/{lid}/ligacao",
            json={"feita": True, "virou_lead": True, "observacao": "ok", "usuario": "SDR 1"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["lead"]["ligacao_feita"])
        r = self.client.post(f"/api/funil/{lid}/estagio", json={"estagio": "fechado", "usuario": "SDR 1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["lead"]["estagio"], "fechado")

    def test_detalhe_inclui_historico_e_cartao(self):
        lid = self._lead()
        r = self.client.get(f"/api/funil/{lid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("historico", r.json()["lead"])
        self.assertIn("cartao", r.json()["lead"])

    def test_detalhe_inexistente_404(self):
        r = self.client.get("/api/funil/999999")
        self.assertEqual(r.status_code, 404)

    def test_metricas(self):
        r = self.client.get("/api/funil/metricas")
        self.assertEqual(r.status_code, 200)
        self.assertIn("por_estagio", r.json()["metricas"])
        self.assertIn("conversao_percent", r.json()["metricas"])

    def test_lista_com_filtro_estagio(self):
        self._lead()
        r = self.client.get("/api/funil", params={"estagio": "novo"})
        self.assertTrue(r.json()["success"])
        self.assertTrue(all(l["estagio"] == "novo" for l in r.json()["leads"]))
        self.assertIn("tempo_no_estagio_dias", r.json()["leads"][0])


if __name__ == "__main__":
    unittest.main()
