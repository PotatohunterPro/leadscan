# Plano de implementação — LeadScan V2

Base: `V2.md` (especificação) + leitura completa do projeto (arquivos atuais).

## 0. Estado atual (levantamento feito)

### Já implementado no backend (não commitado — `git status` mostra M em db.py/main.py/ollama_client.py e ?? em cartao.py/imagem.py/ocr.py/validadores.py)

| Módulo | Cobre os itens do V2 |
|---|---|
| `app/imagem.py` | 11 (pré-processamento: EXIF, orientação, escala 1600–1800px p/ OCR, 1024px p/ VLM, cinza, contraste, nitidez, threshold Otsu; só Pillow) |
| `app/ocr.py` | 10, 15 (Tesseract local por+eng, PSM 6, fallback de rotação 90/180/270, degradação graciosa sem o binário) |
| `app/validadores.py` | 13 (telefone com DDD válido, CEP, e-mail, URL, redes, endereço, CNPJ; nunca completa número ilegível) |
| `app/cartao.py` | 3, 4, 7, 12, 14, 16 (pipeline OCR→VLM→fusão→validação; frente+verso = 1 cartão; `telefones[]` com numero/tipo/origem/confianca; `outras_informacoes`; `sugestoes` p/ "Usar no Lead"; `para_campos_legado`) |
| `app/ollama_client.py` | 10 (LFM2.5-VL-450M mantido; `extrair_dados_cartao` com prompt curto + OCR como apoio; parse JSON defensivo) |
| `app/db.py` | 17, 18 (tabela `lead_cartao` 1:1 com `lead_id UNIQUE`; `salvar_cartao`/`buscar_cartao`/`buscar_lead_completo`/`leads_com_cartao`; migração por ALTER TABLE sem apagar dados) |
| `app/main.py` | 8, 9, 24 (/extract analisa e devolve `cartao` + `data` legado; não cria lead sozinho a menos que `salvar=1`; erros claros; demais rotas intactas) |

### Lacunas encontradas (o que o plano precisa fazer)

1. **`static/index.html` (frontend) não foi atualizado para V2** — maior lacuna:
   - Auto-preenche o formulário do lead com dados do cartão (`preencherFormulario(r.dados.data)`) — **contradiz o item 4** ("O cartão NÃO deve sobrescrever o lead").
   - Não exibe a seção 📇 **INFORMAÇÕES DO CARTÃO** com "Usar no Lead" (item 5) nem "[ Ver texto original ]" (item 15).
2. **`POST /leads` não persiste o cartão** — no fluxo normal (extract sem `salvar=1`), o JSON do cartão fica só na resposta; ao clicar "💾 Salvar Lead" o cartão se perde. Precisa aceitar `cartao_json` e chamar `db.salvar_cartao`.
3. **`Dockerfile` não instala Tesseract** e `requirements.txt` não tem `pytesseract` (item 10).
4. **`templates/admin_leads.html`** não mostra as informações do cartão; `api_detalhe_lead` usa `buscar_lead` (sem a chave `cartao`).
5. **Testes** cobrem só `db` e parse de JSON — faltam validadores, fusão, imagem, endpoint /extract, persistência do cartão (item 22).

## 1. Fase 1 — Backend (fechar lacunas de persistência e API)

### 1.1 `app/main.py` — `salvar_lead_completo` (POST /leads)
Objetivo: o lead salvo deve conter **dados manuais + informações do cartão** (itens 1, 17, 18, 21).

- Aceitar novo campo multipart `cartao_json` (string JSON com a estrutura de `app.cartao.info`).
  - Parse defensivo: JSON inválido → `422 {"success": false, "error": "cartao_json inválido: ..."}` (mesmo estilo dos erros atuais).
- Aceitar campos de caminho `foto_frente_path` e `foto_verso_path` (strings) vindos do /extract, para **reaproveitar** os JPEGs já processados/salvos (evita duplicar arquivos).
- Regra de fotos:
  - Se veio `UploadFile` para o lado → salva novo (comportamento atual) e, se havia um path do extract para o mesmo lado, apaga o órfão (`_apagar_foto`).
  - Senão, se veio path → usa o path direto como `foto_<lado>_path`.
- Após salvar/atualizar o lead: se `cartao_json` presente, chamar `db.salvar_cartao(lead_id, cartao)`; antes de gravar, atualizar `cartao["imagens"]` com os paths finais usados no lead (frente/verso).
- Manter toda a lógica atual (lead_id para edição, campos manuais intactos, apagar fotos antigas substituídas).

### 1.2 `app/main.py` — `api_detalhe_lead` (GET /api/leads/{id})
- Trocar `db.buscar_lead(lead_id)` por `db.buscar_lead_completo(lead_id)` → resposta ganha chave `cartao` (additiva; nada quebra).

### 1.3 Compatibilidade
- Não alterar contrato de `/extract` (mantém `success`, `id`, `data` legado, `cartao`, `fotos`, `avisos`).
- Não alterar `/health`, `/leads` (GET), `/admin/*`, `/api/status`, `/api/leads`, `/fotos/*`.

## 2. Fase 2 — Frontend (`static/index.html`)

Reescrever a parte de interação com /extract e /leads. Manter todo o restante (estilo, captura, WhatsApp, últimos leads).

### 2.1 Fluxo novo (itens 8, 9, 19)
1. Vendedor fotografa frente (obrigatória) e verso (opcional) — como hoje.
2. `POST /extract` → sucesso: **NÃO** auto-preenche o formulário. Guarda `estado.cartao = r.dados.cartao` e `estado.caminhos = r.dados.fotos`.
3. Renderiza a seção 📇 **INFORMAÇÕES DO CARTÃO** com os dados encontrados.
4. Vendedor confere, clica em "[ Usar no Lead ]" quando quiser (item 5).
5. Vendedor preenche/confere os campos manuais e clica **💾 Salvar Lead** (item 9).

### 2.2 Seção 📇 INFORMAÇÕES DO CARTÃO (itens 3, 5, 19)
Nova `<section class="cartao">` (visualmente distinta da seção 👤 DADOS DO LEAD, cor/borda diferenciada — ex. `--ia: #7c3aed`):
- Cabeçalho: `📇 INFORMAÇÕES DO CARTÃO` + badge `🤖 Extraído automaticamente da foto`.
- Blocos exibidos quando houver valor (usa a estrutura `cartao` do backend):
  - Empresa (nome, nome fantasia, ramo/segmento)
  - Pessoa (nome, cargo)
  - Telefones: **todos** (lista — itens 12), cada um com tipo (whatsapp/celular/fixo)
  - E-mails (todos), Sites (todos)
  - Redes sociais (cada uma com a rede identificada)
  - Endereço: logradouro, número, complemento, bairro, cidade, UF, CEP
  - CNPJ
  - Outras informações detectadas (item 14)
- Cada item com botão "[ Usar no Lead ]" — gerado a partir de `cartao.sugestoes` (o backend já monta os pares campo→valor).
  - Comportamento do botão: copia o valor para o campo do formulário do lead **somente se o campo estiver vazio**; se já houver valor manual, **não sobrescreve** — mostra aviso "Campo já preenchido — apague o valor antes de copiar" (itens 4, 22: "tentativa de substituir campo já preenchido").
  - Mapeamento campo→input: `nome_empresa`, `nome_contato`, `cargo` (select — se não houver opção, usa "Outro"? cargo é select fixo: se o valor não casar, não copia e avisa), `whatsapp`, `telefone`, `email`, `site`, `redes_sociais`, `ramo_atividade` (select — casa opção, senão "Outro"+texto), `endereco` (texto composto), `cidade` → concatena em `endereco` (não existe input cidade, como hoje).
  - A informação **continua na seção do cartão** mesmo depois de copiada (item 6).
- "[ Ver texto original ]" (item 15): `<details>` com `<pre>` exibindo `cartao.ocr.frente` e `cartao.ocr.verso` (e aviso se OCR indisponível).
- Avisos (`cartao.avisos`) exibidos quando existirem (ex.: "IA de visão não respondeu...").

### 2.3 Persistência (item 17/18)
- `persistirLead()` passa a enviar também:
  - `cartao_json` = `JSON.stringify(estado.cartao)` (se houver)
  - `foto_frente_path`/`foto_verso_path` = `estado.caminhos` (quando existirem)
  - `foto_frente`/`foto_verso` (UploadFile) **somente** se o vendedor re-selecionou foto depois do extract.
- Mensagem de sucesso: "Lead #X salvo" — sem mencionar "salvo na extração".
- Manter `estado.leadId` nulo após extract (a menos que o backend devolva id — hoje só devolve com `salvar=1`, que a UI não usa).

### 2.4 WhatsApp
- Manter como está (usa campos manuais). Opcional futuro: incluir dados do cartão; não faz parte do escopo mínimo.

## 3. Fase 3 — Container e dependências (item 10)

### 3.1 `Dockerfile`
- Adicionar ao `apt-get install`: `tesseract-ocr tesseract-ocr-por` (Debian bookworm). Manter imagem slim e instalação mínima.

### 3.2 `app/requirements.txt`
- Adicionar `pytesseract>=0.3.10` (Pillow já presente).
- NÃO adicionar OpenCV/pytorch/transformers (item 23 — Pillow é suficiente; o `imagem.py` já usa só Pillow).

### 3.3 `install.sh`
- Verificar se algo precisa mudar (provisiona host, não o container — provavelmente nada). Rodar `grep` e ajustar se necessário. Documentar no README que o OCR roda dentro do container.

## 4. Fase 4 — Painel admin (item 24)

### 4.1 `templates/admin_leads.html`
- No modal de detalhe, após os campos do lead, adicionar bloco "📇 Informações do cartão" quando `l.cartao` existir: empresa, pessoa, telefones (todos), e-mails, sites, redes, endereço, outras informações e "[ Ver texto original ]" (OCR).
- Depende da mudança 1.2 (`buscar_lead_completo`).

### 4.2 `templates/admin_status.html`
- Sem mudanças obrigatórias. Opcional: linha "Tesseract: disponível/ausente" (via novo campo em `/api/status` — pequeno, opcional).

## 5. Fase 5 — Testes (item 22)

Novos arquivos em `tests/` (unittest, padrão dos existentes):

### 5.1 `tests/test_validadores.py`
- Telefone: válido com DDD (10/11), DDD inválido, dígitos repetidos (lixo), sem DDD → parcial, celular sem 9 → descartado, DDI 55, formato e164, múltiplos telefones no mesmo texto, tipo por contexto (whatsapp/celular/fixo).
- CEP (válido, inválido, repetido), e-mail (válido/inválido, sem domínio), URL (normalização, redes sociais vs site, `@usuario`), cidade/UF ("Ibitinga - SP"), logradouro + número + complemento, CNPJ.
- `suportado_pelo_ocr` / `texto_suportado_pelo_ocr`.

### 5.2 `tests/test_cartao.py`
- `fundir`: OCR + VLM → múltiplos telefones **preservados** (item 12); número do VLM que NÃO aparece no OCR é descartado (item 13); `outras_informacoes` guarda linhas sobrando (item 14); dados manuais não são tocados (o `info` é só do cartão).
- `montar_sugestoes`: pares campo→valor corretos.
- `para_campos_legado`: formato antigo preservado.

### 5.3 `tests/test_imagem.py`
- `abrir` corrige EXIF (imagem de teste com orientação 6 gerada por Pillow).
- `escalar` respeita teto 1024/1800 e piso 1100; `preparar` devolve `vlm_jpeg` ≤ 1024px e variantes de OCR; imagem inválida → ValueError.

### 5.4 `tests/test_db_cartao.py`
- `salvar_cartao`/`buscar_cartao`: cria, atualiza (1 por lead), preserva `ocr_texto`; `buscar_lead_completo` retorna lead + cartao; `leads_com_cartao`; **campos manuais do lead não são alterados** por `salvar_cartao` (item 4/21).

### 5.5 `tests/test_main_extract.py` (TestClient do FastAPI, mock de `cartao_mod.analisar`)
- `/extract` sem `salvar` → `success`, `id=None`, `cartao` presente, lead **não** criado (item 9).
- `/extract` com `salvar=1` → lead + cartao persistidos.
- imagem inválida → 422; imagem grande → 413; versão com OCR falho.
- `POST /leads` com `cartao_json` → cartao persistido; sem `cartao_json` → lead salvo sem cartao (compatibilidade).
- `POST /leads` com campo manual preenchido → permanece intacto após salvar cartao (item 21).
- `GET /api/leads/{id}` → resposta contém `cartao`.

### 5.6 Execução
- Rodar toda a suíte: `.venv/Scripts/python.exe -m unittest discover -s tests -q` (projeto usa unittest; sem pytest no venv).
- Teste manual com o cartão real (item 20/21) — frente, frente+verso, cartão rotacionado, baixa luz, dados manuais antes/depois da IA.

## 6. Fase 6 — Entrega (item 26)

1. Listar arquivos modificados.
2. Listar migrations (nenhuma nova coluna em `leads`; tabela `lead_cartao` já existe via `init_db`; conferir bancos antigos com `_migrar_colunas`).
3. Explicar alterações (este plano).
4. Executar testes (5.x).
5. `docker build` (verificar Tesseract instalado: `docker run --rm <imagem> tesseract --version` e `--list-langs` contendo `por`).
6. Subir container (`docker compose up -d --build`).
7. `curl /health`.
8. `curl -F image=@frente.jpg /extract` (sem `salvar` → id null, cartao completo).
9. `curl -F image=@frente.jpg -F verso=@verso.jpg /extract` (1 cartão só, telefones somados).
10. Criar lead via POST /leads com `cartao_json` → conferir `lead_cartao` no SQLite.
11. Editar lead (lead_id) → cartao atualizado, campos manuais preservados.
12. Conferir que dados manuais permanecem intactos e cartão permanece preservado.
13. Informar consumo de memória (ex.: `docker stats` durante um /extract; esperado < ~600 MB).

## 7. Riscos / decisões

- **Auto-preenchimento vs. V2**: a UI atual preenche o formulário com o cartão. O V2 proíbe. Decisão: **remover** o auto-preenchimento (itens 4, 21 são explícitos). O `data` legado do /extract continua na resposta por compatibilidade de API, mas a UI não usa para preencher.
- **Fotos**: /extract continua salvando os JPEGs processados (resposta `fotos`); o /leads reaproveita os paths e só re-salva quando o vendedor re-seleciona a foto. Órfãos de extract abandonado são tolerados (já ocorrem hoje).
- **Memória**: nada de OpenCV/numpy; processamento frente→verso sequencial já implementado; Tesseract roda no mesmo processo sem modelos grandes.
