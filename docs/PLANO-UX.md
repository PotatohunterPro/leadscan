# Plano de UX — LeadScan (aplicando UX_DESIGN_REVIEW.md)

Base: `UX_DESIGN_REVIEW.md` (review Apple-like/HIG). Ela foi escrita para o
projeto antigo (Locação 360 — Vue/Nuxt, `pages/login.vue`, `nuxt.config.ts`,
etc.) que NÃO existe aqui. Este plano **traduz os princípios** da review
(seção 2.3) e as categorias de problema para a realidade do LeadScan:
FastAPI + `static/index.html` (1 página mobile-first) + painel admin em
`templates/*`.

## 0. Princípios herdados da review (2.3)

1. **Uma identidade, um token** — nenhum hex solto; cores via variáveis CSS.
2. **Hierarquia visual** — 1 ação primária por tela; destrutivo com confirmação.
3. **Feedback imediato** — loading/sucesso/erro consistentes em TODA ação.
4. **Empty states acionáveis** — "não há dados" sempre oferece o próximo passo.
5. **Mobile-first & acessível** — alvos ≥44px, foco visível, reduced-motion.

Não se aplicam ao LeadScan (projeto diferente): ⌘K, skeletons, bottom sheets,
dark mode, wizard de OS, manifest PWA.

## 1. Diagnóstico — problemas atuais (mapeados)

### 1.1 Fluxo / jornada (P0)

| # | Problema | Onde | Princípio violado |
|---|---|---|---|
| U1 | **Duplo clique em "💾 Salvar lead" cria lead duplicado** — `btn-salvar` não tem guarda de in-flight nem estado desabilitado | `static/index.html` (handler do btn-salvar) | Feedback imediato (3) |
| U2 | **Feedback longe da ação**: aviso de validação/erro/sucesso fica no topo (`#aviso` da seção de captura). Ao salvar/validar, o usuário está no formulário (abaixo) e não vê o erro | `static/index.html` | Feedback imediato (3) |
| U3 | **Sem fluxo manual (galinha-ovo da review 1.2.1)**: `secao-form` só aparece após um `/extract` com sucesso. O vendedor que quer registrar um lead SEM foto (V2: foto é opcional, coleta manual é a base) não consegue | `static/index.html` (processarFoto) | Empty states/jornada (4) |
| U4 | **Sem "novo lead"**: após salvar, o formulário continua preenchido; começar outro lead exige recarregar a página ou fotografar de novo | `static/index.html` | Jornada |

### 1.2 Feedback e estados (P0/P1)

| # | Problema | Onde | Princípio |
|---|---|---|---|
| U5 | Botão Salvar sem estado "Salvando…" (spinner + disabled) | `static/index.html` | 3 |
| U6 | "Enviar no WhatsApp" persiste o lead **silenciosamente**: falha de persistência vai só pro `console.warn`; usuário não sabe se salvou | `static/index.html` (enviarWhatsApp) | 3 |
| U7 | Extração OK: mensagem no topo (U2) + scroll vai para a seção do cartão — ok, mas o aviso "✅ Cartão lido" fica fora da vista | `static/index.html` | 3 |

### 1.3 Consistência visual (P1)

| # | Problema | Onde | Princípio |
|---|---|---|---|
| U8 | **Duas identidades**: app/login usam o gradiente verde; admin usa header escuro `#1f2430` + hex soltos (`#1e293b`…) | `templates/admin_status.html`, `templates/admin_leads.html` | 1 |
| U9 | Cores duplicadas como hex solto nos templates admin (verde, roxo `#7c3aed`, vermelho) — sem tokens CSS compartilhados como `static/index.html` | `templates/*` | 1 |
| U10 | Sem documentação da semântica de cor: **verde = lead/ação**, **roxo = IA/cartão**, **vermelho = erro** | `static/index.html`, README | 1 |

### 1.4 Acessibilidade / mobile (P1/P2)

| # | Problema | Onde | Princípio |
|---|---|---|---|
| U11 | Sem `focus-visible` explícito em botões (primário/secundário/wa/usar/download) | `static/index.html`, `templates/*` | 5 |
| U12 | Sem `prefers-reduced-motion` (spinner gira sempre) | `static/index.html` | 5 |
| U13 | Alvos pequenos: `summary` (details) e botões "[ Usar no Lead ]" (font 12px, padding 8px) | `static/index.html` | 5 |
| U14 | Empty state "Nenhum lead ainda — tire a primeira foto! 📸" **sem CTA** | `static/index.html` (carregarUltimosLeads) | 4 |

## 2. Plano de implementação

### Fase UX-1 — Bugs de fluxo e feedback (P0) — `static/index.html`

1. **U1+U5 — Guarda de duplo submit + estado no Salvar:**
   - `salvando` flag; desabilitar `btn-salvar` e trocar label para "💾 Salvando…" com spinner inline; reabilitar no fim (sucesso ou erro).
   - Mesma proteção aplicada quando o WhatsApp dispara `persistirLead()`.
2. **U2+U7 — Feedback localizado:**
   - Criar `#aviso-form` (aviso próprio da seção 👤 DADOS DO LEAD) para validação/erro/sucesso de salvar.
   - Ao validar/salvar: `scrollIntoView` suave até o aviso relevante.
   - Manter o `#aviso` da captura só para o fluxo de foto/extract.
3. **U3 — Fluxo manual (sem foto):**
   - Novo botão secundário na captura: "✍️ Preencher sem foto" (visível sempre) → mostra o formulário sem exigir `/extract`.
   - `estado.cartao/caminhos` ficam nulos; salvar funciona normal (sem cartao_json).
   - Atende o V2 (foto é opcional; coleta manual é a fonte A).
4. **U4 — "Novo lead":**
   - Após salvar com sucesso, exibir botão "🆕 Novo lead" (e/ou toast com ação): limpa formulário + `estado` + fotos/previews + esconde seções do cartão.
   - Se houver dados não salvos e o usuário fotografar outro cartão, confirmar antes de descartar (hoje descarta silencioso).

### Fase UX-2 — Consistência e feedback restante (P1)

5. **U6 — Persistência no WhatsApp com feedback:**
   - `persistirLead()` no WhatsApp passa a mostrar feedback não-bloqueante: sucesso ("✅ Lead salvo — mensagem enviada") ou erro ("⚠️ Não consegui salvar o lead — a mensagem foi enviada mesmo assim").
6. **U8+U9 — Identidade única do admin:**
   - Trocar o header escuro `#1f2430` dos templates admin pelo gradiente verde (mesmo do login/app) ou definir token único.
   - Extrair as cores repetidas para variáveis CSS no topo de cada template (padrão do `index.html`): `--verde`, `--verde-escuro`, `--ia`, `--erro`, `--borda`, `--texto`…
   - Alinhar `admin_login.html` (já verde ✓) para usar as mesmas variáveis.
7. **U11 — `focus-visible`:** estilo `:focus-visible { outline: 2px solid var(--verde); outline-offset: 2px; }` em todos os botões/links/summary (index + admin).
8. **U14 — Empty states com CTA:**
   - "Nenhum lead ainda" → botão "📸 Tirar primeira foto" (scroll p/ captura) + link "Abrir painel admin".
   - Seção do cartão vazia pós-falha → CTA "Tentar de novo".

### Fase UX-3 — Polish (P2)

9. **U12 — `prefers-reduced-motion`:** desativar/desacelerar o spinner (`@media (prefers-reduced-motion: reduce) { .bola { animation: none } }`) e os scrolls suaves.
10. **U13 — Alvos ≥44px:** aumentar altura dos botões "usar" e `summary`; espaçamento dos itens do cartão.
11. **U10 — Documentar semântica de cor** (comentário no CSS + README): verde = lead/ação principal, roxo = IA/cartão, vermelho = erro/destrutivo, cinza = neutro.

## 3. Fora de escopo (consciente)

- Dark mode, skeletons, bottom sheets, ⌘K — não fazem sentido no tamanho atual do app (review 2.2.7/2.2.9/2.3 — não aplicáveis).
- Redesign visual completo — o app é funcional e mobile-first; o plano é de **polimento de UX**, não de reescrita.

## 4. Critérios de aceite (teste manual)

1. Clicar "Salvar" 5× rápido cria **um** lead só (e o botão mostra "Salvando…").
2. Salvar sem os obrigatórios mostra o erro **visível na tela** (scroll automático), não no topo da página.
3. "✍️ Preencher sem foto" abre o formulário e salva lead manual sem `cartao_json`.
4. Após salvar, "🆕 Novo lead" limpa tudo; fotografar outro cartão com dados não salvos pede confirmação.
5. WhatsApp com persistência falha mostra aviso (não silencioso).
6. Admin tem o mesmo visual do app (header verde/tokens); login idem.
7. Tab (teclado) mostra foco visível em todos os botões; `prefers-reduced-motion` pausa o spinner.
8. Todos os botões têm ≥44px de altura de toque.
9. Suíte de testes continua verde (94 testes) — nenhuma mudança de backend/contrato.
