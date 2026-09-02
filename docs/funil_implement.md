# Plano de implementação — Módulo Funil de Vendas (funildevendas.md)

Base: `funildevendas.md` (especificação) + leitura do projeto atual (LeadScan V2 já implantado: captura por foto → OCR/IA → WhatsApp, 94 testes).

## 0. Estado atual (levantamento)

| Camada | Hoje | Impacto do funil |
|---|---|---|
| DB | `leads` (CAMPOS + fotos) + `lead_cartao` (1:1, dados_json) — migração por `_migrar_colunas` | + colunas de funil em `leads` + tabela `historico_estagios` |
| Auth | Senha única compartilhada (`auth.py`, cookie assinado) — **não existe usuário/SDR** | Reusar mesma sessão; responsável vira campo do lead (lista fixa no código) |
| Rotas | `/extract`, `/leads` (GET/POST), `/admin/*`, `/api/leads*`, `/fotos/*` | + `/funil` e `/api/funil*` — **nada dos atuais muda** |
| Frontend | `static/index.html` (captura) + `templates/admin_*` | + `templates/funil.html` (kanban do time) |
| Testes | 94 unittest | + funil (db + API) — regressão obrigatória |

## 1. Modelo de dados (migração sem apagar dados)

### 1.1 Colunas novas em `leads` — **FORA de `CAMPOS`** (para o POST /leads da captura não tocar nelas; entram com DEFAULT)

| Coluna | Tipo | Default | Observação |
|---|---|---|---|
| `estagio` | TEXT | `'novo'` | enum: novo, ligacao_feita, qualificado, negociacao, fechado, perdido |
| `data_estagio_atual` | TEXT | '' | ISO — usada no card (tempo no estágio) e métricas |
| `responsavel_atual` | TEXT | '' | SDR designado (lista fixa em código) |
| `ligacao_feita` | INTEGER | 0 | 0/1 |
| `data_ligacao` | TEXT | '' | ISO |
| `ligacao_virou_lead` | INTEGER | 0 | 0/1 |
| `ligacao_observacao` | TEXT | '' | observação livre da ligação |
| `motivo_perda` | TEXT | '' | obrigatório se `estagio = perdido` |

- Estender `_migrar_colunas` (ou nova `_migrar_funil`) com `ALTER TABLE leads ADD COLUMN ... NOT NULL DEFAULT ...` — bancos antigos ganham as colunas **sem reescrever nada**.

### 1.2 Tabela nova `historico_estagios` (auditoria simples + métricas de tempo)

```sql
CREATE TABLE IF NOT EXISTS historico_estagios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL,
  estagio TEXT NOT NULL,
  data TEXT NOT NULL,              -- ISO
  usuario_responsavel TEXT DEFAULT '',
  observacao TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_hist_lead ON historico_estagios(lead_id);
```

### 1.3 Constantes em código (não em tela de admin — como pede a spec)

- `app/funil.py` (novo módulo): `ESTAGIOS` (lista ordenada com rótulos pt-BR) e `RESPONSAVEIS` (lista fixa de SDR/vendedores, configurável no código).

## 2. Backend — API do funil (2.1 `db.py` / 2.2 `main.py`)

Nenhuma mudança em `/extract`, `/leads` (GET/POST), `/admin/*`, `/api/leads*` — o fluxo de captura fica **intocado**.

### 2.1 `db.py`
- `mudar_estagio(lead_id, estagio, usuario, observacao)`:
  - valida estágio no enum; **regras** (sec. 5 da spec): `qualificado` só com `ligacao_feita=1` e `ligacao_virou_lead=1`; `perdido` exige `motivo_perda`; toda mudança grava em `historico_estagios` (estagio, data, usuario, observacao) e atualiza `estagio` + `data_estagio_atual`.
- `registrar_ligacao(lead_id, feita, virou_lead, observacao, usuario)`: grava `ligacao_*` + `data_ligacao`.
- `set_motivo_perda(lead_id, motivo)` (usado junto com mudar_estagio p/ perdido).
- `listar_funil(busca, responsavel, estagio, de, ate, limite)`: join com `lead_cartao` → cada lead sai com `cartao` (p/ miniatura + dados no detalhe), `estagio`, `responsavel_atual`, tempos.
- `metricas_funil(de, ate)`: contagem por estágio; taxa de conversão (fechado/total no período); tempo médio por estágio (via `historico_estagios`: duração entre a entrada no estágio e a saída; estágio atual usa `data_estagio_atual` → agora).

### 2.2 `main.py` — rotas (mesma sessão/cookie do login atual)
- `GET /funil` → `templates/funil.html` (dependência `exige_admin` — mesma sessão, mas a tela é operacional do time, não admin genérico).
- `GET /api/funil` → lista com filtros `responsavel`, `estagio`, `de`, `ate`, `busca`.
- `POST /api/funil/{id}/estagio` → body `{estagio, motivo_perda?, observacao?}` — 422 com mensagem clara quando regra quebra (mesmo padrão dos erros atuais).
- `POST /api/funil/{id}/ligacao` → body `{feita, virou_lead, observacao}`.
- `GET /api/funil/metricas` → contadores + conversão + tempo médio.
- Autenticação: `exige_admin_api` para as APIs; `exige_admin` para a página.

## 3. Frontend — tela do time (`templates/funil.html`, mobile-first)

- **Kanban** por estágio (colunas = `ESTAGIOS`); no mobile vira **abas/scroll horizontal** por estágio (drag-and-drop não é prático em celular).
- **Card do lead**: empresa/nome, miniatura da foto do cartão, tempo no estágio (**destaque visual > 3 dias**, ex. badge âmbar), responsável, badge de ligação feita.
- **Drag-and-drop no desktop** (HTML5 DnD leve, sem lib externa) + **botões "mover"** no card/modal para mobile (a spec pede manter opção via botão).
- **Modal de detalhe** (clique no card):
  - Dados completos: formulário manual + 📇 informações do cartão (reusa o mesmo render do admin) + fotos.
  - **"Registrar ligação"**: checkbox "ligação feita", checkbox "virou lead", observação → `POST /api/funil/{id}/ligacao`.
  - **Mover estágio**: select/botões com validação das regras (qualificado exige ligação; perdido pede motivo).
  - **Linha do tempo** do `historico_estagios` (estágio, data, responsável, observação).
- **Barra de métricas no topo**: contador por estágio, taxa de conversão, tempo médio por estágio.
- **Filtros**: responsável, estágio, período de captura, busca.
- Responsável: o SDR **escolhe o nome dele** (select com `RESPONSAVEIS`) ao registrar ligação/mover — sem login por usuário (decisão, ver sec. 6).

## 4. Testes (unittest — padrão dos existentes)

### 4.1 `tests/test_db_funil.py`
- Migração: banco novo e banco "antigo" (sem colunas) ganham `estagio='novo'` sem perder dados.
- `mudar_estagio`: novo→ligacao_feita ok; →qualificado **sem** ligação = erro; →qualificado com ligação feita+virou_lead ok; →perdido **sem** motivo = erro; →perdido com motivo ok; histórico gravado a cada mudança (auditoria com usuário/timestamp).
- `registrar_ligacao` grava dados; `metricas_funil` (contagens, conversão, tempo médio com dados conhecidos).

### 4.2 `tests/test_main_funil.py` (TestClient, mesmo padrão de test_main_extract)
- `GET /funil` sem sessão → redireciona/401; com sessão → 200 com a página.
- `POST /api/funil/{id}/estagio` feliz e com regra quebrada → 422 + mensagem.
- `POST /api/funil/{id}/ligacao`; `GET /api/funil` com filtros; `GET /api/funil/metricas`.
- Lead capturado via `/extract`+`/leads` **sem funil** entra como `novo` (compatibilidade — POST /leads atual não quebra).

### 4.3 Regressão
- Suíte inteira (`unittest discover -s tests -q`) — os 94 atuais + novos.

## 5. Entrega

1. Listar arquivos modificados/criados.
2. Migrations: colunas novas em `leads` (ALTER TABLE com DEFAULT) + tabela `historico_estagios` — sem apagar dados.
3. Explicar alterações (este plano).
4. Rodar suíte completa.
5. `docker compose up -d --build` na VPS; `curl /health`, `curl /funil` (login), fluxo manual:
   - capturar lead → aparece em **Novo** no kanban;
   - registrar ligação → marca no card;
   - mover até qualificado/negociação/fechado (e perdido com motivo);
   - conferir histórico e métricas.
6. Memória: impacto desprezível (SQLite + 1 página nova — nada de modelos).

## 6. Riscos / decisões

- **Usuário/SDR**: hoje o LeadScan tem **1 senha compartilhada** — não há login por pessoa. Decisão: manter a sessão única e o **responsável como campo escolhido pelo time** (lista `RESPONSAVEIS` fixa no código). Satisfaz "sem gestão de usuários/permissões avançada"; se no futuro houver login individual, `usuario_responsavel` já é gravado no histórico.
- **`estagio` fora de `CAMPOS`**: o POST /leads da captura continua salvando só os campos do formulário — o lead nasce `novo` por DEFAULT do banco, sem tocar no fluxo atual.
- **Histórico em tabela separada** (não JSON): permite auditoria simples e cálculo de tempo médio por estágio com SQL.
- **Kanban sem biblioteca**: HTML5 DnD (desktop) + botões (mobile) — mantém o app leve, sem etapa de build.
- **Rota `/funil`** (e não `/leads`, que já é JSON público da UI): evita conflito com o contrato existente.

## Status de implementação

- [x] **Fase 1 — Modelo de dados**: `app/funil.py` (ESTAGIOS/RESPONSAVEIS/regras) + `db.py` (FUNIL_COLUNAS com DEFAULT, tabela `historico_estagios`, `_migrar_funil`). Migração validada em banco novo e banco antigo (dados preservados, estagio='novo').
- [x] **Fase 2 — Backend/API**: `db.mudar_estagio` (regras: qualificado exige ligação+virou_lead; perdido exige motivo; histórico gravado), `registrar_ligacao`, `historico_do_lead`, `buscar_lead_funil`, `listar_funil` (filtros + tempo no estágio + estagnado), `metricas_funil`; rotas `GET /funil`, `GET /api/funil`, `GET /api/funil/{id}`, `POST /api/funil/{id}/estagio`, `POST /api/funil/{id}/ligacao`, `GET /api/funil/metricas` (mesma sessão do login).
- [x] **Fase 3 — Frontend**: `templates/funil.html` — kanban mobile-first (cards com miniatura da foto, tempo no estágio com destaque >3d, responsável, badge de ligação), drag-and-drop desktop + botões no modal, detalhe com cartão + ligação + mover estágio + timeline, métricas no topo, filtros (responsável/estágio/período/busca), "Atuando como" para a SDR. Links "📊 Funil" nos navs do admin.
- [x] **Fase 4 — Testes**: `tests/test_db_funil.py` + `tests/test_main_funil.py` (25 testes) — **119 testes no total, todos OK**.
- [x] **Fase 5 — Validação**: smoke test end-to-end (captura → Novo → ligação → qualificado → negociação → fechado; histórico; métricas). Pendente no ambiente: `docker build`/deploy na VPS e teste manual com o time.
