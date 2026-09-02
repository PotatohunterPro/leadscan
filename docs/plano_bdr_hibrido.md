# Plano — /bdr híbrido (manual é o dono), imagens do cartão no lead e exclusão

**Data:** 2026-09-02
**Decisões confirmadas com o dono:**
- Na tela `/bdr`: **o formulário manual vem primeiro e é o que manda**; a seção do
  cartão vem **depois, como ADICIONAL** ("📇 Informações do cartão").
- **Cartão nunca sobrescreve manual** (campo manual preenchido fica intocado;
  o "[ Usar no lead ]" só preenche o que está VAZIO).
- A **imagem do cartão fica gravada no lead** (campo de imagens no registro).
- **Exclusão definitiva** de leads: apaga o lead, o JSON do cartão e as fotos do
  disco. **Gestor exclui qualquer lead; BDR/SDR só os próprios** (visibilidade 5.5).

---

## Estado atual (o que já existe e facilita)

- `POST /leads` (captura) já trata cartão e manual de forma separada:
  - campos manuais → tabela `leads` (`CAMPOS`);
  - cartão (JSON + OCR) → tabela `lead_cartao` (1:1, `salvar_cartao`);
  - **fotos** já ficam no lead: colunas `foto_frente_path` / `foto_verso_path`
    (e o JSON do cartão guarda `imagens.{frente,verso}` também).
- Regra "cartão nunca sobrescreve manual" já existe no frontend
  (`static/index.html` — botão "[ Usar no lead ]" só copia p/ campo vazio) e no
  backend (`salvar_cartao` não toca colunas de `leads`).
- `PRAGMA foreign_keys = ON` ativo → excluir o lead apaga em CASCADE:
  `historico_estagios`, `lead_atividades`, `lead_cartao`.
- Não existe NENHUMA rota/método de exclusão de lead hoje (falta tudo).

---

## O que precisa mudar

### 1. Tela `/bdr` híbrida — manual primeiro, cartão como adicional
- [x] **Reordenar a tela** (`static/index.html`, servida em `/bdr`):
  1. 👤 Dados do lead (formulário manual) — PRIMEIRO, em destaque;
  2. 📇 Foto do cartão — DEPOIS, como "2 · 📷 (opcional)".
- [x] Fotografar o cartão passou a ser um complemento: **100% off** — não há
  spinner, não há `/extract` na captura; o BDR salva e a leitura acontece no
  servidor em 2º plano (Opção B). As 📇 aparecem anexadas no funil quando prontas.
- [x] **Campo manual preenchido nunca é substituído** pela sugestão do cartão
  (removido o fluxo de "usar no lead"; o cartão vai para `lead_cartao` como
  camada separada — nada toca nas colunas manuais do lead).
- [x] Regra de segurança no BACKEND: `POST /leads` grava manual em `leads` e o
  cartão só em `lead_cartao` (`salvar_cartao` não toca colunas manuais) — e a
  análise off preserva o manual por construção.
- [x] Smoke manual: preencher nome/contato/whatsapp à mão + foto do cartão →
  o manual permanece e o cartão é anexado por leitura off (teste
  `TestOpcaoBLeituraOff`).

### 2. Imagens do cartão gravadas no lead (campo "imagens")
- [x] A foto enviada na captura é salva como `foto_frente_path`/`foto_verso_path`
  do lead (colunas já existentes) — a Opção B anexa a foto junto no salvar.
- [x] O JSON do cartão (quando lido) guarda `imagens.{frente,verso}` apontando
  para essas fotos (`_analisar_cartao_em_off` seta `info["imagens"]` com os
  caminhos salvos no lead).
- [ ] **Pendente:** expor campo unificado `imagens` na resposta do lead (hoje são
  os 2 paths + `cartao.imagens`).
- [ ] **Pendente:** bloco "🖼️ Imagens do cartão" no detalhe do funil para leads
  manuais que ganharam foto (a miniatura hoje só aparece quando `origem='cartao'`).
- [x] Confirmado: `POST /leads` de um lead existente aceita anexar foto SEM
  apagar os campos manuais (atualizar + `salvar_cartao`) — coberto pelos testes
  existentes (`test_..._sem_cartao_json_continua_compativel`, edição preservando funil).
- [ ] Testes novos de exibição `imagens` (pendente, junto com a UI acima).

### 3. Excluir leads ("vai que eu erre")
- [ ] **Backend:** `db.excluir_lead(lead_id)` apagando fotos do disco + registro
  (cascade já cobre histórico/atividades/cartão).
- [ ] **API:** `DELETE /api/leads/{lead_id}` (ou POST .../excluir) com regra 5.5
  (gestor tudo; BDR/SDR só os próprios; 404 se não puder).
- [ ] **UI funil:** botão 🗑 Excluir com confirmação no detalhe do lead.
- [ ] **UI admin:** opção de excluir no gestor.
- [ ] Testes da exclusão.

---

## Critérios de aceite
- [ ] `/bdr`: dá pra preencher 100% manual; a foto do cartão aparece como seção
  adicional e **nunca apaga o que foi digitado**.
- [ ] Lead com foto de cartão guarda as imagens (visíveis no detalhe do funil).
- [ ] Excluir lead (gestor qualquer, BDR só os seus) remove registro + cartão +
  histórico + fotos do disco, com confirmação na UI.
- [ ] Suíte completa verde (`run_suite_local.py`).

---

## Item novo — processamento do cartão EM OFF no servidor (assíncrono)

**Decisão do dono (2026-09-02):** "a leitura do cartão precisa ser em off no
servidor — eu mando as fotos e ele processa e disponibiliza os dados; eu não
preciso ficar olhando o processamento na tela de captura."

**Modelo escolhido — Opção B (100% off):** o BDR salva o lead na hora (com a
foto anexada); o servidor lê o cartão em SEGUNDO PLANO e anexa as 📇 ao lead
sem tocar no manual.

### Implementado (2026-09-02)
- [x] **Backend:** `POST /leads` com foto nova e SEM `cartao_json` agenda a
  leitura em background (`_analisar_cartao_em_off` via `BackgroundTasks` do
  Starlette) — resposta sai rápida, o BDR não espera.
- [x] A análise off reusa os bytes ORIGINAIS da foto (qualidade de OCR) e
  grava em `lead_cartao` as 📇, aproveitando as fotos já salvas no lead.
- [x] **Modelo de IA:** `OLLAMA_MODEL` → `lfm2.5-vl:latest`
  (default em `ollama_client.py`, `.env.example` e `install.sh`).
- [x] **UI `/bdr` (100% off):** formulário manual vem PRIMEIRO (1 · 👤 Dados do
  lead); a foto virou "2 · 📷 Foto do cartão (opcional)". Selecionar foto só
  anexa (sem spinner, sem `/extract` na tela); 💾 Salvar envia a foto e o
  servidor lê depois. Manual nunca é sobrescrito.
- [x] Removido o fluxo síncrono da captura (seção 📇 "conferir antes de
  salvar", botão "preencher sem foto" e spinner) — o cartão aparece como 📇
  adicional no funil quando a leitura off termina.
- [ ] **Pendente:** testar a leitura off no servidor real (uvicorn) — a task de
  background é do Starlette (executa após a resposta); o smoke com mock
  confirmou o resultado final. Revisar na VPS após `git pull && install.sh`.
