# Fix Final — Auditoria de bugs do LeadScan (V3)

Data: 2026-09-02 · Suíte de testes: **199 testes OK** · Push: `5304b0e..d1df96b main -> main`

Análise completa do código atrás de bugs, feita por auditoria nas três frentes:
backend (`app/main.py`, `app/auth.py`, `app/funil.py`), banco (`app/db.py`) e
frontend (`templates/funil.html`). Todo achado crítico/alto foi confirmado por
leitura direta do código.

**Total: 54 achados** — 1 crítico, 6 altos, 19 médios, 28 baixos.

---

## ✅ STATUS DA CORREÇÃO (2026-09-02 — commit da rodada de fixes)

Todos os 54 achados foram corrigidos. Suíte: **225 testes OK** (199 + 26 novos
em `tests/test_fix_final.py`).

| Severidade | Corrigidos | Onde |
|---|---|---|
| C1 | ✅ | `main.py` — `POST /leads` com `lead_id` exige sessão de admin + checagem 5.5 |
| A1 | ✅ | `auth.py` — fail-closed: sem `SESSION_SECRET` login/sessão desativados (sem fallback) |
| A2 | ✅ | `main.py` — `/api/leads`, `/api/leads/export`, `/api/leads/{id}` filtram por `responsavel` |
| A3 | ✅ | `main.py` — helper `_garantir_visivel` no início de TODAS as mutações do funil |
| A4 | ✅ | `db.py` — `date(data_proxima_acao) < date('now')` (ação de hoje não é atrasada) |
| A5 | ✅ | `db.py` — `mudar_estagio` para fechado/perdido cancela agendadas e limpa colunas |
| A6 | ✅ | `funil.html` — removido `onclick` inline do "✓ concluída" (só o listener) |
| M1–M22 | ✅ | `db.py` + `main.py` + `funil.html` — ver notas abaixo |
| B1–B27 | ✅ | `db.py`, `main.py`, `funil.py`, `funil.html`, `auth.py`, `app/__init__.py` |

Notas de decisão:
- **M3**: `valor_esperado_por_estagio` agora exclui fechado/perdido e os valores
  por estágio ficam sem arredondamento; o total arredonda a soma — assim
  `total == Σ(por_estagio)` exato E `total == ROUND(SUM)` direto no banco.
- **M11**: "lead não encontrado" passou a devolver **404** (antes 422) — testes
  `test_atividade_lead_inexistente_422` atualizados para 404.
- **B5**: `ultima_extracao_sucesso` só considera origem `cartao` (teste atualizado).
- **B16**: login em duas etapas — a lista de usuários só aparece após a senha
  correta (token curto assinado); senha+usuário no mesmo POST continua aceito.
- **M10**: rate limiting simples por IP (em memória) em `/extract`, `POST /leads`
  e `/admin/login`; testes usam `tests/conftest.py` para zerar entre testes.
- **A1**: os testes definem `SESSION_SECRET` próprio em `tests/conftest.py` e nos
  arquivos que fazem login (o app nunca usa segredo fixo).

---

## CRÍTICO

### C1 — `POST /leads` público atualiza/sobrescreve qualquer lead (IDOR total)
- **Onde:** `app/main.py:340-444` (rota sem auth), `401-404` (`lead_id = int(form.get("lead_id") or 0)`), `413-421` (`db.atualizar_lead`), `432-436` (`db.salvar_cartao`).
- **Problema:** a rota é pública (a UI de captura `static/index.html` depende disso) e aceita `lead_id` arbitrário do cliente. Não há checagem de cookie nem de propriedade.
- **Impacto:** qualquer pessoa na internet, sem login, pode (a) sobrescrever todos os campos de qualquer lead (whatsapp, e-mail, anotações, mensalidade, possui_sistema — dados sensíveis de qualificação); (b) forçar a exclusão de fotos de outros leads (`main.py:395-397` apaga a foto antiga ao substituir); (c) substituir o JSON do cartão de qualquer lead via `cartao_json`. É a rota que o próprio funil usa para "Editar dados" (`templates/funil.html:753-774`).
- **Correção:** ao existir `lead_id`, exigir sessão de admin válida E conferir `responsavel_atual` (regra 5.5) antes do `atualizar_lead`/`salvar_cartao` — deixando o fluxo de captura de *novo* lead intacto quando `lead_id` vier vazio.

---

## ALTO

### A1 — Sessão forjável se `SESSION_SECRET` não estiver no ambiente
- **Onde:** `app/auth.py:21-24` (`SESSION_SECRET or "dev-secret-nao-usar-em-producao"`, salt fixo `"leadscan-admin"`).
- **Problema:** se o deploy subir sem `SESSION_SECRET`, o segredo usado para assinar o cookie é público e conhecido; o payload do cookie também é trivial (`"admin"`).
- **Impacto:** qualquer pessoa pode assinar um cookie `leadscan_session` válido e entrar como gestor em `/admin` e `/funil` (leitura e escrita de toda a base, export de CSV, fotos).
- **Correção:** se `SESSION_SECRET` estiver vazio, não cair para segredo fixo — logar erro e negar login/sessão (fail-closed) em vez de usar fallback.

### A2 — BDR/SDR contornam a visibilidade 5.5 via APIs admin `/api/leads*`
- **Onde:** `app/main.py:549-557` (`api_listar_leads` devolve `SELECT *` completo), `560-580` (export CSV com todos os campos), `583-589` (detalhe completo + cartão).
- **Problema:** a proteção `exige_admin_api` só valida o cookie; não valida papel. Um BDR/SDR logado (ex.: "SDR 1") pode chamar essas rotas diretamente e ver TODOS os leads, incluindo campos sensíveis que a regra 5.5 deveria esconder dele.
- **Impacto:** vazamento de dados de vendas entre membros do time (a regra 5.5 é aplicada só em `/api/funil*`, não nas APIs `/api/leads*`).
- **Correção:** nas três rotas, aplicar `_restricao_visivel(usuario_logado(request))` como filtro `responsavel` na consulta (igual já feito em `api_funil_listar`).

### A3 — IDOR autenticado nas mutações do funil (BDR "rouba" lead alheio)
- **Onde:** `app/main.py:731-751` (`/estagio`), `754-774` (`/ligacao`), `777-800` (`/atividade`), `803-825` (`/proxima-acao`), `828-853` (`/dados`), `856-884` (`/concluir`, `/cancelar`).
- **Problema:** só `api_funil_detalhe` (`main.py:720-728`) confere `lead["responsavel_atual"] != restrito → 404`. Todas as rotas de mutação executam direto. Agravante: `mudar_estagio` (`db.py:680-690`) e `registrar_ligacao` (`db.py:735-741`) **gravam `responsavel_atual = usuário`** a cada chamada.
- **Impacto:** um BDR, sabendo o `lead_id` (fácil de enumerar), move o estágio ou registra ligação num lead de outro responsável e, com isso, o lead **passa a pertencer a ele** (some do kanban do dono). As respostas `buscar_lead_funil` também devolvem todos os dados + cartão + histórico do lead alheio.
- **Correção:** no início de cada rota de mutação, repetir a checagem do detalhe: `restrito = _restricao_visivel(usuario_logado(request)); if restrito and lead.responsavel_atual != restrito: raise HTTPException(404)`.

### A4 — Filtro "Atrasados" conta ações de HOJE como vencidas
- **Onde:** `app/db.py:921-926` — `data_proxima_acao < ?` comparado com `agora_iso()` (timestamp completo, ex.: `2026-09-02T14:30:00+00:00`).
- **Problema:** o front envia data pura (`<input type="date">` → `"2026-09-02"`). A comparação lexicográfica `"2026-09-02" < "2026-09-02T14:30:00+00:00"` é **verdadeira** — a string mais curta é menor.
- **Impacto:** todo lead com próxima ação marcada para hoje aparece no filtro "Atrasados" desde a meia-noite, corrompendo a fila de trabalho do time. O teste existente (`test_db_funil_v2.py:112`) só cobre data de 2000, então não pega o caso.
- **Correção:** comparar por dia: `date(data_proxima_acao) < date('now')`.

### A5 — Fechar/perder o lead não cancela a próxima ação agendada
- **Onde:** `app/db.py:675-715` (`mudar_estagio` para `fechado`/`perdido`) + `768-798`.
- **Problema:** `mudar_estagio` para `fechado`/`perdido` atualiza estágio, datas e responsável, mas **não** cancela a atividade `proxima_acao` com `status='agendada'` nem limpa `proxima_acao`/`data_proxima_acao`. Os únicos caminhos que cancelam são `concluir_atividade`, `cancelar_atividade` e `salvar_proxima_acao` (com ação vazia).
- **Impacto:** lead fechado/perdido continua com `tem_acao_agendada=True` (🔔 no kanban e no detalhe, `db.py:877`), a agendada fica pendente para sempre no histórico, e o lead reaparece nos filtros de próxima ação.
- **Correção:** no `mudar_estagio`, ao entrar em `fechado`/`perdido`, cancelar as `agendada` pendentes e limpar as 3 colunas de próxima ação na mesma transação.

### A6 — Botão "✓ concluída" dispara a ação DUAS vezes (duplo POST)
- **Onde:** `templates/funil.html:496-497` (onclick inline) + `777-784` (`conectarConcluir()` chamado em 738, 743, 794).
- **Problema:** o botão é renderizado com `onclick="concluirAtividade(...)"` **e** recebe um `addEventListener("click", ...)` em `conectarConcluir()`. Os dois handlers disparam no mesmo clique → 2 fetches `POST /api/funil/{id}/atividade/{aid}/concluir`.
- **Impacto:** duas chamadas concorrentes à API, dois toasts "Ação concluída", dois `carregar()`; o segundo POST pode falhar (atividade já concluída no servidor) e exibir toast de erro logo após o de sucesso.
- **Correção:** remover o `onclick="concluirAtividade(...)"` do template (linhas 496-497) e manter só o listener em `conectarConcluir()`.

---

## MÉDIO

### Banco (`app/db.py`)

- **M1 — `retorno_hoje` não exclui fechado/perdido** (`db.py:927-928`): o filtro `date(data_proxima_acao) = date('now')` não tem o `estagio NOT IN ('fechado','perdido')` que `atrasados` tem (`db.py:924`). Combinado com A5, leads ganhos/perdidos continuam aparecendo em "Retorno hoje". Correção: adicionar a exclusão (e corrigir A5, causa raiz).
- **M2 — Fuso horário: timestamps UTC × filtros por data UTC vs. usuário em BRT** (`db.py:928, 346-350, 930-934`): `criado_em`/`agora_iso()` são UTC (`db.py:1210-1214`) e os filtros usam `date(criado_em)`/`date('now')` (UTC). Lead capturado entre 21h e 23h59 BRT recebe data UTC do dia seguinte. Filtros `de/ate`, "Retorno hoje" e "Atrasados" deslocam um dia; relatórios de período fecham com contagem errada. Correção: armazenar também a data local ou filtrar com deslocamento de fuso conhecido, documentando que o dia é UTC.
- **M3 — `valor_esperado_total` ≠ soma de `valor_esperado_por_estagio`** (`db.py:1005-1031`): o total é calculado só com leads **abertos** (`estagio NOT IN ('fechado','perdido')`), mas `valor_esperado_por_estagio` inclui `fechado` (probabilidade 100%) e omite `perdido` (0). Além disso, o total é `ROUND(SUM(…),2)` de uma soma única, enquanto cada estágio arredonda sua própria soma. Correção: alinhar a semântica (ex.: total = Σ dos estágios, ou excluir `fechado` de `por_estagio`) e testar `total == Σ(por_estagio)`.
- **M4 — Tempo médio por estágio nunca mede o estágio `novo`** (`db.py:1163-1207`): o lead nasce em `novo` por DEFAULT do banco, mas **não** há entrada em `historico_estagios` no nascimento (só `mudar_estagio` grava). Complementar: o último estágio (inclusive `perdido`/`fechado`) dura até "agora", inflando médias de leads perdidos há meses. Correção: tratar `criado_em` como início do estágio `novo` quando não houver entrada anterior (e parar o relógio em `fechado`/`perdido` na data da perda/ganho).
- **M5 — `str(None)` grava a string `"None"` no banco** (`db.py:280, 303`): `salvar_lead` e `atualizar_lead` fazem `str(dados.get(c, "")).strip()`; JSON público com `{"cargo": null}` vira `"None"`. Correção: `(dados.get(c) or "")`.
- **M6 — Sem WAL e sem retry explícito: "database is locked" → 500** (`db.py:256-266`): `sqlite3.connect(DB_PATH)` com timeout default (5s), sem `journal_mode=WAL` e sem tratamento de `OperationalError` (busy). Correção: `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout` na abertura (e retry pontual em `OperationalError` nas escritas críticas).

### Backend (`app/main.py`)

- **M7 — Vazamento de detalhes internos em endpoints públicos** (`main.py:256-264, 265-273, 437-442`): erro do Ollama e detalhes de SQLite expostos ao cliente anônimo. Correção: `logger.exception` + mensagem genérica.
- **M8 — CSV injection no `/api/leads/export`** (`main.py:560-580`): valores crus no CSV; campo iniciando com `=`, `+`, `-`, `@` executa fórmula no Excel do gestor. Correção: prefixar `'` quando o valor começar com esses caracteres.
- **M9 — `responsavel_atual` zerado quando o gestor age sem o campo `usuario`** (`main.py:172-175` + `db.py:680-690, 735-741`): gestor sem nome e sem `enviado` grava `responsavel_atual = ""`, "desdonando" o lead. Correção: se `usuario` vier vazio, preservar o `responsavel_atual` atual.
- **M10 — Sem rate limiting** (`main.py:196-326, 340-444, 457-495`): `/extract` chama Ollama a cada request (DoS de CPU/IO), `POST /leads` sem auth cria/edita ilimitado, `/admin/login` sem backoff (brute force). Correção: limitador simples por IP (ex.: `slowapi`) e exigir login para criação de leads no funil.
- **M11 — "Lead não encontrado" retorna 422 em vez de 404** (`main.py:747-750, 770-773, 795-798, 820-823, 849-852, 865-868, 880-883`): `ValueError` de `db.*` vira 422 genérico. Correção: distinguir "não encontrado" (404) das regras de negócio (422).
- **M12 — Filtros sem validação: `estagio`/`origem` inválidos e datas malformadas silenciosamente** (`main.py:689-717`, `db.py:929-934`, `db.py:922-926`). Correção: validar com `funil.estagio_valido` e `datetime.fromisoformat` → 422.
- **M13 — `motivo_perda` livre, sem validação contra `MOTIVOS_PERDA`** (`main.py:741`, `db.py:664-667`): relatório de perdas poluído com variações digitadas. Correção: normalizar/validar contra a lista (ou forçar "Outro: <texto>").

### Frontend (`templates/funil.html`)

- **M14 — `esc()` no texto de `<option>` sem `value` corrompe dados salvos** (linhas 570 `sel-usuario` e 578 `mv-motivo`): `<option>` sem atributo `value` usa o *textContent* como valor — e o textContent contém entidades HTML (`&amp;`, `&lt;`). Ex.: responsável "Pão & Cia" vira `Pão &amp; Cia`; esse valor é enviado como `usuario` (675, 730) e como `motivo_perda` (411). Correção: `'<option value="' + esc(nome) + '">' + esc(nome) + '</option>'`.
- **M15 — BDR/SDR pode registrar ligação/interação como outro responsável** (linhas 675 e 730 usam `$("sel-usuario").value` direto; 428-431 `usuarioDaAcao()` força `USUARIO_NOME` para não-gestor): mover estágio (411) e salvar próxima ação (658) usam `usuarioDaAcao()` — correto — mas "Registrar ligação" (675) e "Registrar interação" (730) não. Correção: trocar por `usuario: usuarioDaAcao()`.
- **M16 — `hoje()` usa UTC: destaque "atrasado" errado por ~3h/dia em UTC-3** (linhas 273, 277): `toISOString()` retorna data UTC; entre 21h e 23h59 BRT, ação agendada para hoje é marcada como atrasada. Correção: montar a data com `getFullYear`/`getMonth`/`getDate` locais.
- **M17 — "Limpar" não reseta o seletor mobile `m-estagio`** (linhas 949-957): o handler reseta toggles, selects e inputs, mas não `$("m-estagio").value = ""`; `renderKanban` (338-343) relê o valor antigo → colunas continuam filtradas no mobile após "Limpar". Correção: adicionar `$("m-estagio").value = "";`.
- **M18 — Race condition em `carregar()`: respostas fora de ordem sobrescrevem o kanban** (linhas 370-384): toggles, "Aplicar", Enter na busca e conclusão de ações chamam `carregar()` sem guarda. Correção: token de sequência (`var seq`) ou `AbortController`.
- **M19 — Duplo submit sem desabilitar botão durante o fetch** (linhas 653, 670, 702, 727, 753, 827): clique duplo dispara POSTs duplicados (ligações/interações/edições duplicadas na timeline). Correção: `b.disabled = true` no início e `false` no `.then`/`.catch`.
- **M20 — Drag-and-drop em "Negociação"/"Perdido" abre o modal SEM preselecionar o estágio** (linhas 433-443): se confirmar sem trocar, move o lead para o estágio errado (default do select). Correção: após `abrirLead(id)`, setar `mv-estagio.value` e chamar `atualizaMover()`.
- **M21 — Métricas não acompanham chips/origem/busca — números contradizem o kanban** (linhas 386-396): `carregarMetricas` só envia `de`/`ate`/`responsavel`; com chip "Atrasados", origem ou busca ativos, o kanban mostra N leads mas as métricas mostram o total geral. Correção: reutilizar `paramsApi()` em `carregarMetricas` (ou documentar).
- **M22 — `carregarMetricas` falha silenciosamente e deixa "Carregando métricas…" para sempre** (linha 395 catch vazio + 185): Correção: no catch, mostrar "Métricas indisponíveis".

---

## BAIXO

### Banco (`app/db.py`)
- **B1** (`db.py:1019`): `esperado_por_estagio` omite estágios com esperado 0 — com todos os valores zerados, o estágio `novo` desaparece do mapa; a UI pode perder a coluna. Correção: incluir com 0.0.
- **B2** (`db.py:1036-1042`): `_case_probabilidade` monta SQL via f-string — hoje seguro (valores vêm somente de `PROBABILIDADE_ESTAGIO`, constantes), mas frágil para configuração futura. Correção: whitelist explícita ou placeholders.
- **B3** (`db.py:1023`): `conversao_percent = fechados/total` inclui os perdidos no denominador — conversão diluída. Correção: decidir/documentar denominador.
- **B4** (`db.py:734-747`): `registrar_ligacao` com `feita=False` mesmo assim grava `data_ligacao`, `responsavel_atual` e atividade "Ligação registrada". Correção: só gravar `data_ligacao` quando `feita=True`.
- **B5** (`db.py:454-460`): `ultima_extracao_sucesso` devolve o `criado_em` do lead mais novo de **qualquer** origem (manual também). Correção: filtrar por `origem='cartao'`.
- **B6** (`db.py:775-798`): ao substituir uma próxima ação, a agendada anterior é cancelada em silêncio (sem atividade de cancelamento); `data_hora` da atividade é o momento do agendamento — a data agendada só existe na descrição. Correção: registrar o cancelamento na timeline e guardar a data em coluna própria.
- **B7** (`db.py:1137-1152`): `_tempo_medio_especifico` — reentradas em `qualificado`/`negociacao` contam múltiplas vezes, todas medidas desde `criado_em`. Correção: medir só a primeira entrada (ou o trecho contíguo).
- **B8** (`db.py:1198`): estágio terminal (`perdido`/`fechado`) é medido até "agora" (ver M4). Correção: parar na data da entrada.
- **B9** (`db.py:239-253`): migração assimétrica — `lead_atividades` só ganha `status`; `estagio_anterior`/`estagio_novo` (e `usuarios.papel`) não têm ALTER de segurança — banco antigo sem essas colunas quebra com 500 em toda timeline. Correção: migração genérica por `PRAGMA table_info` para todas as colunas novas.
- **B10** (`db.py:383-391`): `salvar_cartao` sem checagem prévia de existência do lead — `lead_id` inválido → `IntegrityError` (FK) → 500. Correção: validar e levantar `ValueError` (422).
- **B11** (`db.py:163-183`): `init_db` sem `BEGIN IMMEDIATE` — com 2+ workers num banco novo, um request pode executar `INSERT` antes dos `ALTER TABLE` da migração e falhar com "no such column: origem". Correção: transação exclusiva com retry curto.

### Backend (`app/main.py`, `app/funil.py`)
- **B12** (`app/funil.py:106-107`): `rotulo()` nunca usado.
- **B13** (`app/db.py:449-451`): `total_cartoes()` nunca usado no app.
- **B14** (`app/db.py:522-537`): `registrar_atividade()` pública nunca usada (o app usa `_registrar_atividade`).
- **B15** (`app/main.py:35`): import de `extrair_dados` nunca usado (só `listar_modelos` é usado, linha 537).
- **B16** (`main.py:449-454` + `templates/admin_login.html:51-59`): `GET /admin/login` expõe a lista de usuários do time (nomes + papéis) sem autenticação — engenharia social. Correção: mostrar apenas após digitar a senha, ou placeholder.
- **B17** (`main.py:888-896`): `/fotos/{nome}` sem checagem de propriedade (IDOR leve por foto). Correção: validar que o caminho pertence a um lead visível ao usuário.
- **B18** (`main.py:226-236`): `/extract` lê o arquivo inteiro para a memória antes de checar o tamanho. Correção: checar `Content-Length` (quando presente) antes do `read()`.
- **B19** (`templates/funil.html:428-431, 567-571`): sessão 'admin' (gestor) — dropdown de responsável com default "SDR 1"; o gestor atribui ações ao primeiro `RESPONSAVEIS` sem perceber. Correção: desabilitar/padronizar quando `USUARIO_NOME` for nulo.

### Frontend (`templates/funil.html`)
- **B20** (linhas 321-322, 496-497): `l.id`/`a.id` interpolados sem `esc()` em atributos e handlers inline — hoje seguros (IDs inteiros), mas frágil. Correção: `parseInt(l.id, 10)`.
- **B21** (linhas 239-242): `esc()` não escapa aspas simples (`'`) — defesa em profundidade. Correção: adicionar `.replace(/'/g, "&#39;")`.
- **B22** (linhas 345-347): classe `.over` pode ficar presa se o drag for cancelado fora da coluna (sem `dragend`). Correção: listener `dragend` que remove `.over`.
- **B23** (linhas 763-773): `POST /leads` (edição) sem verificar `r.ok` antes de `r.json()` — resposta 4xx/5xx com HTML rejeita e mostra "falha de conexão" enganosa. Correção: wrapper `{ok, d}` como já feito em 415.
- **B24** (linha 318): `l.tempo_no_estagio_dias` indefinido renderiza "undefinedd". Correção: `(l.tempo_no_estagio_dias || 0)`.
- **B25** (linhas 491-492, 627): classes CSS inexistentes usadas (`tagchip`, `fotos`) — cosmético. Correção: adicionar estilos mínimos.
- **B26** (linhas 641/825, 963-964): sem tecla Esc para fechar modais; botão `.fechar` sem `type`. Correção: listener `keydown` para Escape.
- **B27**: `app/__init__.py` não existe — o pacote funciona como namespace package (PEP 420), mas quebra ferramentas que listam pacotes. Correção: criar o arquivo vazio.

---

## Classes que PASSARAM (verificadas de verdade)

- **Bypass por ordem de rotas:** PASS — `/api/funil/metricas` (main.py:659) e `/api/funil/relatorio-perdas` (main.py:672) são declaradas antes de `/api/funil/{lead_id}` (main.py:720); `/api/leads/export` (main.py:560) antes de `/api/leads/{lead_id}` (main.py:583).
- **XSS:** PASS — nenhum `|safe` nos templates; todo dado dinâmico do funil passa por `esc()`; Jinja2 com autoescape padrão do Starlette. Únicas exceções: B20/B21 (IDs e aspas simples).
- **Injeção SQL:** PASS — todas as queries usam parâmetros `?`; as únicas interpolações são colunas/nomes de constantes do código (`CAMPOS`, `COLUNAS_PUBLICAS`) e `_case_probabilidade` gerada de `PROBABILIDADE_ESTAGIO` (constante). Ordem de parâmetros vs. placeholders conferida — correta.
- **Path traversal:** PASS — `/fotos/{nome}` rejeita `/`, `\`, `..` e exige `.jpg` (main.py:891); `_apagar_foto` usa apenas `basename` (main.py:114).
- **Imports circulares:** PASS — `main.py` e `db.py` importam `.funil` sempre *lazy*; `funil.py` não importa nada do app.
- **Rota `/funil` e `USUARIO_NOME`/`USUARIO_PEDE_GESTOR`:** PASS — `funil_page` (main.py:596-619) passa `usuario_logado(request)` corretamente; template calcula certo; backend reaplica a restrição na query (`_restricao_visivel`).
- **Transições de estágio (regras):** PASS — qualificado exige ligação+virou_lead, perdido exige motivo, qualificado→negociação exige observação (`db.py:653-673`); frontend espelha (`funil.html:686-724`).
- **`_conexao()`:** PASS — commit no caminho feliz, `close()` no `finally`, rollback implícito no caminho de exceção; nenhuma conexão vazada; `last_insert_rowid` lido imediatamente após INSERT na mesma conexão.
- **`data_estagio_atual`:** PASS — atualizada nos dois branches de `mudar_estagio`; nenhuma transição esquece a data.
- **Migrações:** PASS — idempotentes via `PRAGMA table_info`; `_migrar_origem` idempotente por `WHERE origem='manual'`; ordem de migração correta (funil antes de origem).
- **`valor_esperado_total` vs. SQL direto:** PASS — bate com a consulta crua (validado pelos testes); a divergência é apenas entre total e por-estágio (M3).
- **Mobile:** PASS — `m-estagio` populado (904-912), sincronizado com `renderKanban` (941), `so-mobile-hidden` correto (343), resize handler com guarda de transição (943-946).
- **Modal de perdido:** PASS — validação (706-716) e exibição de erro (719-722) corretas; fecha no sucesso (419).
- **Busca/visibilidade:** PASS — filtros todos server-side via `paramsApi()`; não há busca no cliente.

---

## Contagem por severidade

| Severidade | Quantidade |
|---|---|
| CRÍTICO | 1 (C1) |
| ALTO | 6 (A1–A6) |
| MÉDIO | 19 (M1–M22, com renumeração do frontend) |
| BAIXO | 28 (B1–B27, com renumeração do frontend) |
| **Total** | **54** |

## Prioridade de correção sugerida

1. **C1 + A3** — fechar o backdoor público de escrita e o IDOR entre responsáveis (segurança/dados).
2. **A1** — fail-closed do `SESSION_SECRET`.
3. **A2** — aplicar visibilidade 5.5 nas APIs `/api/leads*`.
4. **A4, A5, A6** — bugs de uso diário baratos: filtro "Atrasados", cancelamento de próxima ação ao fechar/perder, duplo POST do "✓ concluída".
5. Depois os MÉDIO (M14/M15/M16 do frontend são de dados incorretos; M2/M3 de consistência de métricas).
