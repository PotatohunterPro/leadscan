"""
Análise do cartão de visita — orquestra o pipeline inteiro:

    FOTO -> PRÉ-PROCESSAMENTO -> OCR -> LFM2.5-VL -> FUSÃO
         -> VALIDAÇÃO -> 📇 INFORMAÇÕES DO CARTÃO

O resultado é uma camada COMPLEMENTAR do lead: nada aqui sobrescreve o que o
vendedor digitou. Quem decide aproveitar algo é o usuário, clicando em
"Usar no Lead" na interface.

Frente e verso são um cartão só: as duas imagens entram no mesmo resultado
(nunca dois leads, nunca dois registros).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import imagem as img_mod
from . import ocr as ocr_mod
from . import validadores as val

logger = logging.getLogger("leadscan.cartao")

VERSAO_CARTAO = 1

_PESO_TIPO = {"whatsapp": 3, "celular": 2, "fixo": 1, "desconhecido": 0}


@dataclass
class AnaliseCartao:
    info: dict = field(default_factory=dict)
    jpeg_frente: bytes = b""
    jpeg_verso: bytes | None = None
    erro_vlm: str = ""
    ocr_ok: bool = False


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def info_vazia() -> dict:
    return {
        "versao": VERSAO_CARTAO,
        "gerado_em": agora_iso(),
        "empresa": {"nome": "", "nome_fantasia": "", "ramo_atividade": ""},
        "pessoa": {"nome": "", "cargo": ""},
        "telefones": [],
        "emails": [],
        "sites": [],
        "redes_sociais": [],
        "endereco": {
            "logradouro": "", "numero": "", "complemento": "", "bairro": "",
            "cidade": "", "uf": "", "cep": "", "texto": "",
        },
        "documentos": {"cnpj": ""},
        "outras_informacoes": [],
        "ocr": {
            "disponivel": False, "texto": "", "frente": "", "verso": "",
            "confianca": 0.0,
        },
        "vlm": {"disponivel": False, "erro": "", "bruto": {}},
        "avisos": [],
        "imagens": {"frente": "", "verso": ""},
        "sugestoes": [],
    }


# ------------------------------------------------------------------ fusão

def _mesclar_telefones(*listas: list[dict]) -> list[dict]:
    """Junta telefones de várias origens SEM sobrescrever nenhum número.

    Números iguais viram um registro só (mantendo o tipo mais específico e a
    maior confiança). Números diferentes coexistem — cartão com 3 números
    devolve 3 telefones.
    """
    saida: list[dict] = []
    indice: dict[str, dict] = {}
    for lista in listas:
        for tel in lista or []:
            digitos = tel.get("digitos") or val.apenas_digitos(tel.get("numero"))
            if not digitos:
                continue
            existente = indice.get(digitos)
            if existente is None:
                novo = dict(tel)
                novo["digitos"] = digitos
                indice[digitos] = novo
                saida.append(novo)
                continue
            # já existe: fica o tipo mais específico e a maior confiança
            if _PESO_TIPO.get(tel.get("tipo", ""), 0) > _PESO_TIPO.get(
                existente.get("tipo", ""), 0
            ):
                existente["tipo"] = tel["tipo"]
            if float(tel.get("confianca", 0)) > float(existente.get("confianca", 0)):
                existente["confianca"] = tel["confianca"]
            origens = {existente.get("origem", ""), tel.get("origem", "")} - {""}
            existente["origem"] = "+".join(sorted(origens))
    return saida


def _telefones_do_vlm(bruto: dict, digitos_ocr: str, ocr_ok: bool) -> list[dict]:
    """Telefones citados pelo modelo — só entram se o OCR confirmar.

    Isso impede que o modelo 'invente' ou complete números (regra 13).
    """
    candidatos: list[str] = []
    valor = bruto.get("telefones")
    if isinstance(valor, list):
        candidatos.extend(str(v) for v in valor)
    elif valor:
        candidatos.append(str(valor))
    for chave in ("telefone", "whatsapp", "celular"):
        if bruto.get(chave):
            candidatos.append(str(bruto[chave]))

    saida: list[dict] = []
    for bruto_numero in candidatos:
        tel = val.normalizar_telefone(bruto_numero)
        if not tel:
            continue
        if ocr_ok and not val.suportado_pelo_ocr(tel["digitos"], digitos_ocr):
            logger.info("Descartado número sem apoio do OCR: %s", tel["numero"])
            continue
        contexto = bruto_numero
        if bruto.get("whatsapp") and val.apenas_digitos(str(bruto["whatsapp"])) == tel["digitos"]:
            contexto += " whatsapp"
        tipo = tel["tipo"]
        if "whats" in contexto.lower() or "zap" in contexto.lower():
            tipo = "whatsapp"
        tel["tipo"] = tipo
        tel["origem"] = "vlm"
        tel["confianca"] = 0.8 if ocr_ok else 0.5
        saida.append(tel)
    return saida


def _limpar_linhas(texto: str) -> list[str]:
    return [val.normalizar_espacos(l) for l in (texto or "").splitlines() if l.strip()]


def _linha_ja_usada(linha: str, usados: list[str]) -> bool:
    base = val.sem_acento(linha).lower()
    for u in usados:
        u = val.sem_acento(u).lower().strip()
        if u and (u in base or base in u):
            return True
    return False


def _nome_empresa_do_ocr(texto: str) -> str:
    """Palpite conservador: primeira linha 'de nome' do cartão."""
    for linha in _limpar_linhas(texto):
        if len(linha) < 3 or len(linha) > 60:
            continue
        if val.extrair_telefones(linha) or val.extrair_emails(linha):
            continue
        if val.extrair_urls(linha)[0] or val.extrair_ceps(linha):
            continue
        letras = sum(1 for c in linha if c.isalpha())
        if letras < max(3, len(linha) * 0.5):
            continue
        return linha
    return ""


def fundir(
    texto_ocr: str,
    bruto_vlm: dict,
    ocr_ok: bool,
    texto_frente: str = "",
    texto_verso: str = "",
    confianca_ocr: float = 0.0,
    avisos: list[str] | None = None,
    erro_vlm: str = "",
) -> dict:
    """Junta OCR (determinístico) + VLM (interpretação) em UM cartão."""
    info = info_vazia()
    bruto_vlm = bruto_vlm or {}
    avisos = list(avisos or [])
    digitos_ocr = val.digitos_do_texto(texto_ocr)

    # ---------------- telefones: OCR primeiro, VLM só confirmando
    tels_ocr = val.extrair_telefones(texto_ocr, origem="ocr")
    tels_vlm = _telefones_do_vlm(bruto_vlm, digitos_ocr, ocr_ok)
    info["telefones"] = _mesclar_telefones(tels_ocr, tels_vlm)

    # ---------------- e-mails, sites e redes sociais
    emails = [{"valor": e, "origem": "ocr"} for e in val.extrair_emails(texto_ocr)]
    vistos_email = {e["valor"] for e in emails}
    email_vlm = val.normalizar_email(str(bruto_vlm.get("email", "")))
    if email_vlm and email_vlm not in vistos_email:
        if not ocr_ok or val.texto_suportado_pelo_ocr(email_vlm.split("@")[0], texto_ocr, 0.5):
            emails.append({"valor": email_vlm, "origem": "vlm"})
    info["emails"] = emails

    sites_ocr, redes_ocr = val.extrair_urls(texto_ocr)
    sites = [{"valor": s, "origem": "ocr"} for s in sites_ocr]
    vistos_site = {s["valor"] for s in sites}
    site_vlm = val.normalizar_url(str(bruto_vlm.get("site", "")))
    if site_vlm and site_vlm not in vistos_site:
        if not ocr_ok or val.texto_suportado_pelo_ocr(site_vlm, texto_ocr, 0.5):
            sites.append({"valor": site_vlm, "origem": "vlm"})
    info["sites"] = sites

    redes: list[dict] = [dict(r, origem="ocr") for r in redes_ocr]
    for arroba in val.extrair_arrobas(texto_ocr):
        if not any(r["valor"].lower().endswith(arroba["usuario"].lower()) for r in redes):
            redes.append(dict(arroba, origem="ocr"))
    brutas_vlm = bruto_vlm.get("redes_sociais")
    lista_vlm = brutas_vlm if isinstance(brutas_vlm, list) else ([brutas_vlm] if brutas_vlm else [])
    for item in lista_vlm:
        texto_item = str(item)
        s_extra, r_extra = val.extrair_urls(texto_item)
        for r in r_extra:
            if not any(r["valor"] == x["valor"] for x in redes):
                if not ocr_ok or val.texto_suportado_pelo_ocr(r["valor"], texto_ocr, 0.5):
                    redes.append(dict(r, origem="vlm"))
        for s in s_extra:
            if not any(s == x["valor"] for x in sites):
                if not ocr_ok or val.texto_suportado_pelo_ocr(s, texto_ocr, 0.5):
                    sites.append({"valor": s, "origem": "vlm"})
    info["redes_sociais"] = redes

    # ---------------- endereço: OCR manda nos números, VLM ajuda no resto
    endereco = info["endereco"]
    log = val.extrair_logradouro(texto_ocr)
    endereco.update({k: v for k, v in log.items() if v})
    ceps = val.extrair_ceps(texto_ocr)
    if ceps:
        endereco["cep"] = ceps[0]
    cidade, uf = val.extrair_cidade_uf(texto_ocr)
    if cidade:
        endereco["cidade"] = cidade
    if uf:
        endereco["uf"] = uf

    if not endereco["logradouro"]:
        candidato = val.extrair_logradouro(str(bruto_vlm.get("endereco", "")))
        if candidato["logradouro"] and (
            not ocr_ok or val.texto_suportado_pelo_ocr(candidato["logradouro"], texto_ocr, 0.5)
        ):
            endereco.update({k: v for k, v in candidato.items() if v})
    if not endereco["cep"]:
        cep_vlm = val.normalizar_cep(str(bruto_vlm.get("cep", "")))
        if cep_vlm and (not ocr_ok or val.suportado_pelo_ocr(
            val.apenas_digitos(cep_vlm), digitos_ocr)):
            endereco["cep"] = cep_vlm
    if not endereco["cidade"]:
        cidade_vlm = val.normalizar_espacos(str(bruto_vlm.get("cidade", "")))
        if cidade_vlm and (not ocr_ok or val.texto_suportado_pelo_ocr(cidade_vlm, texto_ocr, 0.6)):
            endereco["cidade"] = cidade_vlm
    if not endereco["uf"]:
        uf_vlm = val.normalizar_espacos(str(bruto_vlm.get("uf", ""))).upper()
        if uf_vlm in val.UFS:
            endereco["uf"] = uf_vlm
    if not endereco["bairro"]:
        bairro_vlm = val.normalizar_espacos(str(bruto_vlm.get("bairro", "")))
        if bairro_vlm and (not ocr_ok or val.texto_suportado_pelo_ocr(bairro_vlm, texto_ocr, 0.6)):
            endereco["bairro"] = bairro_vlm
    endereco["texto"] = montar_endereco(endereco)

    # ---------------- empresa e pessoa (interpretação = papel do VLM)
    nome_vlm = val.normalizar_espacos(str(bruto_vlm.get("nome_empresa", "")))
    if nome_vlm and (not ocr_ok or val.texto_suportado_pelo_ocr(nome_vlm, texto_ocr, 0.5)):
        info["empresa"]["nome"] = nome_vlm
    elif ocr_ok:
        info["empresa"]["nome"] = _nome_empresa_do_ocr(texto_frente or texto_ocr)
    if nome_vlm and not info["empresa"]["nome"]:
        info["empresa"]["nome"] = nome_vlm

    fantasia = val.normalizar_espacos(str(bruto_vlm.get("nome_fantasia", "")))
    if fantasia and fantasia.lower() != info["empresa"]["nome"].lower():
        if not ocr_ok or val.texto_suportado_pelo_ocr(fantasia, texto_ocr, 0.5):
            info["empresa"]["nome_fantasia"] = fantasia
    info["empresa"]["ramo_atividade"] = val.normalizar_espacos(
        str(bruto_vlm.get("ramo_atividade", ""))
    )

    pessoa = val.normalizar_espacos(str(bruto_vlm.get("nome_contato", "")))
    if pessoa and (not ocr_ok or val.texto_suportado_pelo_ocr(pessoa, texto_ocr, 0.5)):
        info["pessoa"]["nome"] = pessoa
    cargo = val.normalizar_espacos(str(bruto_vlm.get("cargo", "")))
    if cargo and (not ocr_ok or val.texto_suportado_pelo_ocr(cargo, texto_ocr, 0.5)):
        info["pessoa"]["cargo"] = cargo

    info["documentos"]["cnpj"] = val.extrair_cnpj(texto_ocr)

    # ---------------- outras informações (regra 14: preservar o máximo)
    outras: list[dict] = []
    vistos_outras: set[str] = set()

    def _add_outra(texto: str, origem: str) -> None:
        texto = val.normalizar_espacos(texto)
        chave = val.sem_acento(texto).lower()
        if len(texto) < 3 or chave in vistos_outras:
            return
        vistos_outras.add(chave)
        outras.append({"texto": texto, "origem": origem})

    brutas_outras = bruto_vlm.get("outras_informacoes")
    lista_outras = brutas_outras if isinstance(brutas_outras, list) else (
        [brutas_outras] if brutas_outras else []
    )
    for item in lista_outras:
        item = str(item)
        if not ocr_ok or val.texto_suportado_pelo_ocr(item, texto_ocr, 0.5):
            _add_outra(item, "vlm")

    # linhas do OCR que não viraram nenhum campo continuam guardadas
    usados = [
        info["empresa"]["nome"], info["empresa"]["nome_fantasia"],
        info["pessoa"]["nome"], info["pessoa"]["cargo"],
        endereco["logradouro"], endereco["bairro"], endereco["cidade"],
    ]
    usados += [t["numero"] for t in info["telefones"]]
    usados += [e["valor"] for e in info["emails"]]
    usados += [s["valor"] for s in info["sites"]]
    usados += [r["valor"] for r in info["redes_sociais"]]
    for linha in _limpar_linhas(texto_ocr):
        if len(linha) < 4:
            continue
        sem_numeros = val.apenas_digitos(linha)
        if sem_numeros and len(sem_numeros) >= len(linha) * 0.5:
            continue
        if _linha_ja_usada(linha, [u for u in usados if u]):
            continue
        if val.extrair_telefones(linha) or val.extrair_emails(linha):
            continue
        if val.extrair_ceps(linha):
            continue
        _add_outra(linha, "ocr")
    info["outras_informacoes"] = outras

    # ---------------- metadados
    info["ocr"] = {
        "disponivel": ocr_ok,
        "texto": texto_ocr or "",
        "frente": texto_frente or "",
        "verso": texto_verso or "",
        "confianca": round(float(confianca_ocr or 0.0), 1),
    }
    info["vlm"] = {
        "disponivel": bool(bruto_vlm) and not erro_vlm,
        "erro": erro_vlm or "",
        "bruto": bruto_vlm,
    }
    info["avisos"] = avisos
    info["sugestoes"] = montar_sugestoes(info)
    return info


def montar_endereco(endereco: dict) -> str:
    """Endereço em uma linha só — usado no botão 'Usar como endereço'."""
    partes: list[str] = []
    if endereco.get("logradouro"):
        rua = endereco["logradouro"]
        if endereco.get("numero"):
            rua += ", " + endereco["numero"]
        partes.append(rua)
    for chave in ("complemento", "bairro"):
        if endereco.get(chave):
            partes.append(endereco[chave])
    cidade = endereco.get("cidade", "")
    if cidade and endereco.get("uf"):
        cidade = f"{cidade} - {endereco['uf']}"
    elif not cidade and endereco.get("uf"):
        cidade = endereco["uf"]
    if cidade:
        partes.append(cidade)
    if endereco.get("cep"):
        partes.append("CEP " + endereco["cep"])
    return " — ".join(partes)


def montar_sugestoes(info: dict) -> list[dict]:
    """Pares (campo do lead, valor do cartão) para os botões 'Usar no Lead'.

    ATENÇÃO: isto é só uma SUGESTÃO exibida na interface. Nada é copiado
    sozinho — o vendedor é quem clica.
    """
    sug: list[dict] = []

    def add(campo: str, rotulo: str, valor: str) -> None:
        if valor:
            sug.append({"campo": campo, "rotulo": rotulo, "valor": valor})

    add("nome_empresa", "Usar como nome da loja", info["empresa"]["nome"]
        or info["empresa"]["nome_fantasia"])
    add("nome_contato", "Usar como nome do contato", info["pessoa"]["nome"])
    add("cargo", "Usar como cargo", info["pessoa"]["cargo"])

    for tel in info["telefones"]:
        if tel.get("tipo") in ("whatsapp", "celular"):
            add("whatsapp", f"Usar {tel['numero']} como WhatsApp do contato", tel["numero"])
        else:
            add("telefone", f"Usar {tel['numero']} como telefone da loja", tel["numero"])
    for email in info["emails"]:
        add("email", f"Usar {email['valor']} como e-mail", email["valor"])
    for site in info["sites"]:
        add("site", f"Usar {site['valor']} como site", site["valor"])
    if info["redes_sociais"]:
        add("redes_sociais", "Usar as redes sociais",
            ", ".join(r["valor"] for r in info["redes_sociais"]))
    add("endereco", "Usar como endereço", info["endereco"]["texto"])
    add("cidade", "Usar como cidade", info["endereco"]["cidade"])
    add("ramo_atividade", "Usar como segmento", info["empresa"]["ramo_atividade"])
    return sug


def para_campos_legado(info: dict) -> dict:
    """Formato antigo e achatado de /extract (compatibilidade com clientes)."""
    tel = next((t["numero"] for t in info["telefones"] if t.get("tipo") == "fixo"), "")
    wpp = next(
        (t["numero"] for t in info["telefones"] if t.get("tipo") in ("whatsapp", "celular")),
        "",
    )
    return {
        "nome_empresa": info["empresa"]["nome"],
        "nome_contato": info["pessoa"]["nome"],
        "telefone": tel or (info["telefones"][0]["numero"] if info["telefones"] else ""),
        "whatsapp": wpp,
        "email": info["emails"][0]["valor"] if info["emails"] else "",
        "site": info["sites"][0]["valor"] if info["sites"] else "",
        "endereco": info["endereco"]["texto"],
        "cidade": info["endereco"]["cidade"],
        "ramo_atividade": info["empresa"]["ramo_atividade"],
        "redes_sociais": ", ".join(r["valor"] for r in info["redes_sociais"]),
    }


# ------------------------------------------------------------------ pipeline

async def analisar(
    frente_bytes: bytes,
    verso_bytes: bytes | None = None,
    chamar_vlm=None,
) -> AnaliseCartao:
    """Executa o pipeline completo do cartão (frente + verso opcional).

    As fotos são processadas SEQUENCIALMENTE — nunca as duas na memória ao
    mesmo tempo em resolução alta (limite de ~1 GB de RAM).

    'chamar_vlm' é injetável nos testes; por padrão usa o Ollama local.
    """
    if chamar_vlm is None:
        from .ollama_client import extrair_dados_cartao as chamar_vlm  # noqa: PLC0415

    avisos: list[str] = []
    textos: list[str] = []
    confiancas: list[float] = []
    ocr_ok = False

    # --- frente (obrigatória)
    prep_frente = img_mod.preparar(frente_bytes, "frente")
    try:
        res_frente = ocr_mod.ler(prep_frente)
    finally:
        prep_frente.liberar()
    avisos.extend(res_frente.avisos)
    if res_frente.texto:
        textos.append(res_frente.texto)
        confiancas.append(res_frente.confianca)
    ocr_ok = ocr_ok or bool(res_frente.texto)
    jpeg_frente = prep_frente.vlm_jpeg

    # --- verso (opcional) — MESMO cartão, nunca um segundo lead
    texto_verso = ""
    jpeg_verso = None
    if verso_bytes:
        prep_verso = img_mod.preparar(verso_bytes, "verso")
        try:
            res_verso = ocr_mod.ler(prep_verso)
        finally:
            prep_verso.liberar()
        avisos.extend(a for a in res_verso.avisos if a not in avisos)
        texto_verso = res_verso.texto
        if texto_verso:
            textos.append(texto_verso)
            confiancas.append(res_verso.confianca)
            ocr_ok = True
        jpeg_verso = prep_verso.vlm_jpeg

    texto_ocr = "\n".join(textos).strip()

    # --- interpretação visual (LFM2.5-VL local)
    imagens = [jpeg_frente] + ([jpeg_verso] if jpeg_verso else [])
    bruto_vlm: dict = {}
    erro_vlm = ""
    try:
        bruto_vlm = await chamar_vlm(imagens, texto_ocr)
    except Exception as exc:
        erro_vlm = f"{type(exc).__name__}: {exc}"
        logger.warning("VLM falhou (%s) — seguindo só com o OCR", erro_vlm)
        avisos.append(
            "A IA de visão não respondeu (" + type(exc).__name__ + "). "
            "As informações abaixo vieram apenas do OCR."
        )

    if not ocr_ok and not bruto_vlm:
        raise ValueError(
            "Não consegui ler nada do cartão: OCR sem texto e IA de visão "
            "indisponível" + (f" ({erro_vlm})" if erro_vlm else "")
        )

    info = fundir(
        texto_ocr=texto_ocr,
        bruto_vlm=bruto_vlm,
        ocr_ok=ocr_ok,
        texto_frente=res_frente.texto,
        texto_verso=texto_verso,
        confianca_ocr=(sum(confiancas) / len(confiancas)) if confiancas else 0.0,
        avisos=avisos,
        erro_vlm=erro_vlm,
    )
    return AnaliseCartao(
        info=info,
        jpeg_frente=jpeg_frente,
        jpeg_verso=jpeg_verso,
        erro_vlm=erro_vlm,
        ocr_ok=ocr_ok,
    )
