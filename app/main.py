"""
LeadScan — captura de cartão de visita com IA local (Ollama).

FastAPI, um único processo, SQLite em arquivo único. Rotas:
  GET  /                     UI única (static/index.html)
  GET  /health               healthcheck (install.sh + Docker)
  POST /extract              multipart 'image' (+ 'verso' opcional) -> extrai e salva
  GET  /leads                últimos leads (JSON) — alimenta a UI
  POST /leads                persiste o formulário completo (IA + manual)
  GET  /config               defaults públicos p/ a UI (DDI do WhatsApp)
  /admin/* e /api/*          painel admin protegido por senha (cookie assinado)
  GET  /fotos/{nome}         serve fotos salvas (só com sessão admin)

Cada erro de /extract tem mensagem clara e específica — nunca deixar a
exceção subir crua (lição do projeto anterior).
"""

import csv
import io
import logging
import os
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError

from . import auth, db
from .ollama_client import OLLAMA_MODEL, extrair_dados, listar_modelos

# ---------------------------------------------------------------- logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("leadscan")

# ------------------------------------------------------------- constantes
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

MAX_LADO_IMG = 1024        # redimensiona antes do modelo (evita timeout)
QUALIDADE_JPEG = 80
TAMANHO_MAX_UPLOAD = 20 * 1024 * 1024  # 20MB (nginx permite 15M — folga)

WHATSAPP_DEFAULT_DDI = os.environ.get("WHATSAPP_DEFAULT_DDI", "55")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    logger.info("LeadScan iniciado — banco em %s, modelo %s", db.DB_PATH, OLLAMA_MODEL)
    yield


app = FastAPI(title="LeadScan", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ------------------------------------------------------------------ helpers

def redimensionar(imagem_bytes: bytes) -> bytes:
    """Reduz a imagem (máx 1024px no maior lado, JPEG q80).

    Imagem grande direto da câmera do celular estoura o timeout do modelo
    — redimensionar antes resolve (lição do debug do HubLead).
    """
    try:
        img = Image.open(io.BytesIO(imagem_bytes))
    except UnidentifiedImageError as exc:
        raise ValueError("Arquivo enviado não é uma imagem válida") from exc
    img = img.convert("RGB")
    img.thumbnail((MAX_LADO_IMG, MAX_LADO_IMG), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=QUALIDADE_JPEG)
    return buf.getvalue()


def salvar_foto(imagem_bytes: bytes, lado: str) -> str:
    """Salva a foto redimensionada em data/fotos/ e devolve o caminho relativo."""
    dados = redimensionar(imagem_bytes)
    nome = f"{uuid.uuid4().hex}-{lado}.jpg"
    db.FOTOS_DIR.mkdir(parents=True, exist_ok=True)
    (db.FOTOS_DIR / nome).write_bytes(dados)
    return f"fotos/{nome}"


def _apagar_foto(caminho: str | None) -> None:
    """Remove uma foto salva (rollback / limpeza de órfãos).

    Usada quando a persistência do lead falha depois de salvar a foto, ou
    quando uma atualização substitui a foto por outra.
    """
    if not caminho:
        return
    try:
        nome = caminho.split("/")[-1]
        arquivo = db.FOTOS_DIR / nome
        if arquivo.exists():
            arquivo.unlink()
    except OSError:
        logger.exception("Não consegui apagar foto órfã %s", caminho)


def exige_admin(request: Request) -> None:
    """Dependência p/ páginas HTML do admin: redireciona pro login."""
    if not auth.cookie_valido(request.cookies.get(auth.SESSION_COOKIE)):
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})


def exige_admin_api(request: Request) -> None:
    """Dependência p/ endpoints JSON do admin: 401 com mensagem clara."""
    if not auth.cookie_valido(request.cookies.get(auth.SESSION_COOKIE)):
        raise HTTPException(
            status_code=401,
            detail="Não autenticado — faça login em /admin/login",
        )


# ------------------------------------------------------------- rotas públicas

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=FileResponse)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/config")
def config():
    """Defaults que a UI precisa (sem expor segredos)."""
    return {"whatsapp_default_ddi": WHATSAPP_DEFAULT_DDI}


@app.post("/extract")
async def extrair_cartao(
    request: Request,
    image: UploadFile = File(...),
    verso: UploadFile | None = File(None),
):
    # Linha de log NA ENTRADA da rota — detecta instantaneamente se a rota
    # foi chamada ou se o problema é em outro lugar (lição do HubLead).
    logger.info(
        "POST /extract recebida: ip=%s arquivo=%s tipo=%s",
        request.client.host if request.client else "?",
        image.filename,
        image.content_type,
    )

    # 1. upload
    dados_img = await image.read()
    if not dados_img:
        return JSONResponse(
            status_code=422,
            content={"success": False, "error": "Campo 'image' vazio — envie o arquivo da foto."},
        )
    if len(dados_img) > TAMANHO_MAX_UPLOAD:
        return JSONResponse(
            status_code=413,
            content={"success": False, "error": "Imagem grande demais (máximo 20MB)."},
        )

    # 2. redimensionar (frente sempre; verso se enviado)
    try:
        imagem_ok = redimensionar(dados_img)
        dados_verso = None
        verso_ok = None
        if verso is not None:
            dados_verso = await verso.read()
            if dados_verso:
                verso_ok = redimensionar(dados_verso)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"success": False, "error": str(exc)})

    # 3. IA local (Ollama) — manda a frente e o verso (se houver)
    imagens = [imagem_ok] + ([verso_ok] if verso_ok else [])
    try:
        extraidos = await extrair_dados(imagens)
    except ValueError as exc:
        logger.warning("Extração falhou (JSON inválido): %s", exc)
        return JSONResponse(
            status_code=422,
            content={"success": False, "error": f"Modelo não devolveu JSON válido: {exc}"},
        )
    except httpx.HTTPError as exc:
        logger.exception("Ollama inacessível (tipo %s): %r", type(exc).__name__, exc)
        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "error": "Ollama inacessível (" + type(exc).__name__ + "): " + str(exc),
            },
        )
    except Exception as exc:  # nunca deixar a exceção subir crua
        logger.exception("Erro inesperado na extração")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Erro interno na extração (" + type(exc).__name__ + "): " + str(exc),
            },
        )

    # 4. salvar fotos (frente sempre; verso se enviado)
    fotos_salvas: list[str] = []
    try:
        lead = dict(extraidos)
        lead["foto_frente_path"] = salvar_foto(dados_img, "frente")
        fotos_salvas.append(lead["foto_frente_path"])
        if verso_ok:
            lead["foto_verso_path"] = salvar_foto(dados_verso, "verso")
            fotos_salvas.append(lead["foto_verso_path"])
    except ValueError as exc:
        for f in fotos_salvas:
            _apagar_foto(f)
        return JSONResponse(status_code=422, content={"success": False, "error": str(exc)})

    # 5. persistir lead com os campos extraídos + timestamp
    try:
        lead_id = db.salvar_lead(lead)
    except Exception as exc:
        logger.exception("Falha ao salvar lead no SQLite")
        for f in fotos_salvas:
            _apagar_foto(f)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Falha ao salvar no banco: {exc}"},
        )

    logger.info("Lead #%s salvo (extração OK)", lead_id)
    return {"success": True, "id": lead_id, "data": extraidos}


@app.get("/leads")
def listar_leads_publico(limite: int = 20):
    """Últimos leads pra alimentar a lista simples da UI — só colunas públicas.

    Dados sensíveis de qualificação (anotações, sistema, mensalidade, etc.)
    ficam restritos ao painel admin (/api/leads).
    """
    leads = db.listar_leads_publico(limite=limite)
    return {"success": True, "leads": leads}


@app.post("/leads")
async def salvar_lead_completo(request: Request):
    """Persiste o formulário completo (campos da IA + manuais + fotos).

    Se vier 'lead_id' de um lead já salvo pelo /extract, atualiza em vez de
    duplicar. Campos vêm como multipart (arquivos p/ foto_frente/foto_verso).
    """
    form = await request.form()
    dados: dict = {}
    for campo in db.CAMPOS:
        valor = form.get(campo)
        if valor is not None and not isinstance(valor, UploadFile):
            dados[campo] = str(valor).strip()

    for lado, campo_foto in (("frente", "foto_frente"), ("verso", "foto_verso")):
        arquivo = form.get(campo_foto)
        if isinstance(arquivo, UploadFile):
            conteudo = await arquivo.read()
            if conteudo:
                try:
                    dados[f"foto_{lado}_path"] = salvar_foto(conteudo, lado)
                except ValueError as exc:
                    return JSONResponse(
                        status_code=422, content={"success": False, "error": str(exc)}
                    )

    try:
        lead_id = int(form.get("lead_id") or 0)
    except (TypeError, ValueError):
        lead_id = 0

    try:
        existente = db.buscar_lead(lead_id) if lead_id else None
        antigas = (
            [existente.get("foto_frente_path"), existente.get("foto_verso_path")]
            if existente
            else []
        )
        if existente:
            db.atualizar_lead(lead_id, dados)
        else:
            lead_id = db.salvar_lead(dados)
        # apaga fotos antigas substituídas por novas nesta atualização (evita órfãos)
        novas = {dados.get("foto_frente_path"), dados.get("foto_verso_path")}
        for f in antigas:
            if f and f not in novas:
                _apagar_foto(f)
    except Exception as exc:
        logger.exception("Falha ao salvar lead completo")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Falha ao salvar no banco: {exc}"},
        )
    logger.info("Lead #%s salvo (formulário completo)", lead_id)
    return {"success": True, "id": lead_id}


# ------------------------------------------------------------- admin: login

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, erro: str = ""):
    return templates.TemplateResponse(
        request, "admin_login.html", {"erro": erro}
    )


@app.post("/admin/login")
async def admin_login_post(request: Request, senha: str = Form(...)):
    if auth.senha_confere(senha):
        resp = RedirectResponse("/admin", status_code=303)
        resp.set_cookie(
            auth.SESSION_COOKIE,
            auth.criar_cookie_valor(),
            httponly=True,
            secure=(request.url.scheme == "https"),
            samesite="lax",
            max_age=auth.SESSION_MAX_AGE,
        )
        logger.info("Login admin OK")
        return resp
    logger.warning("Tentativa de login admin com senha incorreta")
    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {"erro": "Senha incorreta. Tente novamente."},
        status_code=401,
    )


@app.get("/admin/logout", dependencies=[Depends(exige_admin)])
def admin_logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(auth.SESSION_COOKIE)
    return resp


# ------------------------------------------------------------- admin: páginas

@app.get("/admin", dependencies=[Depends(exige_admin)])
def admin_dashboard(request: Request):
    return templates.TemplateResponse(
        request, "admin_status.html", {"modelo": OLLAMA_MODEL}
    )


@app.get("/admin/leads", dependencies=[Depends(exige_admin)])
def admin_leads_page(request: Request):
    return templates.TemplateResponse(
        request, "admin_leads.html", {}
    )


# ------------------------------------------------------------- admin: APIs

@app.get("/api/status", dependencies=[Depends(exige_admin_api)])
async def status_ia():
    """Status da IA: Ollama respondendo? modelo instalado? última extração?"""
    resposta = {
        "ollama_ok": False,
        "erro": None,
        "modelo": OLLAMA_MODEL,
        "modelo_instalado": False,
        "modelos": [],
        "ultima_extracao": db.ultima_extracao_sucesso(),
    }
    try:
        modelos = await listar_modelos()
        resposta["modelos"] = modelos
        resposta["ollama_ok"] = True
        resposta["modelo_instalado"] = OLLAMA_MODEL in modelos
    except httpx.HTTPError as exc:
        resposta["erro"] = f"Ollama inacessível: {exc}"
    except Exception as exc:
        logger.exception("Falha ao consultar status do Ollama")
        resposta["erro"] = f"Erro ao consultar Ollama: {exc}"
    return resposta


@app.get("/api/leads", dependencies=[Depends(exige_admin_api)])
def api_listar_leads(
    busca: str = "",
    de: str | None = None,
    ate: str | None = None,
    limite: int = 100,
):
    leads = db.listar_leads(busca=busca, de=de, ate=ate, limite=max(1, min(limite, 1000)))
    return {"success": True, "total": len(leads), "leads": leads}


@app.get("/api/leads/export", dependencies=[Depends(exige_admin_api)])
def exportar_csv(
    busca: str = "",
    de: str | None = None,
    ate: str | None = None,
):
    """Exporta leads filtrados em CSV (com BOM, abre certo no Excel)."""
    leads = db.listar_leads(busca=busca, de=de, ate=ate, limite=10000)
    colunas = ["id", "criado_em"] + db.CAMPOS
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(colunas)
    for lead in leads:
        writer.writerow([lead.get(c, "") for c in colunas])
    conteudo = "\ufeff" + buf.getvalue()
    nome = f"leads-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    return Response(
        content=conteudo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@app.get("/api/leads/{lead_id}", dependencies=[Depends(exige_admin_api)])
def api_detalhe_lead(lead_id: int):
    lead = db.buscar_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    return {"success": True, "lead": lead}


@app.get("/fotos/{nome}", dependencies=[Depends(exige_admin_api)])
def servir_foto(nome: str):
    """Serve fotos salvas em data/fotos/ (somente com sessão admin)."""
    if "/" in nome or "\\" in nome or ".." in nome or not nome.endswith(".jpg"):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    caminho = db.FOTOS_DIR / nome
    if not caminho.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(caminho, media_type="image/jpeg")
