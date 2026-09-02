# Plano — Adotar o design system HUB Solução no LeadScan

**Objetivo:** unificar a identidade visual do LeadScan (funil + captura + admin) ao
design system "premium corporate fintech" da HUB Solução (mesma empresa),
eliminando a "segunda identidade" verde/roxa e os hex crus. Sem quebrar o JS.

**Referência:** `apresentacao hubqwen2.html` (`:root` HUB).
**Restrições:** não tocar no JS (esc(), Number(l.id), btn.disabled, seqCarregar,
pendenteEstagio, nav.share); manter o bottom sheet mobile do funil; manter empty
states com CTA; manter `--amber` só p/ atenção; não renomear IDs que os testes
validam (`sel-usuario`, `btn-novo`, `btn-salvar`, `f-busca`, `m-estagio`...).

---

## Tokens HUB a adotar

```
COR DE MARCA     --deep:#0B4D8C  --deep-2:#093D70  --azure:#0089CE  --azure-2:#0074B0  --sky:#5BC1EA  --sky-soft:#B8E0F5
NEUTROS AZULADOS --bg:#F5F9FC  --bg-2:#EEF5FB  --card:#FFFFFF  --ink:#0F2A43  --ink-2:#1C3A57  --mut:#5C7189  --mut-2:#8497AD  --line:#DCE9F5  --line-2:#C5D9EC
SEMÂNTICAS       --green:#16A34A  --green-bg:#E6F7EC  --amber:#B45309  --amber-bg:#FFF7ED  --wa:#128C4B
ADICIONADAS      --danger:#DC2626  --danger-bg:#FEF2F2  --danger-line:#FECACA  (HUB não tem vermelho)
FORMA            --r-lg:22  --r-md:16  --r-sm:12  --r-xs:8  --sh-sm/md/lg/in  --ease:cubic-bezier(.2,.8,.2,1)
FONTE            Inter (corpo) + Sora (títulos)
```

## Mapa semântico HUB → LeadScan

| LeadScan hoje | HUB | Nota |
|---|---|---|
| Header funil `#26231f` e verde captura/admin | gradiente `deep→deep-2→azure` | unifica identidade |
| `.primario` preto / verde | `.btn.primary` gradiente `azure→deep` | CTA forte |
| `.secundario` | `.btn.ghost` | |
| WhatsApp `#25d366` | `.btn.wa` gradiente | |
| `.painel/.cartao` | `.card` (`--card`,`--line`,`--r-lg`,`--sh-md`) | |
| `.chip` métricas | `.kpi` (barra de acento) / `.chip` pílula | |
| `.tgl` filtros | `.tile` (`on`=`azure`) | resolve alvo <44px |
| Atrasado `#b45309` | `--amber` | **já bate** |
| Sucesso `#166534` | `--green` | |
| Erro `#b91c1c/#dc2626` | `--danger` (novo) | |
| IA roxo `#7c3aed` | `--azure`/`--sky-soft` + `.badge.b1` | sem roxo no HUB |
| `card-valor` preto | `--ink` (num-destaque → `.num` gradiente) | |
| Modal bottom-sheet | `.modal-card` HUB + manter `flex-end` mobile | |

---

## Checklist de execução

### P0 — Fundação
- [x] Criar `static/design-tokens.css` (tokens HUB + `--danger*` + classes utilitárias + fontes + animações)
- [x] Linkar `/static/design-tokens.css` + Google Fonts (Inter+Sora) nos 5 templates
- [x] Migrar header dos 5 templates p/ gradiente `deep→deep-2→azure`
- [x] Botão primário de cada template → `.btn.primary` (gradiente azure→deep)

### P1 — Consistência
- [x] `funil.html`: `.painel`→`.card`, filtros→`.tile` (44px), modal→`.modal` HUB (manter bottom sheet), títulos→Sora
- [x] `static/index.html` (captura): header, seção IA roxo→azul, botões (1 primária/tela)
- [x] `admin_login.html`: card HUB + barra superior gradiente + `mpop`
- [x] `admin_leads.html`: header, `.cartao`→`.card`, tabela HUB, modal HUB (bottom-sheet mobile)
- [x] `admin_status.html`: header, status-item→`.line`

### P2 — Polimento
- [x] Indicador de estágio no kanban (bolinha colorida por `data-estagio` — novo=mut, ligacao=sky, qualificado=azure, negociacao=amber, fechado=green, perdido=danger)
- [x] Skeletons no lugar de "Carregando…" (kanban + métricas do funil)
- [x] Estados de erro/aviso com `--danger`/`--green`/`--amber`
- [x] `prefers-reduced-motion` em animações (design-tokens.css global)
- [x] Toast no padrão HUB (design-tokens.css)

### Validação
- [x] Suíte completa verde — `run_suite_local.py` → **225 testes OK** (15 módulos)
- [x] Render smoke: gestor + bdr (`/funil`), `/admin`, `/admin/leads`, `/admin/login`, `/` (captura) — todas 200 com `design-tokens.css` + Sora

---

## Notas / pendências fora do design

- **Runner `run_suite_local.py` refeito:** os arquivos de teste definem
  `DATA_DIR`/`SESSION_SECRET` e chamam `db.init_db()` no import, e `app/db.py`
  cacheia `DB_PATH` no 1º import — rodar tudo no mesmo processo (unittest
  discover) fazia o banco de um módulo vazar para o outro (5 falhas de ordem
  introduzidas pelo `test_fix_final.py`). Agora cada módulo roda num subprocesso
  isolado; a suíte inteira passou a ficar verde também no runner unittest
  (o `pytest` já passava).
- `tests/test_db_funil.py` `TestMetricas` ganhou `setUpClass` com `db.init_db()`
  (dependia de init global de outro módulo — bug latente revelado pelo isolamento).
- Segunda etapa do login (B16) usa `criar_token_login`/`token_login_valido` do
  `auth.py` — fora do design, já implementado no commit `e547ff5`.
