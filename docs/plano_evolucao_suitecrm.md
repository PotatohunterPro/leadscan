# Plano de evolução — incorporar conceitos do SuiteCRM no LeadScan

**Data:** 2026-09-02
**Base:** `docs/suitecrm-referencia.md` (estudo, sem código copiado) + decisões do
dono do produto. Cada item vira código no schema atual (Python/FastAPI/SQLite +
HTML/JS puro), escrito do zero — nada de AGPLv3 no produto.

---

## Contexto e decisões de produto

O LeadScan é **lead-único** (spec item 40): o lead é a entidade principal, sem
módulo Accounts/Contacts/Opportunities separado. Os itens pedidos do SuiteCRM
foram **adaptados a esse modelo**, não copiados como entidades próprias.

**Mudança de negócio (definida em 2026-09-02):**
- A raiz `https://hublead.pradodacostasolucoes.com.br` passa a abrir o **funil**
  (kanban) — redireciona para `/funil` e exige login.
- A captura de cartão na rua (tela "minha" do BDR) sai da raiz e vai para
  `https://hublead.pradodacostasolucoes.com.br/bdr`.
- `/bdr` **precisa do usuário que está lançando**: o BDR faz login (senha +
  nome) e a captura registra quem capturou o lead.

---

## Fase A — Melhorias no modelo atual (mesmo schema-base)

### A1. Detecção de duplicatas na criação
- [ ] `POST /leads` e `POST /funil`: antes de salvar, buscar por `whatsapp`/`email`/`nome_empresa+nome_contato` normalizados
- [ ] Resposta ganha `possiveis_duplicatas: [{id, nome_empresa, nome_contato, whatsapp}]`
- [ ] Frontend (captura + Novo Lead): "Já existe um lead parecido — continuar mesmo assim?"
- [ ] Testes db + API
- Nota: CNPJ vive no JSON do cartão (`lead_cartao.dados_json`), não em coluna — duplicata por CNPJ só depois de virar coluna.

### A2. Reagendamento de ligação com motivo + contador de tentativas
- [ ] `FUNIL_COLUNAS` += `ligacao_tentativas INTEGER NOT NULL DEFAULT 0`, `ligacao_ultimo_resultado TEXT NOT NULL DEFAULT ''` (migração idempotente)
- [ ] `RESULTADOS_LIGACAO` em `app/funil.py` (Não atendeu / Ocupado / Caixa postal / Recusou / Reagendado)
- [ ] `POST /ligacao` aceita `resultado` quando `feita=false`; incrementa tentativas
- [ ] Frontend: select de resultado + contador "3ª tentativa"; filtro "📞 Tentado sem sucesso"
- [ ] Testes db + API

### A3. Auditoria de campos editados
- [ ] Tabela `auditoria_campos (id, lead_id, campo, valor_anterior, valor_novo, data_hora, responsavel)` FK CASCADE
- [ ] Escrita em `atualizar_lead` e `POST /api/funil/{id}/dados` quando o valor muda
- [ ] UI: `<details>` "Auditoria" no detalhe do lead
- [ ] Testes db

### A4. Tarefas com 5 estados + prioridade + vencimento
- [ ] Decisão de produto: **manter próxima-ação única** (não quebrar V3/5.2) OU múltiplas tarefas
- [ ] (Se mínimo) tabela `lead_tarefas (id, lead_id, titulo, prioridade, status, data_vencimento, responsavel, criado_em)`
- [ ] Próxima-ação vira atalho "criar tarefa pendente"
- [ ] Lista de tarefas abertas no kanban/detalhe com prioridade
- [ ] Testes db + API

---

## Fase B — Documents / Notes por lead

### B1. Notas por lead (Notes)
- [ ] Decisão: timeline já registra observações — **avaliar redundância** antes de tabela nova
- [ ] (Se aprovado) `lead_notas (id, lead_id, texto, data_hora, responsavel)` + campo rápido no detalhe
- [ ] Testes db

### B2. Documentos (upload genérico por lead)
- [ ] Decisão: WhatsApp-first reduz o valor — **recomendado fora de escopo** salvo arquivar contratos/propostas
- [ ] (Se aprovado) `lead_documentos` + `data/documentos/` + upload/servir autenticado com checagem de propriedade
- [ ] Testes

---

## Fase C — Cases (suporte/pós-venda)
- [ ] `cases (id, lead_id, titulo, descricao, status, prioridade, responsavel, data_abertura, data_fechamento)` — amarrado a lead FECHADO (pós-venda)
- [ ] `tipo='case'` em `TIPOS_ATIVIDADE` (timeline do case reusa `lead_atividades`)
- [ ] Aba "🛟 Suporte" no detalhe quando `estagio=fechado` + listagem no admin
- [ ] Testes db + API

## Fase D — Projects / ProjectTask
- [ ] **Decisão:** NÃO criar entidade Project própria (ref-doc: não se aplica)
- [ ] Necessidade real = acompanhar implantação pós-venda: **checklist/template de tarefas dentro do case** de implantação
- [ ] Testes

## Fase E — Calendar / Calls / Meetings / Tasks (agenda + convidados)
- [ ] **Decisão:** NÃO portar calendário/convites/recorrência/reunião online (fora — ref-doc)
- [ ] Adaptação útil: **"Agenda de retornos"** por responsável — linha do tempo unificando tarefas abertas (A4) + ligações agendadas + `data_proxima_acao` + cases, com chips atrasados/hoje já existentes
- [ ] Testes

---

## Rotas e layout (mudança de negócio — já em andamento)

### Rotas
- [x] `/` (raiz) → redireciona para `/funil` (kanban, exige login)
- [x] `/funil` — mantém como está
- [x] `/bdr` — nova rota: tela de captura (static/index.html), exige login
- [x] Login de `/bdr` grava quem está capturando (responsável na criação)
- [x] Links internos (`/` → funil/captura) ajustados para `/bdr` (funil.html nav + empty state, admin_login "voltar")

### Layout
- [x] Identidade HUB já aplicada (design-tokens.css) — nada a refazer

---

## Critérios de aceite
- [x] `https://…` sem caminho abre o funil (pede login; logado → kanban) — raiz 303 → `/funil`; sem sessão desemboca no login
- [x] `https://…/bdr` abre a captura só logado; leads capturados ficam atribuídos ao usuário logado (smoke: SDR 1 → lead com `responsavel_atual='SDR 1'`)
- [x] Suíte completa verde (`run_suite_local.py` — 225 testes OK)

### Mudanças de código desta rodada (rotas/layout)
- `app/main.py`: `/` → `RedirectResponse('/funil')`; rota nova `GET /bdr` (FileResponse da captura, `Depends(exige_admin)`); `_criar_sessao` agora manda pro `/funil`; `POST /leads` atribui `registrar_responsavel` ao usuário logado (não-gestor) ao criar lead novo.
- `templates/funil.html`: link "Captura" → `/bdr` (nav + empty state).
- `templates/admin_login.html`: "voltar" → `/bdr`.
