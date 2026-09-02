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
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, cartao as cartao_mod, db, imagem as img_mod, ocr as ocr_mod
from .ollama_client import OLLAMA_MODEL, listar_modelos

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
    """Reduz a imagem para guardar/enviar ao modelo (máx 1024px, JPEG q80).

    Agora passa pelo app.imagem: corrige EXIF/orientação antes de reduzir
    (foto de celular deitada quebrava o OCR e confundia o modelo). O OCR usa
    outra versão, em resolução maior — ver app/imagem.py.
    """
    img = img_mod.abrir(imagem_bytes)
    try:
        menor = img_mod.escalar(img, MAX_LADO_IMG)
        try:
            return img_mod.para_jpeg(menor, QUALIDADE_JPEG)
        finally:
            menor.close()
    finally:
        img.close()


def salvar_foto(imagem_bytes: bytes, lado: str) -> str:
    """Salva a foto redimensionada em data/fotos/ e devolve o caminho relativo."""
    return salvar_jpeg(redimensionar(imagem_bytes), lado)


def salvar_jpeg(jpeg: bytes, lado: str) -> str:
    """Grava um JPEG já processado (evita redimensionar duas vezes)."""
    nome = f"{uuid.uuid4().hex}-{lado}.jpg"
    db.FOTOS_DIR.mkdir(parents=True, exist_ok=True)
    (db.FOTOS_DIR / nome).write_bytes(jpeg)
    return f"fotos/{nome}"


def _limite_estourado(request: Request, chave: str, maximo: int, janela: float) -> bool:
    """M10: limitador simples por IP (janela deslizante, em memória).

    O app é um processo único — o contador vive na RAM e zera no restart
    (aceitável; é proteção contra abuso, não controle de cota). Protege:
    /extract (Ollama a cada request = CPU/IO), POST /leads (criação pública
    ilimitada) e /admin/login (força bruta).
    """
    ip = request.client.host if request.client else "?"
    agora = time.monotonic()
    fila = _RATE_LIMIT[(chave, ip)]
    while fila and fila[0] < agora - janela:
        fila.pop(0)
    if len(fila) >= maximo:
        return True
    fila.append(agora)
    return False


_RATE_LIMIT: dict[tuple[str, str], list[float]] = defaultdict(list)


def _verdadeiro(valor) -> bool:
    return str(valor or "").strip().lower() in ("1", "true", "sim", "yes", "on")


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


def _eh_arquivo(valor) -> bool:
    """True para qualquer UploadFile (FastAPI OU Starlette).

    O tipo concreto devolvido por request.form() varia conforme a versão do
    FastAPI/Starlette (em 0.141 é starlette.datastructures.UploadFile, que NÃO
    é a classe de fastapi.datastructures.UploadFile). Comparar por isinstance
    com um dos dois quebra — o duck-type (tem .read() e .filename) é estável.
    """
    return hasattr(valor, "read") and hasattr(valor, "filename")


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


def usuario_logado(request: Request) -> dict:
    """Quem está na sessão (V3 — 5.5): nome + papel lido DO BANCO.

    Sessão 'admin' antiga (senha única sem usuário) = gestor, sempre viu
    tudo e continua assim. O papel NUNCA vem do cliente: o cookie assinado
    só guarda o nome; o papel é consultado em `usuarios` a cada request.
    """
    nome = auth.usuario_da_sessao(request)
    if not nome:
        return {"nome": None, "papel": "gestor"}
    usuario = db.buscar_usuario(nome)
    return {"nome": nome, "papel": (usuario or {}).get("papel", "sdr")}


def _restricao_visivel(usuario: dict) -> str:
    """Nome que a listagem é obrigada a filtrar ('' = vê tudo).

    Item 5.5: bdr/sdr só enxergam os leads em que são o responsável atual —
    aplicado NA QUERY do backend, nunca escondido só na UI."""
    if usuario["papel"] != "gestor" and usuario["nome"]:
        return usuario["nome"]
    return ""


def _responsavel_da_acao(usuario: dict, enviado: str) -> str:
    """Quem assina a ação: não-gestor só pode agir como ele mesmo."""
    restrito = _restricao_visivel(usuario)
    return restrito or (enviado or usuario.get("nome") or "")


def _garantir_visivel(request: Request, lead_id: int) -> dict:
    """A3 (auditoria fix_final): 404 se o lead não existe OU está fora da
    visão do usuário (5.5). Todas as rotas de mutação do funil começam por
    aqui — antes era só o detalhe que conferia; um BDR podia mover o estágio
    / registrar ligação em lead alheio e "roubá-lo" (mudar_estagio e
    registrar_ligacao gravam responsavel_atual = quem age)."""
    restrito = _restricao_visivel(usuario_logado(request))
    lead = db.buscar_lead(lead_id)
    if not lead or (restrito and lead.get("responsavel_atual") != restrito):
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    return lead


def _validar_filtros(
    estagio: str = "",
    origem: str = "",
    de: str | None = None,
    ate: str | None = None,
) -> None:
    """M12: filtros inválidos viram 422 em vez de falharem em silêncio.

    - estagio/origem: só os valores conhecidos do funil;
    - de/ate: data ISO (YYYY-MM-DD) — aceita também timestamp ISO.
    """
    from .funil import ESTAGIOS, estagio_valido

    if estagio and not estagio_valido(estagio):
        raise HTTPException(
            status_code=422,
            detail=f"Estágio inválido: {estagio!r}. Valores: {', '.join(ESTAGIOS)}",
        )
    if origem and origem not in ("manual", "cartao"):
        raise HTTPException(
            status_code=422,
            detail=f"Origem inválida: {origem!r}. Valores: manual, cartao",
        )
    for rotulo, valor in (("de", de), ("ate", ate)):
        if valor:
            try:
                datetime.fromisoformat(valor)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"Data {rotulo} inválida: {valor!r} (use YYYY-MM-DD).",
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
    salvar: str = Form(""),
):
    """Analisa o cartão (OCR + IA) e devolve as INFORMAÇÕES DO CARTÃO.

    IMPORTANTE (regra 9 do projeto): esta rota NÃO cria mais um lead
    definitivo sozinha. Ela só analisa e devolve os dados para a interface —
    quem conclui o cadastro é o POST /leads ("💾 Salvar Lead"). Para o
    comportamento antigo (salvar na hora), envie salvar=1 no formulário.

    Resposta:
      success, id (lead salvo ou None), data (formato antigo, achatado),
      cartao (estrutura completa: telefones[], redes[], endereço, OCR bruto),
      fotos (caminhos já salvos, reaproveitados no POST /leads).
    """
    # Linha de log NA ENTRADA da rota — detecta instantaneamente se a rota
    # foi chamada ou se o problema é em outro lugar (lição do HubLead).
    logger.info(
        "POST /extract recebida: ip=%s arquivo=%s tipo=%s verso=%s",
        request.client.host if request.client else "?",
        image.filename,
        image.content_type,
        bool(verso),
    )

    # M10: cada análise chama o Ollama (CPU/IO) — limite por IP
    if _limite_estourado(request, "extract", 30, 60):
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "error": "Muitas análises em sequência — aguarde um minuto e tente de novo.",
            },
        )

    # 1. upload — B18: quando o cliente informa o tamanho no header, recusa
    # ANTES de ler o arquivo inteiro pra memória (upload gigante vira DoS).
    try:
        tamanho_declarado = int(request.headers.get("content-length") or 0)
    except (TypeError, ValueError):
        tamanho_declarado = 0
    if tamanho_declarado > TAMANHO_MAX_UPLOAD:
        return JSONResponse(
            status_code=413,
            content={"success": False, "error": "Imagem grande demais (máximo 20MB)."},
        )
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

    dados_verso = None
    if verso is not None:
        dados_verso = await verso.read() or None
        if dados_verso and len(dados_verso) > TAMANHO_MAX_UPLOAD:
            return JSONResponse(
                status_code=413,
                content={"success": False, "error": "Verso grande demais (máximo 20MB)."},
            )

    # 2. pipeline: pré-processamento -> OCR -> VLM -> fusão -> validação
    #    (frente e verso são o MESMO cartão, processados em sequência)
    try:
        analise = await cartao_mod.analisar(dados_img, dados_verso)
    except ValueError as exc:
        logger.warning("Análise do cartão falhou: %s", exc)
        return JSONResponse(
            status_code=422, content={"success": False, "error": str(exc)}
        )
    except httpx.HTTPError as exc:  # pragma: no cover - rede
        # M7: detalhes da rede/nome do serviço ficam no log — o cliente
        # anônimo recebe mensagem genérica (sem endereço/porta internos).
        logger.exception("Ollama inacessível (tipo %s): %r", type(exc).__name__, exc)
        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "error": "O serviço de IA está inacessível no momento. Tente de novo em instantes.",
            },
        )
    except Exception as exc:  # nunca deixar a exceção subir crua
        logger.exception("Erro inesperado na extração (%s): %r", type(exc).__name__, exc)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Erro interno na extração. Tente novamente — se persistir, veja os logs do servidor.",
            },
        )

    info = analise.info
    legado = cartao_mod.para_campos_legado(info)

    # 3. salvar as fotos já processadas (a UI devolve os caminhos no /leads)
    fotos_salvas: list[str] = []
    try:
        caminho_frente = salvar_jpeg(analise.jpeg_frente, "frente")
        fotos_salvas.append(caminho_frente)
        caminho_verso = ""
        if analise.jpeg_verso:
            caminho_verso = salvar_jpeg(analise.jpeg_verso, "verso")
            fotos_salvas.append(caminho_verso)
    except OSError as exc:
        logger.exception("Falha ao gravar a foto")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Falha ao salvar a foto: {exc}"},
        )
    info["imagens"] = {"frente": caminho_frente, "verso": caminho_verso}

    # 4. salvar o lead só se pedido explicitamente (compatibilidade)
    lead_id = None
    if _verdadeiro(salvar):
        try:
            lead = dict(legado)
            lead["foto_frente_path"] = caminho_frente
            lead["foto_verso_path"] = caminho_verso
            # item 48: lead que nasce da captura tem origem 'cartao'
            lead_id = db.salvar_lead(lead, origem="cartao")
            db.salvar_cartao(lead_id, info)
        except Exception as exc:
            logger.exception("Falha ao salvar lead no SQLite: %r", exc)
            for f in fotos_salvas:
                _apagar_foto(f)
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "Falha ao salvar no banco. Tente novamente."},
            )
        logger.info("Lead #%s salvo (extração com salvar=1)", lead_id)

    logger.info(
        "Cartão analisado: %d telefone(s), OCR=%s, VLM=%s",
        len(info["telefones"]), analise.ocr_ok, not analise.erro_vlm,
    )
    return {
        "success": True,
        "id": lead_id,
        "data": legado,          # formato antigo — clientes existentes seguem funcionando
        "cartao": info,          # 📇 INFORMAÇÕES DO CARTÃO (novo)
        "fotos": {"frente": caminho_frente, "verso": caminho_verso},
        "avisos": info.get("avisos", []),
    }


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
    """Persiste o formulário completo (campos manuais + INFORMAÇÕES DO CARTÃO).

    Se vier 'lead_id' de um lead já salvo, atualiza em vez de duplicar.

    Contrato multipart:
      - campos do lead (db.CAMPOS) — textos digitados pelo vendedor;
      - cartao_json — JSON com a estrutura de app.cartao.info (📇 do cartão);
      - foto_frente_path / foto_verso_path — caminhos já gravados pelo /extract
        (reaproveitados, evita duplicar arquivos);
      - foto_frente / foto_verso — arquivos novos (têm prioridade; o path
        reaproveitado do /extract é apagado quando é substituído).

    O cartão NUNCA sobrescreve campos manuais: ele vai para a tabela separada
    lead_cartao, vinculada ao MESMO lead (itens 17/18 do projeto).
    """
    form = await request.form()

    # M10: criação pública de leads é ilimitada por padrão — limite por IP
    if _limite_estourado(request, "leads", 30, 60):
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "error": "Muitos envios em sequência — aguarde um minuto e tente de novo.",
            },
        )

    # cartão (📇 INFORMAÇÕES DO CARTÃO) — parse defensivo ANTES de qualquer
    # efeito colateral (fotos/banco), para um JSON inválido não deixar lixo.
    cartao = None
    cartao_json = form.get("cartao_json")
    if cartao_json is not None and str(cartao_json).strip():
        try:
            cartao = json.loads(str(cartao_json))
        except json.JSONDecodeError as exc:
            return JSONResponse(
                status_code=422,
                content={"success": False, "error": f"cartao_json inválido: {exc}"},
            )
        if not isinstance(cartao, dict):
            return JSONResponse(
                status_code=422,
                content={"success": False, "error": "cartao_json deve ser um objeto JSON."},
            )

    dados: dict = {}
    for campo in db.CAMPOS:
        valor = form.get(campo)
        if valor is not None and not _eh_arquivo(valor):
            dados[campo] = str(valor).strip()

    for lado, campo_foto in (("frente", "foto_frente"), ("verso", "foto_verso")):
        arquivo = form.get(campo_foto)
        if _eh_arquivo(arquivo):
            conteudo = await arquivo.read()
            if conteudo:
                try:
                    novo_caminho = salvar_foto(conteudo, lado)
                except ValueError as exc:
                    return JSONResponse(
                        status_code=422, content={"success": False, "error": str(exc)}
                    )
                # path reaproveitado do /extract foi substituído — vira órfão
                antigo_caminho = dados.get(f"foto_{lado}_path")
                if antigo_caminho and antigo_caminho != novo_caminho:
                    _apagar_foto(antigo_caminho)
                dados[f"foto_{lado}_path"] = novo_caminho
            await arquivo.close()

    try:
        lead_id = int(form.get("lead_id") or 0)
    except (TypeError, ValueError):
        lead_id = 0

    # C1 (auditoria fix_final): a rota é pública para a CAPTURA de lead novo
    # (sem lead_id). Editar/sobrescrever um lead existente exige sessão de
    # admin válida — antes qualquer pessoa na internet podia mandar um
    # lead_id arbitrário e reescrever dados sensíveis de outro lead (inclusive
    # apagar fotos e trocar o JSON do cartão).
    if lead_id and not auth.cookie_valido(request.cookies.get(auth.SESSION_COOKIE)):
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error": "Não autenticado — faça login para editar um lead.",
            },
        )

    # origem (item 18/47/48): campo explícito tem prioridade; sem campo,
    # o lead que nasce com cartão é 'cartao' (captura) e o manual é 'manual'.
    # Na EDIÇÃO (lead existente) a origem nunca muda (item 47).
    origem = str(form.get("origem") or "").strip()
    if origem not in ("manual", "cartao"):
        origem = ""

    try:
        existente = db.buscar_lead(lead_id) if lead_id else None
        if lead_id and not existente:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Lead não encontrado."},
            )
        # 5.5: bdr/sdr só editam leads em que são o responsável atual — mesma
        # regra aplicada nas APIs do funil (A3), agora também na edição.
        if existente:
            restrito = _restricao_visivel(usuario_logado(request))
            if restrito and existente.get("responsavel_atual") != restrito:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "error": "Lead não encontrado."},
                )
        antigas = (
            [existente.get("foto_frente_path"), existente.get("foto_verso_path")]
            if existente
            else []
        )
        if existente:
            db.atualizar_lead(lead_id, dados)
        else:
            nova_origem = origem or ("cartao" if cartao is not None else "manual")
            lead_id = db.salvar_lead(dados, origem=nova_origem)
        # apaga fotos antigas substituídas por novas nesta atualização (evita órfãos)
        novas = {dados.get("foto_frente_path"), dados.get("foto_verso_path")}
        for f in antigas:
            if f and f not in novas:
                _apagar_foto(f)
        # grava as INFORMAÇÕES DO CARTÃO no MESMO lead (tabela separada — nada
        # aqui toca nos campos manuais do lead, item 17/18 do projeto)
        if cartao is not None:
            cartao.setdefault("imagens", {})
            cartao["imagens"]["frente"] = dados.get("foto_frente_path") or ""
            cartao["imagens"]["verso"] = dados.get("foto_verso_path") or ""
            db.salvar_cartao(lead_id, cartao)
    except Exception as exc:
        logger.exception("Falha ao salvar lead completo: %r", exc)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Falha ao salvar no banco. Tente novamente."},
        )
    logger.info("Lead #%s salvo (formulário completo)", lead_id)
    return {"success": True, "id": lead_id}


# ------------------------------------------------------------- admin: login

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, erro: str = ""):
    # B16: a página NÃO expõe mais a lista de usuários do time (nomes + papéis)
    # sem autenticação — engenharia social. A lista só aparece na etapa 2,
    # depois de a senha correta ser digitada (ver admin_login_post).
    return templates.TemplateResponse(
        request, "admin_login.html",
        {"erro": erro, "usuarios": [], "token": ""},
    )


def _resposta_login(
    request: Request, erro: str, usuarios: list, token: str = "", status: int = 200
):
    """Renderiza a página de login (B16: sem usuários na etapa 1)."""
    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {"erro": erro, "usuarios": usuarios, "token": token},
        status_code=status,
    )


@app.post("/admin/login")
async def admin_login_post(
    request: Request, senha: str = Form(""), usuario: str = Form(""), token: str = Form("")
):
    # A1: sem SESSION_SECRET configurado o login é negado (fail-closed).
    if not auth.sessao_disponivel():
        logger.error("Login recusado: SESSION_SECRET não configurado no .env")
        return _resposta_login(
            request, "Login temporariamente indisponível — fale com o responsável técnico.", []
        )

    # M10: força bruta — no máximo 10 tentativas por IP a cada 5 min
    if _limite_estourado(request, "login", 10, 300):
        logger.warning("Muitas tentativas de login — ip=%s", request.client.host if request.client else "?")
        return _resposta_login(
            request, "Muitas tentativas de login — aguarde 5 minutos.", [], status=429
        )

    # etapa 2 — a senha já foi conferida (token curto assinado); aqui só se
    # escolhe quem está entrando. O token expira em TOKEN_LOGIN_MAX_AGE.
    if token:
        if not auth.token_login_valido(token):
            logger.warning("Token de login expirado/inválido")
            return _resposta_login(
                request, "Sessão de login expirada — digite a senha de novo.", [], status=401
            )
        usuario = usuario.strip()
        if usuario and not db.buscar_usuario(usuario):
            return _resposta_login(
                request, "Usuário não encontrado. Selecione um nome válido.", [], status=401
            )
        return _criar_sessao(request, usuario or None)

    # etapa 1 — a senha
    if not auth.senha_confere(senha):
        logger.warning("Tentativa de login admin com senha incorreta")
        return _resposta_login(
            request, "Senha incorreta. Tente novamente.", [], status=401
        )
    usuario = usuario.strip()
    if usuario:
        # fluxo direto (senha + usuário no mesmo POST — usado nos testes e
        # em clientes antigos)
        if not db.buscar_usuario(usuario):
            return _resposta_login(
                request, "Usuário não encontrado. Selecione um nome válido.", [], status=401
            )
        return _criar_sessao(request, usuario)
    # senha certa, sem usuário: agora sim a lista de usuários aparece (B16) —
    # com um token curto que prova que a senha já foi validada.
    logger.info("Senha OK — escolhendo usuário do time")
    return _resposta_login(
        request, "", db.listar_usuarios(), token=auth.criar_token_login()
    )


def _criar_sessao(request: Request, usuario: str | None) -> RedirectResponse:
    """Grava o cookie de sessão e manda pro painel."""
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(
        auth.SESSION_COOKIE,
        auth.criar_cookie_valor(usuario),
        httponly=True,
        secure=(request.url.scheme == "https"),
        samesite="lax",
        max_age=auth.SESSION_MAX_AGE,
    )
    logger.info("Login OK (usuario=%s)", usuario or "admin")
    return resp


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
        "tesseract_ok": ocr_mod.disponivel(),
        "tesseract_idiomas": ocr_mod.idiomas() if ocr_mod.disponivel() else "",
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
    request: Request,
    busca: str = "",
    de: str | None = None,
    ate: str | None = None,
    limite: int = 100,
):
    # A2: bdr/sdr só enxergam os próprios leads — a regra 5.5 que o funil
    # aplica vale também para estas APIs (antes um SDR via TODOS os leads
    # chamando /api/leads direto).
    restrito = _restricao_visivel(usuario_logado(request))
    leads = db.listar_leads(
        busca=busca, de=de, ate=ate, responsavel=restrito,
        limite=max(1, min(limite, 1000)),
    )
    return {"success": True, "total": len(leads), "leads": leads}


@app.get("/api/leads/export", dependencies=[Depends(exige_admin_api)])
def exportar_csv(
    request: Request,
    busca: str = "",
    de: str | None = None,
    ate: str | None = None,
):
    """Exporta leads filtrados em CSV (com BOM, abre certo no Excel).

    A2: mesma visibilidade 5.5 da listagem — o CSV de um bdr/sdr só sai
    com os leads dele. M8: valores que começam com =,+,-,@ ganham um ' na
    frente (CSV injection — o Excel não executa fórmula vinda do arquivo).
    """
    restrito = _restricao_visivel(usuario_logado(request))
    leads = db.listar_leads(
        busca=busca, de=de, ate=ate, responsavel=restrito, limite=10000
    )
    colunas = ["id", "criado_em"] + db.CAMPOS
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(colunas)
    for lead in leads:
        writer.writerow([_csv_seguro(lead.get(c, "")) for c in colunas])
    conteudo = "\ufeff" + buf.getvalue()
    nome = f"leads-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
    return Response(
        content=conteudo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


def _csv_seguro(valor) -> str:
    """M8: prefixa ' em valores que o Excel interpretaria como fórmula."""
    texto = str(valor or "")
    if texto and texto[0] in "=+-@":
        return "'" + texto
    return texto


@app.get("/api/leads/{lead_id}", dependencies=[Depends(exige_admin_api)])
def api_detalhe_lead(lead_id: int, request: Request):
    """Detalhe do lead + suas INFORMAÇÕES DO CARTÃO (chave 'cartao').

    A2: bdr/sdr não abrem detalhe de lead de outro responsável (404)."""
    lead = db.buscar_lead_completo(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    restrito = _restricao_visivel(usuario_logado(request))
    if restrito and lead.get("responsavel_atual") != restrito:
        raise HTTPException(status_code=404, detail="Lead não encontrado")
    return {"success": True, "lead": lead}


# ------------------------------------------------------- funil de vendas
# Tela operacional do time (funildevendas.md) — NÃO é admin genérico, mas usa
# a mesma sessão do login. O fluxo de captura (/extract, /leads) fica intocado.

@app.get("/funil", dependencies=[Depends(exige_admin)])
def funil_page(request: Request):
    from .funil import (
        DIAS_ESTAGNADO,
        ESTAGIOS,
        MOTIVOS_PERDA,
        RESPONSAVEIS,
        ROTULOS_ESTAGIOS,
        TIPOS_ATIVIDADE,
    )

    return templates.TemplateResponse(
        request,
        "funil.html",
        {
            "estagios": ESTAGIOS,
            "rotulos": ROTULOS_ESTAGIOS,
            "responsaveis": RESPONSAVEIS,
            "motivos_perda": MOTIVOS_PERDA,
            "tipos_atividade": TIPOS_ATIVIDADE,
            "dias_estagnado": DIAS_ESTAGNADO,
            "usuario_logado": usuario_logado(request),
        },
    )


@app.post("/funil", dependencies=[Depends(exige_admin_api)])
async def funil_novo_lead(request: Request):
    """[+ Novo Lead] direto na tela do funil (item 50 da spec).

    Aceita JSON ou form com os campos de db.CAMPOS; o lead nasce em
    estágio 'novo' com origem 'manual'. Não toca no fluxo de captura.
    V3 (5.1): aceita 'valor_estimado' para o cálculo de valor esperado.
    """
    usuario = usuario_logado(request)
    try:
        corpo = await request.json()
        if not isinstance(corpo, dict):
            corpo = {}
    except Exception:
        corpo = dict((await request.form()).items())
    dados = {c: corpo.get(c, "") for c in db.CAMPOS}
    if not str(dados.get("nome_empresa") or dados.get("nome_contato") or "").strip():
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": "Informe ao menos a empresa ou o contato do lead.",
            },
        )
    try:
        valor = float(corpo.get("valor_estimado") or 0)
    except (TypeError, ValueError):
        valor = 0.0
    lead_id = db.salvar_lead(dados, origem="manual")
    if valor > 0:
        db.salvar_valor_estimado(lead_id, valor)
    # quem criou é o responsável (5.5: BDR/SDR agem sobre o próprio lead)
    if usuario["papel"] != "gestor" and usuario["nome"]:
        db.registrar_responsavel(lead_id, usuario["nome"])
    return {"success": True, "id": lead_id, "lead": db.buscar_lead_funil(lead_id)}


@app.get("/api/funil/metricas", dependencies=[Depends(exige_admin_api)])
def api_funil_metricas(request: Request, de: str | None = None, ate: str | None = None):
    """Contagem por estágio, conversão, tempo médio e valor esperado (V3 5.1).

    Visibilidade (5.5): bdr/sdr só veem as métricas dos próprios leads."""
    _validar_filtros(de=de, ate=ate)
    return {
        "success": True,
        "metricas": db.metricas_funil(
            de=de, ate=ate, responsavel=_restricao_visivel(usuario_logado(request))
        ),
    }


@app.get("/api/funil/relatorio-perdas", dependencies=[Depends(exige_admin_api)])
def api_funil_relatorio_perdas(
    request: Request, de: str | None = None, ate: str | None = None
):
    """V3 (5.4): contagem de leads perdidos por motivo × origem × responsável.
    Sem tabela nova — lê direto de leads (estagio='perdido').

    Declarada ANTES de /api/funil/{lead_id} para não ser capturada pelo
    parâmetro de rota (que exige inteiro e devolveria 422)."""
    _validar_filtros(de=de, ate=ate)
    return {
        "success": True,
        "relatorio": db.relatorio_perdas(
            de=de, ate=ate, responsavel=_restricao_visivel(usuario_logado(request))
        ),
    }


@app.get("/api/funil", dependencies=[Depends(exige_admin_api)])
def api_funil_listar(
    request: Request,
    busca: str = "",
    responsavel: str = "",
    estagio: str = "",
    origem: str = "",
    de: str | None = None,
    ate: str | None = None,
    sem_contato: str = "",
    atrasados: str = "",
    retorno_hoje: str = "",
    limite: int = 500,
):
    """Kanban com filtros V2 (itens 31–34): origem, sem contato, atrasados,
    retorno hoje e busca ampliada (telefone/e-mail).

    Visibilidade (5.5): o filtro por responsável de bdr/sdr é APLICADO AQUI,
    no backend — o que o cliente pedir não amplia a visão."""
    _validar_filtros(estagio=estagio, origem=origem, de=de, ate=ate)
    restrito = _restricao_visivel(usuario_logado(request))
    leads = db.listar_funil(
        busca=busca, responsavel=restrito or responsavel, estagio=estagio,
        origem=origem, de=de, ate=ate,
        sem_contato=_verdadeiro(sem_contato),
        atrasados=_verdadeiro(atrasados),
        retorno_hoje=_verdadeiro(retorno_hoje),
        limite=limite,
    )
    return {"success": True, "total": len(leads), "leads": leads}


@app.get("/api/funil/{lead_id}", dependencies=[Depends(exige_admin_api)])
def api_funil_detalhe(lead_id: int, request: Request):
    _garantir_visivel(request, lead_id)  # 404 se fora da visão (5.5)
    lead = db.buscar_lead_funil(lead_id)
    return {"success": True, "lead": lead}


@app.post("/api/funil/{lead_id}/estagio", dependencies=[Depends(exige_admin_api)])
async def api_funil_mover_estagio(lead_id: int, request: Request):
    _garantir_visivel(request, lead_id)  # A3: BDR/SDR não movem lead alheio
    usuario = usuario_logado(request)
    try:
        corpo = await request.json()
    except Exception:
        corpo = {}
    estagio = str(corpo.get("estagio", "")).strip()
    enviado = str(corpo.get("usuario", "")).strip()
    observacao = str(corpo.get("observacao", "")).strip()
    motivo_perda = str(corpo.get("motivo_perda", "")).strip()
    try:
        lead = db.mudar_estagio(
            lead_id, estagio, usuario=_responsavel_da_acao(usuario, enviado),
            observacao=observacao, motivo_perda=motivo_perda,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422, content={"success": False, "error": str(exc)}
        )
    return {"success": True, "lead": lead}


@app.post("/api/funil/{lead_id}/ligacao", dependencies=[Depends(exige_admin_api)])
async def api_funil_ligacao(lead_id: int, request: Request):
    _garantir_visivel(request, lead_id)  # A3
    usuario = usuario_logado(request)
    try:
        corpo = await request.json()
    except Exception:
        corpo = {}
    feita = _verdadeiro(corpo.get("feita", True))
    virou_lead = _verdadeiro(corpo.get("virou_lead", False))
    observacao = str(corpo.get("observacao", "")).strip()
    enviado = str(corpo.get("usuario", "")).strip()
    try:
        lead = db.registrar_ligacao(
            lead_id, feita, virou_lead, observacao,
            _responsavel_da_acao(usuario, enviado),
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422, content={"success": False, "error": str(exc)}
        )
    return {"success": True, "lead": lead}


@app.post("/api/funil/{lead_id}/atividade", dependencies=[Depends(exige_admin_api)])
async def api_funil_atividade(lead_id: int, request: Request):
    """[+ Registrar interação] (item 25): whatsapp/email/proposta/observacao/outro."""
    _garantir_visivel(request, lead_id)  # A3
    usuario = usuario_logado(request)
    try:
        corpo = await request.json()
    except Exception:
        corpo = {}
    tipo = str(corpo.get("tipo", "")).strip()
    descricao = str(corpo.get("descricao", "")).strip()
    enviado = (
        str(corpo.get("usuario", "")).strip()
        or str(corpo.get("responsavel", "")).strip()
    )
    try:
        db.registrar_interacao(
            lead_id, tipo, descricao, _responsavel_da_acao(usuario, enviado)
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422, content={"success": False, "error": str(exc)}
        )
    # resposta com a timeline atualizada (mesmo formato do detalhe)
    return {"success": True, "lead": db.buscar_lead_funil(lead_id)}


@app.post("/api/funil/{lead_id}/proxima-acao", dependencies=[Depends(exige_admin_api)])
async def api_funil_proxima_acao(lead_id: int, request: Request):
    """Próxima ação do lead (item 21): acao + data + observacao."""
    _garantir_visivel(request, lead_id)  # A3
    usuario = usuario_logado(request)
    try:
        corpo = await request.json()
    except Exception:
        corpo = {}
    acao = str(corpo.get("acao", "")).strip()
    data = str(corpo.get("data", "")).strip()
    observacao = str(corpo.get("observacao", "")).strip()
    enviado = str(corpo.get("usuario", "")).strip()
    try:
        db.salvar_proxima_acao(
            lead_id, acao, data, observacao,
            _responsavel_da_acao(usuario, enviado),
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422, content={"success": False, "error": str(exc)}
        )
    # resposta com a timeline atualizada (mesmo formato do detalhe)
    return {"success": True, "lead": db.buscar_lead_funil(lead_id)}


@app.post("/api/funil/{lead_id}/dados", dependencies=[Depends(exige_admin_api)])
async def api_funil_dados(lead_id: int, request: Request):
    """V3 (5.1): atualiza o valor estimado do lead. Campo dado, não estado."""
    _garantir_visivel(request, lead_id)  # A3
    try:
        corpo = await request.json()
    except Exception:
        corpo = {}
    if "valor_estimado" not in corpo:
        return JSONResponse(
            status_code=422,
            content={"success": False, "error": "Informe 'valor_estimado'."},
        )
    try:
        valor = float(corpo.get("valor_estimado") or 0)
    except (TypeError, ValueError):
        return JSONResponse(
            status_code=422,
            content={"success": False, "error": "'valor_estimado' deve ser um número."},
        )
    try:
        lead = db.salvar_valor_estimado(lead_id, valor)
    except ValueError as exc:
        return JSONResponse(
            status_code=422, content={"success": False, "error": str(exc)}
        )
    return {"success": True, "lead": lead}


@app.post("/api/funil/{lead_id}/atividade/{atividade_id}/concluir", dependencies=[Depends(exige_admin_api)])
async def api_funil_concluir_atividade(lead_id: int, atividade_id: int, request: Request):
    """V3 (5.2): concluir uma próxima ação agendada (por ID — decisão
    documentada no docs; não por proximidade de data)."""
    _garantir_visivel(request, lead_id)  # A3
    usuario = usuario_logado(request)
    try:
        lead = db.concluir_atividade(
            lead_id, atividade_id, _responsavel_da_acao(usuario, "")
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422, content={"success": False, "error": str(exc)}
        )
    return {"success": True, "lead": db.buscar_lead_funil(lead_id)}


@app.post("/api/funil/{lead_id}/atividade/{atividade_id}/cancelar", dependencies=[Depends(exige_admin_api)])
async def api_funil_cancelar_atividade(lead_id: int, atividade_id: int, request: Request):
    """V3 (5.2): cancelar uma próxima ação agendada."""
    _garantir_visivel(request, lead_id)  # A3
    usuario = usuario_logado(request)
    try:
        lead = db.cancelar_atividade(
            lead_id, atividade_id, _responsavel_da_acao(usuario, "")
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422, content={"success": False, "error": str(exc)}
        )
    return {"success": True, "lead": db.buscar_lead_funil(lead_id)}



@app.get("/fotos/{nome}", dependencies=[Depends(exige_admin_api)])
def servir_foto(nome: str, request: Request):
    """Serve fotos salvas em data/fotos/ (somente com sessão admin).

    B17: além da sessão, um bdr/sdr só baixa foto de lead em que é o
    responsável atual — antes qualquer autenticado podia buscar fotos de
    qualquer lead por nome (IDOR leve por foto)."""
    if "/" in nome or "\\" in nome or ".." in nome or not nome.endswith(".jpg"):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    restrito = _restricao_visivel(usuario_logado(request))
    if restrito:
        lead_id = db.buscar_lead_por_foto(nome)
        lead = db.buscar_lead(lead_id) if lead_id else None
        if not lead or lead.get("responsavel_atual") != restrito:
            raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    caminho = db.FOTOS_DIR / nome
    if not caminho.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(caminho, media_type="image/jpeg")
