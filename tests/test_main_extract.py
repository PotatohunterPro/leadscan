"""Testes dos endpoints de extração e persistência do cartão (Fase 1 do V2).

Cobre o contrato novo:
  - /extract NÃO cria lead sozinho (item 9 do V2) — salvar=1 é o caminho legado;
  - /leads aceita cartao_json e grava as INFORMAÇÕES DO CARTÃO no MESMO lead
    (item 17/18), SEM tocar nos campos manuais (itens 4 e 21);
  - /leads reaproveita foto_frente_path/foto_verso_path do /extract e apaga o
    órfão quando um arquivo novo substitui o path;
  - /api/leads/{id} devolve o cartão junto (admin).

O pipeline (OCR + VLM) é substituído por um mock — aqui testamos a API, não o
modelo. Para rodar isolado:  python -m unittest tests.test_main_extract -v
"""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# DATA_DIR precisa existir ANTES de importar app.db (o módulo lê no import)
_TMP = tempfile.mkdtemp(prefix="leadscan-test-api-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("SESSION_SECRET", "chave-de-teste-leadscan")

from PIL import Image  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import cartao as cartao_mod  # noqa: E402
from app import db  # noqa: E402
from app import auth  # noqa: E402
from app import main as main_mod  # noqa: E402
from app.main import app  # noqa: E402

# um JPEG pequeno e válido para subir como foto
_buf = io.BytesIO()
Image.new("RGB", (240, 160), "white").save(_buf, format="JPEG")
JPEG_TINHO = _buf.getvalue()


async def _analisar_fake(frente_bytes: bytes, verso_bytes: bytes | None = None, chamar_vlm=None):
    """Mock do pipeline: devolve um cartão realista SEM chamar OCR/VLM."""
    if b"NAO-E-IMAGEM" in frente_bytes:
        raise ValueError("Arquivo enviado não é uma imagem válida")
    info = cartao_mod.info_vazia()
    info["empresa"]["nome"] = "Arte & Tear"
    info["pessoa"]["nome"] = "João da Silva"
    info["telefones"] = [
        {"numero": "(16) 3341-2520", "digitos": "1633412520", "e164": "+551633412520",
         "tipo": "fixo", "origem": "ocr", "confianca": 0.9},
        {"numero": "(16) 99726-9098", "digitos": "16997269098", "e164": "+5516997269098",
         "tipo": "whatsapp", "origem": "ocr", "confianca": 0.9},
    ]
    info["emails"] = [{"valor": "contato@artetear.com.br", "origem": "ocr"}]
    info["sites"] = [{"valor": "www.artetear.com.br", "origem": "ocr"}]
    info["ocr"]["disponivel"] = True
    info["ocr"]["texto"] = "Arte & Tear\n(16) 3341-2520"
    info["vlm"]["disponivel"] = True
    return SimpleNamespace(
        info=info,
        jpeg_frente=JPEG_TINHO,
        jpeg_verso=JPEG_TINHO if verso_bytes else None,
        erro_vlm="",
        ocr_ok=True,
    )


def _login_admin(client: TestClient) -> None:
    """Simula a sessão do admin (cookie assinado válido)."""
    client.cookies.set(auth.SESSION_COOKIE, auth.criar_cookie_valor())


def _cartao_json() -> str:
    return json.dumps({
        "versao": 1,
        "empresa": {"nome": "Arte & Tear", "nome_fantasia": "", "ramo_atividade": ""},
        "pessoa": {"nome": "João da Silva", "cargo": "Proprietário"},
        "telefones": [
            {"numero": "(16) 3341-2520", "digitos": "1633412520", "tipo": "fixo", "origem": "ocr"},
        ],
        "emails": [{"valor": "contato@artetear.com.br", "origem": "ocr"}],
        "sites": [{"valor": "www.artetear.com.br", "origem": "ocr"}],
        "redes_sociais": [{"rede": "instagram", "valor": "instagram.com/artetear", "usuario": "artetear", "origem": "ocr"}],
        "endereco": {"logradouro": "Rua Daniel de Freitas", "numero": "645", "complemento": "",
                     "bairro": "Centro", "cidade": "Ibitinga", "uf": "SP", "cep": "14940-145",
                     "texto": "Rua Daniel de Freitas, 645 — Centro — Ibitinga - SP — CEP 14940-145"},
        "documentos": {"cnpj": ""},
        "outras_informacoes": [{"texto": "Desde 1998", "origem": "ocr"}],
        "ocr": {"disponivel": True, "texto": "Arte & Tear\nRua Daniel de Freitas, 645\nCentro\nIbitinga - SP",
                "frente": "Arte & Tear\nRua Daniel de Freitas, 645\nCentro\nIbitinga - SP", "verso": "", "confianca": 90.0},
        "vlm": {"disponivel": True, "erro": "", "bruto": {}},
        "avisos": [],
        "imagens": {"frente": "", "verso": ""},
        "sugestoes": [],
    }, ensure_ascii=False)


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        self.patch_analisar = patch.object(main_mod.cartao_mod, "analisar", _analisar_fake)
        self.patch_analisar.start()

    def tearDown(self):
        self.patch_analisar.stop()
        self.client.__exit__(None, None, None)

    def test_extract_nao_cria_lead(self):
        """Item 9: a análise preenche a interface, só o 💾 Salvar Lead conclui."""
        antes = db.total_leads()
        resp = self.client.post(
            "/extract",
            files={"image": ("frente.jpg", JPEG_TINHO, "image/jpeg")},
        )
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()
        self.assertTrue(dados["success"])
        self.assertIsNone(dados["id"])                 # NÃO criou lead
        self.assertEqual(db.total_leads(), antes)
        self.assertIn("cartao", dados)                  # 📇 INFORMAÇÕES DO CARTÃO
        self.assertEqual(dados["cartao"]["empresa"]["nome"], "Arte & Tear")
        self.assertEqual(len(dados["cartao"]["telefones"]), 2)
        self.assertIn("data", dados)                    # formato legado segue lá
        self.assertEqual(dados["data"]["nome_empresa"], "Arte & Tear")

    def test_extract_frente_e_verso_mesmo_cartao(self):
        """Item 7: verso entra no pipeline junto (um cartão só)."""
        resp = self.client.post(
            "/extract",
            files={
                "image": ("frente.jpg", JPEG_TINHO, "image/jpeg"),
                "verso": ("verso.jpg", JPEG_TINHO, "image/jpeg"),
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.assertTrue(resp.json()["fotos"]["verso"])

    def test_extract_com_salvar_1_cria_lead_e_cartao(self):
        """Comportamento legado (salvar=1) continua funcionando."""
        resp = self.client.post(
            "/extract",
            files={"image": ("frente.jpg", JPEG_TINHO, "image/jpeg")},
            data={"salvar": "1"},
        )
        self.assertEqual(resp.status_code, 200)
        dados = resp.json()
        self.assertIsInstance(dados["id"], int)
        cartao = db.buscar_cartao(dados["id"])
        self.assertIsNotNone(cartao)
        self.assertEqual(cartao["empresa"]["nome"], "Arte & Tear")

    def test_extract_imagem_invalida_422(self):
        resp = self.client.post(
            "/extract",
            files={"image": ("lixo.jpg", b"NAO-E-IMAGEM", "image/jpeg")},
        )
        self.assertEqual(resp.status_code, 422)
        self.assertFalse(resp.json()["success"])

    def test_extract_imagem_grande_demais_413(self):
        with patch.object(main_mod, "TAMANHO_MAX_UPLOAD", 1000):
            resp = self.client.post(
                "/extract",
                files={"image": ("grande.jpg", b"x" * 2000, "image/jpeg")},
            )
        self.assertEqual(resp.status_code, 413)
        self.assertFalse(resp.json()["success"])


class TestLeadsPersistencia(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_leads_salva_cartao_no_mesmo_lead(self):
        """Item 17/18: lead único com dados manuais + informações do cartão."""
        resp = self.client.post("/leads", data={
            "nome_empresa": "Arte & Tear",
            "nome_contato": "Carlos",
            "cargo": "Proprietário",
            "whatsapp": "(16) 99726-9098",
            "anotacoes": "Está insatisfeito com o suporte.",
            "cartao_json": _cartao_json(),
        })
        self.assertEqual(resp.status_code, 200)
        lead_id = resp.json()["id"]
        lead = db.buscar_lead(lead_id)
        # dados manuais intactos (itens 4 e 21)
        self.assertEqual(lead["nome_contato"], "Carlos")
        self.assertEqual(lead["anotacoes"], "Está insatisfeito com o suporte.")
        # cartão salvo no MESMO lead, com a info da IA
        cartao = db.buscar_cartao(lead_id)
        self.assertIsNotNone(cartao)
        self.assertEqual(cartao["pessoa"]["nome"], "João da Silva")  # NÃO virou o contato
        self.assertEqual(cartao["endereco"]["cidade"], "Ibitinga")
        self.assertEqual(cartao["ocr"]["texto"], "Arte & Tear\nRua Daniel de Freitas, 645\nCentro\nIbitinga - SP")

    def test_leads_nao_sobrescreve_manual_pelo_cartao(self):
        """REGRA ABSOLUTA: a IA nunca apaga/substitui dados manuais."""
        resp = self.client.post("/leads", data={
            "nome_contato": "Carlos",
            "whatsapp": "(16) 99999-9999",
            "cartao_json": _cartao_json(),
        })
        lead_id = resp.json()["id"]
        lead = db.buscar_lead(lead_id)
        self.assertEqual(lead["nome_contato"], "Carlos")
        self.assertEqual(lead["whatsapp"], "(16) 99999-9999")
        cartao = db.buscar_cartao(lead_id)
        self.assertEqual(cartao["pessoa"]["nome"], "João da Silva")

    def test_leads_sem_cartao_json_continua_compativel(self):
        """POST /leads sem cartão: comportamento antigo, sem erro."""
        resp = self.client.post("/leads", data={"nome_empresa": "Só Manual"})
        self.assertEqual(resp.status_code, 200)
        lead_id = resp.json()["id"]
        self.assertIsNone(db.buscar_cartao(lead_id))
        self.assertEqual(db.buscar_lead(lead_id)["nome_empresa"], "Só Manual")

    def test_leads_cartao_json_invalido_422(self):
        """JSON quebrado não pode criar lead nem deixar lixo."""
        antes = db.total_leads()
        resp = self.client.post("/leads", data={
            "nome_empresa": "X",
            "cartao_json": '{"empresa": "sem fechamento',
        })
        self.assertEqual(resp.status_code, 422)
        self.assertFalse(resp.json()["success"])
        self.assertIn("cartao_json", resp.json()["error"])
        self.assertEqual(db.total_leads(), antes)

    def test_leads_cartao_json_nao_objeto_422(self):
        resp = self.client.post("/leads", data={
            "nome_empresa": "X",
            "cartao_json": "[1, 2, 3]",
        })
        self.assertEqual(resp.status_code, 422)
        self.assertFalse(resp.json()["success"])

    def test_leads_reaproveita_path_do_extract(self):
        """Path do /extract é usado direto (sem duplicar arquivo)."""
        resp = self.client.post("/leads", data={
            "nome_empresa": "Arte & Tear",
            "foto_frente_path": "fotos/abc-frente.jpg",
            "cartao_json": _cartao_json(),
        })
        self.assertEqual(resp.status_code, 200)
        lead_id = resp.json()["id"]
        lead = db.buscar_lead(lead_id)
        self.assertEqual(lead["foto_frente_path"], "fotos/abc-frente.jpg")
        cartao = db.buscar_cartao(lead_id)
        self.assertEqual(cartao["imagens"]["frente"], "fotos/abc-frente.jpg")

    def test_leads_upload_novo_apaga_orfao_do_extract(self):
        """Arquivo novo substitui o path do extract e apaga o órfão."""
        db.FOTOS_DIR.mkdir(parents=True, exist_ok=True)
        (db.FOTOS_DIR / "orfao-frente.jpg").write_bytes(JPEG_TINHO)
        resp = self.client.post(
            "/leads",
            data={
                "nome_empresa": "Arte & Tear",
                "foto_frente_path": "fotos/orfao-frente.jpg",
                "cartao_json": _cartao_json(),
            },
            files={"foto_frente": ("nova.jpg", JPEG_TINHO, "image/jpeg")},
        )
        self.assertEqual(resp.status_code, 200)
        lead = db.buscar_lead(resp.json()["id"])
        self.assertNotEqual(lead["foto_frente_path"], "fotos/orfao-frente.jpg")
        self.assertTrue(lead["foto_frente_path"].startswith("fotos/"))
        self.assertFalse((db.FOTOS_DIR / "orfao-frente.jpg").exists())

    def test_leads_atualiza_cartao_preservando_manuais(self):
        """Edição (lead_id): cartão atualiza, campos manuais permanecem.

        C1: editar lead existente exige sessão de admin — a rota pública de
        captura só CRIA (sem lead_id); atualizar é operação autenticada."""
        _login_admin(self.client)
        resp = self.client.post("/leads", data={
            "nome_contato": "Carlos",
            "anotacoes": "nota original",
            "cartao_json": _cartao_json(),
        })
        lead_id = resp.json()["id"]

        cartao2 = json.loads(_cartao_json())
        cartao2["empresa"]["nome"] = "Arte & Tear II"
        resp2 = self.client.post("/leads", data={
            "lead_id": str(lead_id),
            "nome_contato": "Carlos",          # vendedor reenvia o valor manual
            "anotacoes": "nota original",
            "cartao_json": json.dumps(cartao2, ensure_ascii=False),
        })
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["id"], lead_id)
        lead = db.buscar_lead(lead_id)
        self.assertEqual(lead["nome_contato"], "Carlos")
        self.assertEqual(lead["anotacoes"], "nota original")
        cartao = db.buscar_cartao(lead_id)
        self.assertEqual(cartao["empresa"]["nome"], "Arte & Tear II")

    def test_leads_atualizar_sem_cartao_nao_apaga_cartao(self):
        """Atualização sem cartao_json não apaga o cartão já gravado."""
        _login_admin(self.client)
        resp = self.client.post("/leads", data={
            "nome_empresa": "A",
            "cartao_json": _cartao_json(),
        })
        lead_id = resp.json()["id"]
        resp2 = self.client.post("/leads", data={
            "lead_id": str(lead_id),
            "nome_empresa": "B",
        })
        self.assertEqual(resp2.status_code, 200)
        self.assertIsNotNone(db.buscar_cartao(lead_id))


class TestAdminDetalhe(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        _login_admin(self.client)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_api_detalhe_inclui_cartao(self):
        resp = self.client.post("/leads", data={
            "nome_empresa": "Com Cartão",
            "cartao_json": _cartao_json(),
        })
        lead_id = resp.json()["id"]
        detalhe = self.client.get(f"/api/leads/{lead_id}").json()
        self.assertTrue(detalhe["success"])
        self.assertEqual(detalhe["lead"]["nome_empresa"], "Com Cartão")
        self.assertIn("cartao", detalhe["lead"])
        self.assertEqual(detalhe["lead"]["cartao"]["empresa"]["nome"], "Arte & Tear")

    def test_api_detalhe_sem_cartao(self):
        resp = self.client.post("/leads", data={"nome_empresa": "Sem Cartão"})
        lead_id = resp.json()["id"]
        detalhe = self.client.get(f"/api/leads/{lead_id}").json()
        self.assertIsNone(detalhe["lead"]["cartao"])


if __name__ == "__main__":
    unittest.main()
