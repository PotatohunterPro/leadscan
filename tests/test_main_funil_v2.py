"""Testes dos endpoints V2 do funil (Fase D2 do funil_implement_v2.md).

Mesmo padrão do test_main_funil.py: TestClient do FastAPI + cookie de sessão.
Cobre: /atividade, /proxima-acao, filtros novos (origem/sem_contato/
atrasados/retorno_hoje), origem cartao na captura e edição preservando funil.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="leadscan-test-apifunilv2-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("SESSION_SECRET", "chave-de-teste-leadscan")

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, db  # noqa: E402
from app.main import app  # noqa: E402

db.init_db()  # garante o banco pronto antes de qualquer teste


def _login(client: TestClient) -> None:
    client.cookies.set(auth.SESSION_COOKIE, auth.criar_cookie_valor())


class TestFunilV2Api(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def _lead(self, **extra) -> int:
        data = {"nome_empresa": "Loja V2", "nome_contato": "C", "whatsapp": "11999990000"}
        data.update(extra)
        resp = self.client.post("/leads", data=data)
        return resp.json()["id"]

    def test_atividade_ok(self):
        lid = self._lead()
        r = self.client.post(
            f"/api/funil/{lid}/atividade",
            json={"tipo": "whatsapp", "descricao": "Enviei apresentação", "usuario": "SDR 1"},
        )
        self.assertEqual(r.status_code, 200)
        lead = r.json()["lead"]
        self.assertEqual(lead["atividades"][0]["tipo"], "whatsapp")
        self.assertNotEqual(lead["data_ultima_interacao"], "")

    def test_atividade_tipo_invalido_422(self):
        lid = self._lead()
        r = self.client.post(
            f"/api/funil/{lid}/atividade",
            json={"tipo": "nao_existe", "descricao": "x"},
        )
        self.assertEqual(r.status_code, 422)

    def test_atividade_lead_inexistente_404(self):
        """M11: 'lead não encontrado' é 404 (antes virava 422 genérico)."""
        r = self.client.post(
            "/api/funil/999999/atividade",
            json={"tipo": "outro", "descricao": "x"},
        )
        self.assertEqual(r.status_code, 404)

    def test_proxima_acao_ok(self):
        lid = self._lead()
        r = self.client.post(
            f"/api/funil/{lid}/proxima-acao",
            json={"acao": "Ligar", "data": "2026-09-03", "observacao": "manhã", "usuario": "SDR 1"},
        )
        self.assertEqual(r.status_code, 200)
        lead = r.json()["lead"]
        self.assertEqual(lead["proxima_acao"], "Ligar")
        self.assertEqual(lead["data_proxima_acao"], "2026-09-03")
        self.assertNotEqual(lead["data_ultima_interacao"], "")

    def test_filtros_novos_na_lista(self):
        lid = self._lead()  # sem contato e origem manual
        r = self.client.get("/api/funil", params={"sem_contato": "1", "origem": "manual"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(lid, [l["id"] for l in r.json()["leads"]])

    def test_filtro_atrasados(self):
        lid = self._lead()
        self.client.post(
            f"/api/funil/{lid}/proxima-acao",
            json={"acao": "Retornar", "data": "2000-01-01T00:00:00"},
        )
        r = self.client.get("/api/funil", params={"atrasados": "1"})
        self.assertIn(lid, [l["id"] for l in r.json()["leads"]])

    def test_filtro_retorno_hoje(self):
        lid = self._lead()
        from app.db import agora_iso
        self.client.post(
            f"/api/funil/{lid}/proxima-acao",
            json={"acao": "Apresentar", "data": agora_iso()},
        )
        r = self.client.get("/api/funil", params={"retorno_hoje": "1"})
        self.assertIn(lid, [l["id"] for l in r.json()["leads"]])

    def test_origem_cartao_na_captura(self):
        """Item 48: POST /leads com cartao_json nasce com origem cartao."""
        r = self.client.post(
            "/leads",
            data={
                "nome_empresa": "Loja Cartão",
                "cartao_json": '{"empresa": {"nome": "Loja Cartão"}, "telefones": []}',
            },
        )
        lid = r.json()["id"]
        det = self.client.get(f"/api/funil/{lid}").json()["lead"]
        self.assertEqual(det["origem"], "cartao")
        self.assertEqual(det["atividades"][0]["tipo"], "cartao")

    def test_edicao_preserva_funil_e_origem(self):
        """B7: editar via POST /leads com lead_id não mexe no funil/origem."""
        lid = self._lead()
        self.client.post(
            f"/api/funil/{lid}/ligacao",
            json={"feita": True, "virou_lead": False, "usuario": "SDR 1"},
        )
        r = self.client.post(
            "/leads",
            data={"lead_id": str(lid), "nome_empresa": "Loja V2 Editada", "whatsapp": "11999990000"},
        )
        self.assertEqual(r.status_code, 200)
        det = self.client.get(f"/api/funil/{lid}").json()["lead"]
        self.assertEqual(det["nome_empresa"], "Loja V2 Editada")
        self.assertEqual(det["estagio"], "novo")
        self.assertEqual(det["origem"], "manual")
        self.assertEqual(det["ligacao_feita"], 1)

    def test_metricas_especificas(self):
        r = self.client.get("/api/funil/metricas")
        self.assertEqual(r.status_code, 200)
        m = r.json()["metricas"]
        self.assertIn("tempo_medio_qualificacao_dias", m)
        self.assertIn("tempo_medio_negociacao_dias", m)
        self.assertIn("tempo_medio_fechamento_dias", m)

    def test_detalhe_inclui_atividades(self):
        lid = self._lead()
        r = self.client.get(f"/api/funil/{lid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("atividades", r.json()["lead"])
        self.assertIn("origem", r.json()["lead"])


if __name__ == "__main__":
    unittest.main()