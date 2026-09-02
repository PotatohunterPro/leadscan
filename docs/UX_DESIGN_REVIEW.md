# UX & Design Review — Locação 360

**Data:** 16/08/2026
**Escopo:** Análise de UX, fluxo do usuário, consistência visual e cores — **sem alterações de código**
**Referência:** Design System "Apple-Inspired 1.0" (`app/assets/css/design-tokens.css` + `globals.css`)

---

## 1. Consistência do Fluxo do Usuário (Jornada)

### 1.1 Jornada ideal vs atual

| Etapa | Ideal (Apple-like) | Atual | Problema |
|---|---|---|---|
| Login | Identidade visual única | Página `slate-950` escura (fora do design system) | 2 identidades visuais |
| Onboarding 1º uso | Setup guiado | Dashboard sem estados vazios acionáveis | Dead-end "Nova Locação" |
| Criar OS | 4 passos claros | Wizard bom, mas sem atalho p/ cadastrar cliente/unidade | Trava na etapa 1/2 |
| Assinatura | Cliente assina quando quiser | Assinatura **obrigatória no wizard** + link redundante | Fluxos contraditórios |
| Entregar/Devolver | Check-in/out físico | **Sem botões** na UI | Ciclo nunca avança |
| Ocorrência | Registrar avaria no fluxo | **Sem botão "Nova"** | Módulo morto |
| Relatórios | Drill-down | Datas com fuso errado | Números duvidosos |
| Comando ⌘K | Navega direto | "documents" → vai para `configuracoes` (Settings) | Dead-end de navegação |

### 1.2 Pontos de fricção na jornada

1. **Dead-end de onboarding (galinha-ovo):** o botão primário do dashboard é "Nova Locação", mas o wizard exige clientes e equipamentos pré-cadastrados. Tenant novo sem nada cadastrado trava nas etapas 1 e 2, sem atalho para cadastrar.
2. **Assinatura obrigatória na criação:** `nova.vue` bloqueia a criação sem assinatura no canvas. Toda OS sai assinada, mas o status permanece `RASCUNHO` — a OS nunca transita para `AGUARDANDO_ASSINATURA`/`APROVADA`.
3. **Sem avanço de status na UI:** nenhum componente chama `PUT /api/rentals/:id/status`. Não há botões "Entregar", "Devolver", "Concluir", "Cancelar" em nenhuma tela.
4. **Sem criação de ocorrências na UI:** `OccurrencesView` é somente leitura (lista + filtros). O registro de avaria/perda/atraso existe só via API.
5. **Atalhos ⌘K inconsistentes:** resultados de busca "documents" navegam para `/ ?tab=configuracoes` (Settings), que não mostra documentos.

---

## 2. Nota para o Designer (Sistema Clean, Apple-Like)

### 2.1 O que está bem resolvido

- **Design tokens sólidos** (regra 80-90% neutros / 10-20% acento, escala 4pt, raios 8-20px, elevações sutis, dark mode desenhado separadamente).
- Alvos de toque ≥44px respeitados.
- Foco visível (`focus-visible`) em todos os controles.
- `prefers-reduced-motion` tratado.
- Cores semânticas sempre com label (nunca só cor).
- Empty states existem (mas sem CTA — ver 2.3).

### 2.2 Inconsistências a corrigir

1. **Duas identidades visuais:** `login.vue`, `admin/index.vue`, `offline.vue` usam `slate-950`/`sky`/`emerald` (paleta Tailwind pura), ignorando completamente os tokens. Item nº 1 de "clean".
2. **Cor da tinta de assinatura divergente:** wizard usa `#0ea5e9` hardcoded; `assinar/[token].vue` lê `--color-accent` (`#0071e3`). Mesmo gesto, cores diferentes.
3. **Overload semântico do vermelho:** bloco "Tensão Elétrica" usa `border-danger`/`bg-danger-subtle`. Vermelho = destrutivo/erro no HIG. Campo obrigatório deveria ser neutro ou com acento.
4. **Escala tipográfica quebrada:** dezenas de `text-[10px]`, `text-[11px]` arbitrários; `font-extrabold` (900) com Inter carregada só até 700. Usar `--text-caption`/`--text-caption2` e `--weight-bold`.
5. **`shadow-2xl`** no footer do wizard é default do Tailwind, não um token (`--elevation-*`).
6. **Header com opacidades diferentes:** `HeaderBar` usa `bg-surface/80`, wizard usa `bg-surface/90`. Padronizar.
7. **Opacidades em cores-var não funcionam:** `border-danger/40`, `bg-accent-subtle/60`, `bg-danger/20` aplicados sobre `var(--color-*)` **são no-ops no Tailwind** (sem `<alpha-value>`). A transparência pretendida não acontece — usar `color-mix()` (como já feito no Toast).
8. **Skeletons:** hoje spinners inline; Apple usa skeleton/greyscale em carregamento de listas.
9. **Bottom sheets no mobile:** modais centrados (`BaseModal` com `items-center`) em telas pequenas; HIG iOS prefere sheet de baixo (o `MoreSheet` já faz isso).
10. **Dinheiro sempre verde:** Apple usa preto para total; verde reservado para "sucesso/ok". Revisar hierarquia.
11. **Empty states sem CTA:** todo empty state deveria ter ação primária (ex.: "Cadastrar primeiro cliente", "Adicionar unidade").

### 2.3 Princípios a seguir (Apple HIG)

- **Uma identidade, um token:** nenhum hex hardcoded; nenhuma cor fora dos tokens.
- **Hierarquia visual:** 1 ação primária por tela; ações destrutivas sempre com confirmação.
- **Feedback imediato:** estados de loading/sucesso/erro consistentes em todas as ações.
- **Atalhos de teclado consistentes** (⌘K funciona; ampliar para ⌘N nova locação, etc.).
- **Empty states acionáveis:** "não há dados" sempre deve oferecer o próximo passo.

---

## 3. Análise de Consistência de Cores

### 3.1 Tokens (light/dark): ✓ coerentes

Design tokens desenhados separadamente para claro/escuro (não é inversão). Escala neutra + acento + semânticas bem definidas.

### 3.2 Inconsistências identificadas

| Item | Valor no token | Valor real no app | Consistente? |
|---|---|---|---|
| Fundo do app | `--color-background: #f5f5f7` | Login/Admin/Offline `#020617` | ❌ |
| Acento | `--color-accent: #0071e3` | Login/Admin `sky-600 #0284c7`, foco `#0ea5e9` | ❌ |
| PWA manifest | — | `background_color #020617`, `theme_color #0284c7` | ❌ (não segue tokens) |
| Tinta assinatura | `--color-accent` | wizard `#0ea5e9` vs assinar `#0071e3` | ❌ |
| Admin CSS scoped | — | `#1e293b`, `#334155`, `#0ea5e9` hardcoded | ❌ |
| Erro/danger | `#ff3b30` | admin `red-400 #f87171`, login `red-400` | ❌ |
| Sucesso | `#34c759` | admin `emerald-400` | ❌ |

### 3.3 Semântica de badges (StatusBadge.vue): ✓ coerente

- OS: `RASCUNHO`=info, `AGUARDANDO_ASSINATURA`=warning, `APROVADA`=success, `ENTREGUE`=info, `DEVOLVIDA/FINALIZADA`=neutral, `CANCELADA`=danger ✓
- Unidades: `DISPONIVEL`=success, `RESERVADO`=warning, `LOCADO`=info, `MANUTENCAO`=warning ✓
- Ocorrências: `ABERTA`=danger, `EM_ANALISE`=warning, `RESOLVIDA`=success ✓

### 3.4 Cores dentro do design system (dashboard/views): ✓ consistentes

Dashboard, listas e views usam os tokens corretamente. As inconsistências estão **concentradas** em login/admin/offline/PWA manifest.

---

## 4. Recomendações Priorizadas

| Prioridade | Ação | Arquivos |
|---|---|---|
| P0 | Migrar login, admin e offline para o design system | `pages/login.vue`, `pages/admin/index.vue`, `pages/offline.vue` |
| P0 | Alinhar manifest/theme-color aos tokens | `nuxt.config.ts` |
| P1 | Unificar cor da tinta de assinatura via token | `NewRentalWizard.vue`, `assinar/[token].vue` |
| P1 | Corrigir opacidades no-op com `color-mix()` | `globals.css`, componentes |
| P1 | Adicionar CTAs nos empty states de onboarding | `ClientsView`, `EquipmentView`, `RentalOrderList` |
| P2 | Implementar skeletons de carregamento | views com dados async |
| P2 | Padronizar scale tipográfica (remover `text-[10px]`/`text-[11px]`) | todos os .vue |
| P2 | Bottom sheets em mobile para modais de formulário | `BaseModal.vue` |