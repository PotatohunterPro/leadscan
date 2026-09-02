# Plano de implementação V3 — Funil com solidez de CRM maduro

Base: `funildevendas.md` completo (R0 ok, seção 1 confirmada no código) +
`funil_implement_v2.md` (V2 ok) + a especificação V3 deste repositório
(seções 5.1–5.5). Tudo foi implementado no código; este doc registra as
decisões de projeto tomadas (a spec pede explícito no 5.2).

## R0 — confirmação da base (seção 1)

- `POST /funil` criado (item 50, "+ Novo Lead" na tela) — aceita JSON ou
  form, `origem='manual'`, estágio `novo`.
- Modal de Perdido com **lista curta de motivos** (`MOTIVOS_PERDA`), sem
  `prompt()`. O drag-and-drop para a coluna Perdido/Negociação abre o modal
  em vez de agir direto.
- Frontend `funil.html` reescrito conforme a UX da seção 3: kanban com
  miniatura só p/ `origem=cartao`, segmento em texto, tempo com destaque
  discreto após `DIAS_ESTAGNADO`, 🔔 só com ação agendada, borda de atenção
  sutil p/ atrasada, mobile vira lista com seletor de estágio, detalhe em 3
  blocos, estados vazio/erro amigáveis e sem jargão técnico.
- Filtros da UI completos: chips Atrasados / Retorno hoje / Sem contato,
  origem ("De onde veio o lead"), período, busca ampliada.

## R1 — 5.1 (valor esperado) + 5.5 (visibilidade por papel)

### 5.1
- Coluna `valor_estimado REAL NOT NULL DEFAULT 0` em `leads` (migração
  idempotente via ALTER TABLE, fora de `CAMPOS` para o POST /leads não tocar).
- `PROBABILIDADE_ESTAGIO` em `app/funil.py`
  (novo=5, ligacao_feita=10, qualificado=25, negociacao=60, fechado=100,
  perdido=0).
- `metricas_funil` devolve `valor_esperado_total` e
  `valor_esperado_por_estagio`, calculados **no SQL**
  (`ROUND(SUM(valor_estimado * prob), 2)`) para bater exatamente com uma
  consulta direta no banco (critério "todo número mostrado bate com o banco").
  `valor_esperado_total` soma só os leads ABERTOS (fora de fechado/perdido).
- `POST /api/funil/{id}/dados` atualiza o valor (campo, não muda de estado —
  não gera atividade). `POST /funil` aceita `valor_estimado`.
- Card mostra o valor quando preenchido; cabeçalho das métricas mostra
  "Valor esperado no funil: R$ X"; bloco de dados do detalhe tem o campo
  editável.

### 5.5
- Tabela `usuarios` (nome UNIQUE, papel DEFAULT 'sdr'; papéis
  `sdr | bdr | gestor`), semeada de `RESPONSAVEIS` + `PAPEL_RESPONSAVEL` no
  startup (idempotente — papéis existentes não são sobrescritos). Config no
  código, sem tela de admin.
- Login vira "senha + quem está entrando": o cookie assinado guarda só o
  nome (`u:<nome>`); o papel é consultado NO BANCO a cada request —
  cliente não controla o papel. Sessão 'admin' antiga (sem usuário) =
  gestor, vê tudo (compatibilidade com install.sh e testes antigos).
- `usuario_logado(request)` resolve nome+papel; `_restricao_visivel` aplica
  `responsavel_atual = usuário` **na query** de listagem, métricas e
  relatório. Não-gestor também não abre o detalhe de lead alheio (404) e a
  escrita força o responsável = usuário logado.
- UI: gestor tem filtro opcional "Meus leads"; bdr/sdr já abrem restritos
  (sem dropdown de responsável).

## R2 — 5.2 (agendada/realizada) + 5.3 (oportunidade)

### 5.2
- Coluna `status TEXT NOT NULL DEFAULT 'realizada'` em `lead_atividades`
  (migração idempotente; bancos antigos ficam todas 'realizada').
- `salvar_proxima_acao` grava atividade `tipo='proxima_acao'`,
  `status='agendada'`; uma nova próxima ação **cancela** a agendada pendente
  anterior (só uma ação pendente por lead). Limpar a próxima ação também
  cancela.
- **Decisão (como ligar agendada ↔ realizada): por ID.** O botão "✓
  concluída" na timeline chama `POST /api/funil/{lead}/atividade/{id}/concluir`
  que marca 'realizada' e limpa a próxima ação pendente do lead. NÃO por
  proximidade de data — frágil quando duas ações caem no mesmo dia.
  Existe também `/cancelar` (marca 'cancelada').
- Timeline distingue os três estados visualmente; `tem_acao_agendada` no
  kanban E no detalhe vem da atividade agendada pendente — 🔔 some quando a
  atividade vira realizada/cancelada.

### 5.3
- `mudar_estagio`: `qualificado → negociacao` passa a exigir observação
  obrigatória ("por que virou oportunidade real") — 422 no backend. Só essa
  aresta: reabertura de perdido/fechado pra negociação não exige (preserva
  fluxos antigos).
- Atividade própria `tipo='oportunidade'`, descrição "🎯 Virou oportunidade
  — {obs}", com estagio_anterior/novo. `oportunidade` entrou em
  `TIPOS_ATIVIDADE`.

## R3 — 5.4 (relatório de perdas)

- `GET /api/funil/relatorio-perdas?de&ate` — contagem cruzando
  `motivo_perda × origem × responsavel_atual` (lê de `leads` com
  `estagio='perdido'`; sem tabela nova), ordenado por quantidade desc, com
  soma de `valor_estimado`. Visibilidade (5.5) aplicada.
- Declarada ANTES de `/api/funil/{lead_id}` (senão o path param engole a
  rota e devolve 422).
- UI: seção colapsável "📉 Relatório de perdas" com filtro de período e
  tabela simples (sem gráfico).

## R4 — smoke end-to-end

- `TestR4Smoke` no `test_main_funil_v3.py`: captura→kanban→ligação→
  qualificado→próxima ação→negociação (com observação)→fechado; perdido com
  motivo; reabertura preservando motivo/histórico; perdido sem motivo 422;
  valor esperado batendo com consulta direta no banco.

## Fora de escopo (mantido fora)

Campanhas de e-mail, Cases/suporte, Knowledge Base, Surveys, Studio,
integração de calendário externo, templates de PDF — não implementado.

## Testes

- Suíte completa verde: **199 testes** (`run_suite_local.py`).
- Novos: `tests/test_db_funil_v3.py` (banco), `tests/test_main_funil_v3.py`
  (API + smoke). Testes V1/V2 ajustados onde a regra nova de 5.3 exigiu
  observação na transição qualificado→negociacao.
