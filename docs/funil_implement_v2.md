# Plano de implementação V2 — Funil de Vendas completo (funildevendas.md)

Base: `funildevendas.md` **completo** (85 itens) + 1ª rodada já entregue
(`funil_implement.md`, **119 testes OK**) + **leitura do código atual nesta
rodada** — cada lacuna abaixo foi conferida contra `app/db.py`,
`app/funil.py`, `app/main.py` e `templates/funil.html`.

## 0. Estado atual — VERIFICADO no código

| Camada | O que existe hoje | Onde |
|---|---|---|
| Constantes | 6 estágios + rótulos + `RESPONSAVEIS` (3 SDR) + `DIAS_ESTAGNADO=3` | `app/funil.py` (55 linhas) |
| Colunas de funil | `estagio`, `data_estagio_atual`, `responsavel_atual`, `ligacao_*` (flat), `motivo_perda` — DEFAULT, FORA de `CAMPOS` | `app/db.py`: `FUNIL_COLUNAS` + `_migrar_funil` (ALTER TABLE) |
| Histórico de estágios | tabela `historico_estagios` + índice; escrita em `mudar_estagio` | `app/db.py`: `_SCHEMA_FUNIL` |
| Regras no backend | qualificado exige ligação+virou_lead; perdido exige motivo; idempotente | `app/db.py`: `mudar_estagio` |
| Ligações | `registrar_ligacao` (feita, virou_lead, obs, data, responsável) | `app/db.py` |
| API | `GET /funil`, `GET /api/funil`, `GET /api/funil/{id}`, `GET /api/funil/metricas`, `POST .../estagio`, `POST .../ligacao` — mesma sessão do login | `app/main.py` |
| Kanban | card com foto, empresa, contato, WhatsApp, badge ligação, responsável, tempo, estagnado; DnD desktop + botões; vazio amigável | `templates/funil.html` |
| Detalhe | modal único: campos, 📇 cartão, registrar ligação, mover estágio (**motivo por `prompt()`**), timeline só de estágios | `templates/funil.html` |
| Filtros | responsável, estágio, período, busca (empresa/contato/whatsapp) | `listar_funil` + `funil.html` |
| Métricas | total, por estágio, conversão, tempo médio **por estágio** (genérico) | `metricas_funil` |
| Testes | **119** (test_db_funil 15, test_main_funil 10, demais regressão) | `tests/` |

## 1. Lacunas mapeadas (spec completa vs atual)

| # | Itens da spec | Lacuna (confirmada no código) |
|---|---|---|
| L1 | 18, 47, 48 | **`origem`** (`cartao`/`manual`) — coluna não existe; `salvar_lead` não recebe origem; `/extract salvar=1` grava sem origem |
| L2 | 22, 26, 59 | **`data_ultima_interacao`** — coluna não existe; nenhuma função atualiza |
| L3 | 21, 69 | **Próxima ação** — `proxima_acao`, `data_proxima_acao`, `proxima_acao_observacao` não existem; sem endpoint |
| L4 | 23–25, 71 | **`lead_atividades`** (timeline comercial geral) — tabela não existe; hoje só `historico_estagios` |
| L5 | 25 | **[+ Registrar interação]** — não existe (nem endpoint nem UI) |
| L6 | 14, 68 | **Edição dos campos manuais no detalhe** — `POST /leads` com `lead_id` já atualiza (B7 reusa), mas não há botão ✏ |
| L7 | 45, 68 | **Ações rápidas no detalhe** — não existem (📞 tel:, 📲 wa.me) |
| L8 | 50, 65 | **[+ Novo Lead]** manual — não existe na tela do funil |
| L9 | 31–34 | Filtros novos — `listar_funil` não tem `origem`, `sem_contato`, `atrasados`, `retorno_hoje`; busca não cobre telefone/e-mail |
| L10 | 20, 28 | **Modal de Perdido** com select de motivo — hoje é `prompt()` (`moverEstagio`) |
| L11 | 29, 30 | Reabertura — a API permite, MAS `mudar_estagio` **sobrescreve `motivo_perda` com ''** ao sair de perdido (motivo original se perde) |
| L12 | 27 | Fechado com observação + atividade "✅ Lead fechado" — não há atividade |
| L13 | 37 | Métricas específicas — só `tempo_medio_dias` genérico por estágio |
| L14 | 39 | **`PRAGMA foreign_keys=ON`** — `_conexao()` não ativa |
| L15 | 9, 46 | Card — falta **segmento** (`ramo_atividade`), indicador **📇 cartão**, **🔔 próxima ação + data** (destaque atrasada) |
| L16 | 13, 43 | Detalhe — modal único de leitura; faltam os 3 grupos (👤 / 📇 / 📊) e o ACOMPANHAMENTO completo |

## 2. Fases de implementação

### FASE A — Banco (migração V2) — itens 18, 21, 22, 39, 61, 62

- **A1** — Novas colunas em `leads` (adicionar a `FUNIL_COLUNAS` de `app/db.py` → migração via ALTER TABLE idempotente já existente, sem DROP):
  - `origem TEXT NOT NULL DEFAULT 'manual'`
  - `data_ultima_interacao TEXT NOT NULL DEFAULT ''`
  - `proxima_acao TEXT NOT NULL DEFAULT ''`
  - `data_proxima_acao TEXT NOT NULL DEFAULT ''`
  - `proxima_acao_observacao TEXT NOT NULL DEFAULT ''`
- **A2** — Tabela nova `lead_atividades` (itens 23/24/39) em `init_db`:
```sql
CREATE TABLE IF NOT EXISTS lead_atividades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL,            -- estagio|ligacao|whatsapp|email|proposta|observacao|proxima_acao|cartao|outro
  descricao TEXT NOT NULL DEFAULT '',
  data_hora TEXT NOT NULL,
  responsavel TEXT NOT NULL DEFAULT '',
  estagio_anterior TEXT DEFAULT '',
  estagio_novo TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_atividades_lead ON lead_atividades(lead_id);
```
- **A3** — `PRAGMA foreign_keys=ON` no início de `_conexao()` (item 39).
- **A4** — `app/funil.py`: constantes `TIPOS_ATIVIDADE` (item 24) e `MOTIVOS_PERDA` (item 20: Sem interesse, Já possui solução, Preço, Sem orçamento, Sem necessidade, Concorrente, Contato inválido, Outro).
- **A5** — Migração de dados (idempotente, em `_migrar_funil`): leads que já têm `lead_cartao` ganham `origem='cartao'`; os demais ficam `manual` (item 61 — sem exigir ação do usuário; nenhum dado apagado).

### FASE B — Backend (regras + atividades + próxima ação) — itens 21–27, 47, 48, 56–60

- **B1** — Gravar `origem`:
  - `/extract` com `salvar=1` → `db.salvar_lead(lead, origem="cartao")`;
  - `POST /leads` aceita campo opcional `origem` (frontend de captura envia `cartao` quando há cartão analisado; default `manual`);
  - **item 47**: edição/atualização NÃO muda `origem` (origem ≠ tem cartão; `atualizar_lead` continua só em `CAMPOS`).
- **B2** — `registrar_atividade(lead_id, tipo, descricao, responsavel, estagio_anterior="", estagio_novo="")`: INSERT em `lead_atividades` + UPDATE `data_ultima_interacao` na **mesma transação** (item 22/59).
- **B3** — `mudar_estagio` estendido (transação única): UPDATE lead + INSERT `historico_estagios` + `registrar_atividade(tipo='estagio', anterior/novo, observação)` + `data_ultima_interacao`; ao entrar em `fechado` → atividade "✅ Lead fechado" (item 27); ao entrar em `perdido` → atividade com motivo (item 28). **Correção de reabertura (itens 29/30): só gravar `motivo_perda` quando ENTRAR em perdido — ao sair, preservar o motivo no lead** (hoje o UPDATE zera sempre; o histórico/atividades mantêm o registro antigo).
- **B4** — `registrar_ligacao` estendido: + atividade tipo=`ligacao` + `data_ultima_interacao` (item 19).
- **B5** — `salvar_proxima_acao(lead_id, acao, data, observacao, responsavel)`: atualiza as 3 colunas + atividade tipo=`proxima_acao` + `data_ultima_interacao` (item 21).
- **B6** — `registrar_interacao(lead_id, tipo, descricao, responsavel)` → reusa B2 (tipos whatsapp/email/proposta/observacao/outro — item 25).
- **B7** — Edição manual: reutilizar `POST /leads` com `lead_id` (já atualiza sem duplicar) — expor no frontend; confirmação ao substituir dados manuais (item 53).
- **B8** — `listar_funil` estendido: filtros `origem`, `sem_contato` (`ligacao_feita=0`), `atrasados` (`data_proxima_acao != '' AND < agora AND estagio NOT IN (fechado, perdido)`), `retorno_hoje` (`date(data_proxima_acao) = hoje`), `proxima_acao`; busca também por `telefone` e `email`; resposta inclui `origem`, `proxima_acao`, `data_proxima_acao`, `proxima_acao_observacao`, `tem_cartao` (itens 31–34).
- **B9** — `metricas_funil` estendido: + `tempo_medio_qualificacao_dias` (novo→qualificado), `tempo_medio_negociacao_dias` (permanência em negociação), `tempo_medio_fechamento_dias` (novo→fechado) — calculados a partir de `historico_estagios` (item 37; mostrar "—" sem dados).
- **B10** — Endpoints novos (mesma sessão): `POST /api/funil/{id}/atividade` e `POST /api/funil/{id}/proxima-acao`; manter `/estagio` e `/ligacao` atuais (compatíveis com a spec 56).

### FASE C — Frontend (`templates/funil.html`) — itens 9, 13, 16, 20, 25, 28, 43, 45, 50, 65–71

- **C1** — Card completo e compacto (item 9): + **segmento** (`ramo_atividade`), **📇** se tem cartão, **🔔 próxima ação + data** (vermelho se atrasada) — mantendo o visual atual (foto miniatura, contato, WhatsApp, responsável, ⏱ tempo com destaque >3d).
- **C2** — Filtros (itens 31–34, 67): checkboxes **☑ Sem contato / ☑ Atrasados / ☑ Retorno hoje**, select de **origem**, busca por empresa/contato/whatsapp/telefone/e-mail.
- **C3** — Cabeçalho (item 65): **[+ Novo Lead]** com modal de formulário mínimo → `POST /leads` manual (`origem=manual`), lead entra em Novo.
- **C4** — Detalhe em 3 grupos (item 13):
  - **👤 DADOS DO LEAD**: todos os campos + botão **✏ Editar** (form inline → `POST /leads` com `lead_id`; confirmação ao substituir — item 53).
  - **📇 INFORMAÇÕES DO CARTÃO**: mantém o bloco atual separado (frente/verso/OCR — itens 15, 49).
  - **📊 ACOMPANHAMENTO**: estágio, responsável, última interação, próxima ação (form), ligações (última + virou lead + obs + [Registrar nova ligação]), **[+ Registrar interação]** (tipo + descrição), **timeline geral** de `lead_atividades` (ícones por tipo, ordem decrescente — item 71) — substitui a timeline só de estágios.
- **C5** — Ações rápidas no topo do detalhe (itens 45, 68): **📞 Ligar** (`tel:` do telefone/whatsapp), **📲 WhatsApp** (`wa.me` com texto montado — fluxo de captura permanece intacto, item 44), **✏ Editar**, **➡ Alterar estágio**.
- **C6** — Modal de Perdido (itens 20, 28): select `MOTIVOS_PERDA` + "Outro" com campo livre + observação — usado tanto no DnD quanto no botão; **substitui o `prompt()` atual**; confirmação explícita.
- **C7** — Reabertura (itens 29, 30): mover de Perdido/Fechado de volta é permitido; timeline preserva e mostra a reabertura; motivo antigo permanece visível.

### FASE D — Testes (itens 76–80)

- **D1** `tests/test_db_funil_v2.py`: origem (manual/cartao; cartão depois não muda origem), próxima ação (salvar + filtros atrasados/retorno_hoje), atividades (tipos + `data_ultima_interacao` atualizada em ligação/estágio/interação), **reabertura perdido→qualificado e fechado→negociacao** (motivo/histórico preservados), migração de lead antigo com cartão → origem cartao, `foreign_keys` ativa, tempos médios específicos.
- **D2** `tests/test_main_funil_v2.py`: endpoints `/atividade` e `/proxima-acao`; filtros novos na lista; edição via `POST /leads` com `lead_id` preserva funil; regras (78) reafirmadas.
- **D3** — Regressão: suíte completa (119 atuais + novos).

### FASE E — Entrega / validação

1. Listar arquivos; 2. migrations (colunas novas + `lead_atividades`, sem DROP); 3. rodar suíte; 4. smoke test end-to-end (captura cartão → kanban → ligação → qualificado → próxima ação → negociação → fechado; perdido com motivo; reabertura); 5. docker build/deploy na VPS + teste com o cartão real (item 80); 6. memória inalterada (SQLite + 1 página — item 64).

## 3. Ordem de execução sugerida (rodadas)

| Rodada | Escopo | Critério de saída |
|---|---|---|
| R1 | Fase A + B + D1/D2 (backend completo) | Suíte verde (119 + novos) |
| R2 | Fase C (frontend) | Kanban/detalhe/filtros novos funcionando |
| R3 | Fase D completo + E (regressão + smoke + deploy) | Validação end-to-end na VPS |

## 4. Riscos / decisões

- **`historico_estagios` + `lead_atividades`**: mantém a tabela de estágios (métricas e regras já testadas) e adiciona a timeline geral. Escrita dupla na **mesma transação** — consistente (item 59).
- **Origem**: `manual` é o DEFAULT (não quebra `POST /leads` atual); `cartao` gravado pelo `/extract` e pela captura quando há cartão. Origem ≠ tem cartão (item 18).
- **Reabertura**: correção no UPDATE (preservar `motivo_perda` ao sair de perdido) + teste garantindo que motivo/histórico persistem (itens 29/30).
- **WhatsApp no detalhe**: `wa.me` com texto montado (mesmo mecanismo do fallback da captura); fluxo com foto + Web Share permanece no app de captura, intacto (itens 1, 44).
- **Sem admin**: `/funil` é autônomo (mesma sessão do login); nada técnico (Ollama/Docker/RAM) na tela comercial (item 83).
- **Sem framework novo**: Python/FastAPI/SQLite/JS puro (item 63); memória estável (item 64).

---

## 5. Status da R1 — concluída ✅

Implementado nesta rodada (Fase A + B + D1/D2), tudo verde na suíte:

| Item | Entrega |
|---|---|
| A1 | Colunas novas em `leads`: `origem`, `data_ultima_interacao`, `proxima_acao`, `data_proxima_acao`, `proxima_acao_observacao` (ALTER TABLE idempotente) |
| A2 | Tabela `lead_atividades` + índice (timeline comercial geral) |
| A3 | `PRAGMA foreign_keys=ON` em `_conexao()` |
| A4 | `TIPOS_ATIVIDADE` e `MOTIVOS_PERDA` em `app/funil.py` |
| A5 | Backfill `origem='cartao'` para leads antigos com cartão (`_migrar_origem`) |
| B1 | `salvar_lead(origem=...)`; `/extract salvar=1` → cartao; `POST /leads` auto-deriva (cartao_json → cartao) e nunca muda origem na edição |
| B2 | `registrar_atividade` (INSERT + `data_ultima_interacao`, mesma transação) |
| B3 | `mudar_estagio`: atividade de estágio (✅ fechado / ❌ perdido com motivo) + `data_ultima_interacao` + **preserva `motivo_perda` na reabertura** |
| B4 | `registrar_ligacao`: atividade tipo ligacao + `data_ultima_interacao` |
| B5 | `salvar_proxima_acao` (3 colunas + atividade + última interação) |
| B6 | `registrar_interacao` (tipos padronizados, validação) |
| B8 | `listar_funil`: filtros `origem`, `sem_contato`, `atrasados`, `retorno_hoje`; busca por telefone/e-mail; campos `tem_cartao`/próxima ação |
| B9 | `metricas_funil`: `tempo_medio_qualificacao_dias`, `tempo_medio_negociacao_dias`, `tempo_medio_fechamento_dias` (None → mostra "—") |
| B10 | `POST /api/funil/{id}/atividade` e `POST /api/funil/{id}/proxima-acao` (mesma sessão; resposta = detalhe com timeline) |
| D1/D2 | `tests/test_db_funil_v2.py` (17) + `tests/test_main_funil_v2.py` (12) |
| Regressão | **156 testes OK** (119 antigos + 37 novos) |

Arquivos tocados: `app/db.py`, `app/funil.py`, `app/main.py`, `tests/test_db_funil_v2.py`, `tests/test_main_funil_v2.py`, `run_suite_local.py` (runner dev p/ sandbox), `.gitignore`.

**Próxima rodada (R2 — Fase C + UX_FUNIL.md)**: ver seção 6 abaixo.
---

## 6. R2 — Frontend (Fase C + UX_FUNIL.md) — PRÓXIMA sprint

Análise: o documento `docs/UX_FUNIL.md` **cabe nesta sprint** — é todo
trabalho de frontend em `templates/funil.html` (mais CSS e texto). O
backend da R1 já entrega tudo que o UX doc usa: `origem`/`tem_cartao`,
`proxima_acao`/`data_proxima_acao` (filtros atrasados/retorno_hoje/sem_
contato), `data_ultima_interacao`, `atividades`/timeline, `MOTIVOS_PERDA`,
preserva motivo na reabertura e métricas específicas. Única dependência
nova: expor `MOTIVOS_PERDA` e `TIPOS_ATIVIDADE` no contexto do template
(`app/main.py` → `funil_page`).

### Escopo R2 (mapeado do UX + Fase C)

| # | Tarefa (UX_FUNIL.md) | Fase C / backend |
|---|---|---|
| R2.1 | **Kanban**: desktop colunas com scroll horizontal; **mobile = lista vertical + seletor de estágio no topo** (substitui scroll de colunas); divisórias finas entre estágios, sem sombra/borda arredondada de SaaS | C1/C7 + direção visual |
| R2.2 | **Card**: foto miniatura só se `origem=cartao`; segmento como texto; tempo no estágio neutro até 3d e destaque (cor+peso) depois; `🔔` só com próxima ação e borda sutil de atenção se vencida; card inteiro clicável | C1 + L15 |
| R2.3 | **Presets de papel**: `[Meus leads ▾]` = responsável selecionado no cabeçalho; atalho BDR (Novo + Sem contato) e SDR (Qualificado + Atrasados); filtros `🔴 Atrasados`, `Retorno hoje`, `Sem contato`, `Origem` (rótulo "de onde veio") | C2 + L9 |
| R2.4 | **Detalhe em 3 blocos** (ordem do UX): ① Ações rápidas (📞 Ligar `tel:`, 📲 WhatsApp `wa.me`, ➡ Mudar estágio, ✏ Editar) · ② Acompanhamento (estágio/responsável, última interação, próxima ação com empty-state convite, ligação, [+ Registrar interação] inline, timeline com ícones por tipo) · ③ Dados do lead com 📇 colapsado | C4/C5 + L16 |
| R2.5 | **Modal de Perdido**: select `MOTIVOS_PERDA` + "Outro" livre + observação (fim do `prompt()`); **Fechado pede observação** (não motivo) | C6 + L10 |
| R2.6 | **[+ Novo Lead]** manual (modal mínimo → `POST /leads`, origem manual) | C3 + L8 |
| R2.7 | **Vazio e erro**: kanban vazio = convite com [+ Novo Lead]; coluna vazia = "Nenhum lead aqui no momento"; falha de salvar = mensagem do que não foi salvo + "Tente novamente"; sem erro técnico cru | UX "Vazio e erro" |
| R2.8 | **Linguagem**: botões = ação ("Registrar ligação", "Mudar estágio"); sem jargão ("de onde veio o lead", nunca "origem") | UX "Linguagem" |
| R2.9 | **Visual**: paleta neutra (cinzas quentes) + 1 cor de atenção exclusiva (atrasado/estagnado); tipografia única sem serifa; densidade (mais cards por scroll) | UX "Direção visual" |
| R2.10 | **Testes**: novos endpoints já cobertos na R1 (D2); nesta sprint smoke manual + revisão desktop/mobile; regressão 156 verdes | Fase E parcial |

### Critério de saída
- `/funil` em desktop e mobile com os fluxos BDR (Novo+Sem contato → ligação
  → qualificado) e SDR (Qualificado+Atrasados → fechado/perdido) funcionando
  ponta a ponta, sem regressão (156 testes continuam verdes).

