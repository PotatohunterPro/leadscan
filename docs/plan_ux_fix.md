# PLANO-UX-FIX — implementação e validação (LeadScan)

Origem: `PLANO-UX.md` (tradução da `UX_DESIGN_REVIEW.md` para o LeadScan).
Método: uma fase por vez — implementar, validar, seguir.

## Fase UX-1 — bugs de fluxo e feedback (P0) ✅

- [x] U1+U5 — guarda de duplo submit + estado "💾 Salvando…" no botão Salvar
- [x] U2 — feedback localizado: `#aviso-form` no formulário + scroll até o aviso
- [x] U3 — fluxo manual: botão "✍️ Preencher sem foto" (foto opcional — V2)
- [x] U4 — "🆕 Novo lead" após salvar + confirmação antes de descartar dados

Validação UX-1:
- [x] Sintaxe JS (node) OK
- [x] 28 IDs referenciados no JS existem no HTML — nenhum faltando
- [x] Suíte backend: 94 testes OK
- [x] Smoke test: página serve com os novos elementos

## Fase UX-2 — consistência visual e feedback restante (P1) ✅

- [x] U6 — feedback da persistência no WhatsApp (não silencioso; avisos do fluxo
      WhatsApp movidos para perto da ação, `#aviso-form`)
- [x] U8+U9 — identidade única: admin com header verde (gradiente do app) +
      tokens CSS `:root` compartilhados; hex hardcoded removidos (exceto o
      bloco `<pre>` escuro do OCR, intencional)
- [x] U11 — `focus-visible` em botões/links/inputs/summary (index + 3 templates)
- [x] U14 — empty states com CTA: "📸 Tirar primeira foto" + "Painel admin"

Validação UX-2:
- [x] Sintaxe JS em todos os templates (máscara Jinja) OK
- [x] Nenhum uso hardcoded de cor-chave fora do `:root` (grep verificado)
- [x] Smoke test: /admin/login, /admin, /admin/leads com header verde; /api/status OK
- [x] Suíte backend: 94 testes OK

## Fase UX-3 — polish (P2) ✅

- [x] U12 — `prefers-reduced-motion`: spinner parado + scrolls sem smooth
      (helper `rolarAte` checa matchMedia)
- [x] U13 — alvos de toque ≥44px: botões "[ Usar no Lead ]", `summary`, links
      de download; token `--ia-escuro` no lugar do hex
- [x] U10 — semântica de cor documentada: comentário no `:root` do index +
      seção "🎨 Design (UX)" no README

Validação UX-3:
- [x] Sintaxe JS OK; IDs OK; `min-height: 44px` e `prefers-reduced-motion` presentes
- [x] Suíte backend completa: 94 testes OK
- [x] Smoke test final: frontend com elementos UX, fluxo manual (sem cartao) salva lead, /health OK

## Resumo final

Arquivos alterados: `static/index.html`, `templates/admin_status.html`,
`templates/admin_leads.html`, `templates/admin_login.html`, `README.md`,
`PLANO-UX.md`, este arquivo.

Nada de backend/contrato de API mudou — os 94 testes seguem verdes.
Pendências fora do código (ambiente): docker build/deploy na VPS e teste
manual com o cartão real (itens 20/21 do V2).
