# suitecrm-referencia.md — Conceitos do SuiteCRM reescritos para o LeadScan

Material de ESTUDO. O SuiteCRM 7.15.2 é AGPLv3 — este documento é texto
100% original (nenhum trecho de código copiado), produzido a partir da
leitura dos módulos. A pasta `SuiteCRM-7.15.2/` está no `.gitignore` (não é
versionada e não faz parte do produto). Nenhuma alteração de código do
LeadScan foi feita nesta etapa — o que segue são mapeamentos e PROPOSTAS,
que só viram código após revisão, escritos do zero no schema atual do
LeadScan (Python/FastAPI/SQLite + HTML/JS puro).

---

## 1. Mapeamento dos módulos (o que o SuiteCRM faz)

### 1.1 Leads — ciclo de vida, campos e conversão

**Campos (agrupados por tema):**
- Identificação: saudação, primeiro/último nome, nome completo (composto).
- Contato/cargo: cargo, departamento, foto, assistente + telefone do assistente, «não ligar» (flag), vínculo «reporta-se a» (contato/lead hierárquico).
- Telefones/e-mails: comercial, residencial, celular, outro, fax; e-mail principal e secundário; flags de e-mail inválido e de opt-out de campanhas; campos de consentimento (base legal p/ LGPD/GDPR).
- Endereços: primário e alternativo completos (rua, complementos, cidade, estado, CEP, país).
- Empresa: nome da conta (empresa), descrição, id da conta resultante (preenchido na conversão).
- Comercial: nome da oportunidade associada, valor da oportunidade (texto simples), id da oportunidade resultante.
- Ciclo de vida: status, descrição do status, fonte/origem, descrição da fonte, flag convertido, «indicado por» (quem referenciou).
- Marketing: campanha + log de campanha, listas de prospecção. Portal/web: origem de portal.

**Estados (`status`):** Novo, Atribuído, Em Andamento, Convertido, Reciclado, Morto. Transições manuais; salvar sem status preenche «Novo»; a única transição automática é a conversão (status «Convertido»; o lead NÃO é apagado — vira referência histórica).

**Origem (`fonte`):** Ligação fria, Cliente existente, Autogerado, Funcionário, Parceiro, Relações públicas, Mala direta, Conferência, Feira/evento, Site, Indicação, E-mail, Campanha, Outro.

**Conversão de lead (destaque):** página única com uma seção por módulo destino — Contato (OBRIGATÓRIO) e Conta (OBRIGATÓRIO), Oportunidade (opcional), além de Notas/Ligações/Reuniões/Tarefas (opcionais). Cada seção oferece «criar novo» (formulário pré-preenchido com dados do lead) OU «selecionar existente» (busca de duplicata). Ao salvar: cria/liga os registros (Contato e Conta primeiro), herda responsável, aponta a oportunidade para a conta, registra mérito de campanha, marca o lead como Convertido e mostra o resultado (links para o que foi criado). Há checagem de duplicatas embutida. O destino das atividades do lead (copiar/mover/manter) é configurável. O ID do contato criado herda o ID do lead (continuidade de identidade).

**Tela de lista:** colunas padrão = nome (link), status, empresa, telefone comercial, e-mail, responsável, criado em; várias colunas ocultáveis; filtros por nome, «somente meus», «somente abertos», favoritos e busca avançada (nome, e-mail, telefone, endereço, status, fonte, responsável); popover no hover com resumo do lead.

**Tela de detalhe:** 3 abas (Overview: contato/telefones/endereços/descrição · Advanced: status/fonte/valor/indicado por · Assignment: auditoria) + subpainéis Activities (abertas) e History (encerradas) com botões de criar tarefa/agendar ligação/reunião/compor e-mail; faixa de links para os registros criados quando convertido.

**Regras interessantes:** duplicatas verificadas na criação e na conversão; lead convertido continua na lista (filtros podem ocultar); foto copiada para o contato na conversão; atividades legadas rastreadas por id do pai; lead pode nascer de listas de prospecção.

### 1.2 Opportunities — estágios, probabilidade e valor

**Campos:** nome (obrigatório), tipo (Negócio novo / Negócio existente), conta (empresa), campanha, origem do lead, próximo passo (texto curto), descrição; valor (obrigatório, moeda), valor em dólar (computado), moeda; data prevista de fechamento (obrigatória); estágio de venda (obrigatório), probabilidade (% inteiro, 0–100); responsável, auditoria (criado/modificado por), grupos de segurança. Relacionamentos: contas, contatos (com papel na venda — decisor primário/técnico, avaliador, patrocinador, influenciador...), tarefas, ligações, reuniões, e-mails, documentos, leads, projetos, cotações, contratos.

**Estágios e probabilidade (pareados, estágio padrão Prospecting):**

| Estágio | Probabilidade |
|---|---|
| Prospecting (Prospecção) | 10% |
| Qualification (Qualificação) | 20% |
| Needs Analysis (Análise de necessidade) | 25% |
| Value Proposition (Proposta de valor) | 30% |
| Id. Decision Makers (Identificar decisores) | 40% |
| Perception Analysis (Análise de percepção) | 50% |
| Proposal/Price Quote (Proposta/Preço) | 65% |
| Negotiation/Review (Negociação/Revisão) | 80% |
| Closed Won (Fechado ganho) | 100% |
| Closed Lost (Fechado perdido) | 0% |

**Regras de negócio:** a probabilidade é preenchida AUTOMATICAMENTE ao mudar o estágio (mas pode ser sobrescrita manualmente — o valor gravado prevalece); o valor é convertido para a moeda padrão no salvamento (lista sempre mostra o valor normalizado); ganho/perdido são estágios terminais (filtro «apenas abertas» os exclui — é o filtro de pipeline); feed/notificação de oportunidade ganha; detecção de duplicatas na criação + botão localizar duplicatas; auditoria de campos (valor, estágio, probabilidade, datas...).

**Tela de lista:** nome, conta, estágio, valor (formatado, alinhado à direita), data de fechamento, responsável, criado em; filtros: nome, somente meus, APENAS ABERTAS (pipeline), favoritos, valor por faixa, estágio, origem, data de fechamento; popover no hover com origem/probabilidade/próximo passo/descrição. Página «Minhas principais oportunidades abertas» = top 5 por valor.

**Tela de detalhe:** abas; painel principal com valor + data prevista de fechamento, estágio + tipo, probabilidade + origem, próximo passo + campanha, descrição, responsável; subpainéis Activities e History com botões de criar tarefa/ligação/reunião/e-mail.

**Observações de UX:** o estágio e o % andam juntos (mudou o estágio, mudou o % — consistência do funil); a lista normaliza valores entre moedas; a data de fechamento é «esperada» (não hora); o próximo passo é um texto curto de documentação — não há derivação automática a partir de tarefas.

### 1.3 Calls / Meetings / Tasks — registro de atividades

**Ligações (Calls):** assunto (obrigatório), direção (entrada/saída), início/fim (data+hora, início antes do fim), duração (horas+minutos, obrigatória, soma > 0), status (Planejada / Realizada / Não Realizada), vínculo genérico ao registro pai (tipo + id), contato, lembretes (pop-up e/ou e-mail, antecedência de 1min a 1 dia, flag de envio), recorrência, reagendamento. **Como registram resultado:** o STATUS é o mecanismo central — botões «Fechar» (marca Realizada) e «Fechar e criar novo» (realizada + formulário da próxima); **Reagendar** (enquanto não realizada) pede nova data + MOTIVO de lista curta (ex.: fora do escritório, em reunião) e mantém histórico de tentativas + contador. Lista com coluna de ação rápida de fechar. Detalhe com abas (informações / reagendamento / atribuição).

**Reuniões (Meetings):** assunto, status (Planejada/Realizada/Não Realizada), início/fim com validação, duração por lista pronta (15min a 1 semana), local, vínculo ao registro pai, participantes/convidados (usuários + contatos com status de aceite — «Aceitar?»), lembretes, recorrência, integração externa (URLs, provedores de reunião online). UX: botões «Adicionar convidados» e «Salvar e enviar convites»; resultado registrado pelo status.

**Tarefas (Tasks):** assunto, status (Não Iniciada / Em Andamento / Concluída / Aguardando Resposta / Adiada), prioridade (Alta/Média/Baixa), início e vencimento (data+hora, início antes do vencimento, flags «sem data»), vínculo ao registro pai, contato (com telefone/e-mail exibidos na lista). **Relação com «próxima ação»:** a tarefa aberta com vencimento é o mecanismo operacional de follow-up; a Oportunidade tem ainda o campo textual «próximo passo». Ou seja: não existe campo «próxima ação» automático — a prática é criar a tarefa como próximo passo com vencimento.

**Vínculo com Lead/Oportunidade:** cada atividade tem vínculo genérico (tipo+id do pai) e relações específicas muitos-para-muitos. Dentro do Lead/Oportunidade/Contato há dois subpainéis «coleção»: **Atividades** (abertas: reuniões/ligações planejadas + tarefas não concluídas, com botões de criar tarefa/agendar reunião/ligação/compor e-mail) e **Histórico** (encerradas: realizadas, não realizadas, concluídas, adiadas + notas/e-mails). O que está aberto vive em Atividades; ao encerrar migra para o Histórico.

**Regras/UX:** datas com validação de ordem; duração obrigatória na ligação; fechamento rápido com 1 clique (coluna/botão) oculto quando já encerrado; lembretes agendados por job; reagendamento com motivo obrigatório e histórico; auditoria (criado/modificado por).

---

## 2. Comparação com o LeadScan (estado atual)

Referência do lado LeadScan: `app/db.py` (leads + funil + lead_cartao + historico_estagios + lead_atividades), `app/funil.py` (6 estágios, RESPONSAVEIS, MOTIVOS_PERDA, TIPOS_ATIVIDADE), `docs/UX_FUNIL.md` (UX da tela), `docs/funil_implement_v2.md` (R1 pronta, R2 frontend).

### 2.1 O que o SuiteCRM tem e o LeadScan NÃO tem (candidatos a considerar)

| Conceito | Onde está no SuiteCRM | Situação no LeadScan |
|---|---|---|
| Probabilidade automática por estágio | Opportunities (sales_stage + probability) | **Não tem** — seria novo sinal de prioridade + base p/ pipeline |
| Valor/valor esperado (valor × prob.) | Opportunities (amount, amount_usdollar) | **Não tem** — depende de decisão de produto |
| Filtro «apenas abertas» (pipeline) | Opportunities (open_only) | Não tem como atalho único (filtra por estágio individual) |
| Motivo + histórico de ligação não realizada (reagendamento, contador de tentativas) | Calls (Reschedule) | **Não tem** — só «feita/virou lead/obs»; não distingue «não atendeu» de «recusou» |
| Detecção de duplicatas na criação | Leads/Opportunities | **Não tem** — risco de cartão repetido virar 2 leads |
| Separação «Atividades abertas × Histórico» | Subpanels ForActivities/ForHistory | Parcial — timeline única (lead_atividades); o conceito de coleções separadas pode ser adotado na UI |
| Auditoria de campos editados (valor anterior/novo) | Flag auditable | **Não tem** — só histórico de estágio/atividades |
| Tarefa como follow-up com prioridade + 5 estados | Tasks | Parcial — próxima ação única com data (mais simples; cobre o essencial) |
| Popover no hover da lista | Leads/Opportunities (additionalDetails) | Não tem — desktop-only; o UX doc prefere card autoexplicativo |
| «Indicado por» (referral) | Leads (refered_by) | **Não tem** — indicação é fonte valiosa p/ venda |
| Papel do contato na venda (decisor/avaliador...) | Opportunities (contact_role) | Não tem — sem multi-contato no modelo atual |
| Status terminais com vocabulário próprio (Reciclado/Morto) | Leads (lead_status_dom) | Parcial — LeadScan tem perdido + reabertura (equivale a Reciclado) |

### 2.2 O que NÃO se aplica ao LeadScan

- **Módulo Contas/Contatos/Casos/Contratos/Cotações/Projetos**: modelo multi-entidade — o LeadScan é lead-único (item 40 da spec: um Lead continua sendo a entidade principal).
- **Multi-moeda e conversão para dólar**: LeadScan é BRL, sem necessidade de normalização de moeda.
- **Campanhas, e-mail marketing, opt-out, listas de prospecção, portal**: fora do escopo do produto.
- **Reuniões com convidados, aceite, recorrência, integração de reunião online, calendário**: o time usa WhatsApp/telefone no celular — sem agenda/convite.
- **ACL/perfis/usuários, grupos de segurança, favoritos, feed de atividades, notificações por e-mail**: LeadScan tem login único compartilhado (item 41) — nada de permissão por pessoa.
- **Conversão Lead → Contato+Conta+Oportunidade (multi-registro)**: a conversão no LeadScan é a QUALIFICAÇÃO (um estágio), não a criação de novos registros — o modelo inteiro de beans não se aplica.
- **Full-text search, importação em massa, vCard, merge de duplicados**: fora do escopo (export CSV já existe).
- **Lembretes agendados (pop-up/e-mail por job)**: sem push no LeadScan; o WhatsApp-first torna lembretes de e-mail irrelevantes.

### 2.3 Onde o LeadScan já resolve melhor para o caso de uso dele

- **Captura por foto → OCR/IA → WhatsApp**: não existe no SuiteCRM (é o coração do LeadScan, itens 1/44).
- **Funil com regras de negócio no backend**: qualificação exige ligação + virou lead; perdido exige motivo; histórico obrigatório (itens 6/58) — o SuiteCRM tem estágios livres sem regras.
- **Próxima ação com data + filtros «atrasados» e «retorno hoje»**: não existe no SuiteCRM (o «próximo passo» é texto solto; tarefas têm vencimento mas sem o conceito de retorno do dia).
- **Timeline comercial unificada** (lead_atividades com tipos padronizados) em 1 tela mobile-first — o SuiteCRM separa Atividades/Histórico em subpainéis pesados.
- **Métricas de tempo por estágio** (tempo médio qualificação/negociação/fechamento): o SuiteCRM não calcula isso nativamente.
- **Origem simplificada (cartão/manual)**: 2 valores claros vs 15 fontes — menos atrito de preenchimento para BDR/SDR.
- **Reabertura preservando motivo** (itens 29/30): o SuiteCRM mantém o lead convertido como referência, mas o fluxo de voltar perdido ao funil com histórico é mais direto no LeadScan.

---

## 3. Propostas (avaliar antes de virar código)

Cada proposta: **conceito** (uma frase) · **de onde veio** · **vale a pena?** · **como ficaria reescrito no schema SQLite atual** (sem nada copiado do SuiteCRM).

### P1 — Probabilidade por estágio (RECOMENDADA, baixo custo)
- **Conceito**: cada estágio do funil tem um % de chance de fechamento; mudar o estágio preenche o % automaticamente; o card mostra o % como sinal de prioridade.
- **De onde veio**: Opportunities (estágio + probabilidade pareados, preenchimento automático).
- **Vale a pena?** Sim — custo baixo, encaixa na «1 cor de atenção» do UX doc e cria a base para pipeline/valor esperado (P2) depois.
- **Como ficaria**: constantes em `app/funil.py`: `PROBABILIDADE_ESTAGIO = {novo: 10, ligacao_feita: 20, qualificado: 40, negociacao: 70, fechado: 100, perdido: 0}`; coluna `probabilidade INTEGER NOT NULL DEFAULT 10` em `FUNIL_COLUNAS` (migração idempotente); `mudar_estagio` grava o % do estágio destino; card/detalhe exibem «40%» (rotulagem do UX: «chance de fechar»).

### P2 — Valor estimado + valor esperado (OPCIONAL — decisão de produto)
- **Conceito**: campo monetário opcional por lead; valor esperado = valor × probabilidade; soma por estágio = pipeline.
- **De onde veio**: Opportunities (amount + probability; lista normaliza valor).
- **Vale a pena?** Só se o time declarar valor por negócio (mensalidade já existe nos campos — pode ser a base). Sem multi-moeda. **Decisão**: adotar como opt-in, não obrigatório.
- **Como ficaria**: coluna `valor_estimado TEXT NOT NULL DEFAULT ''` (numérico simples) em leads; no detalhe/card, se preenchido: «valor estimado: R$ X · chance 40% · esperado R$ Y»; métrica opcional `pipeline_estimado` = soma(valor × prob/100) dos abertos.

### P3 — Acompanhamento separado em «Em aberto × Histórico» (RECOMENDADA — encaixa na R2)
- **Conceito**: no detalhe do lead, coleções distintas: o que está aberto (próxima ação agendada, ligação pendente) vs o histórico encerrado.
- **De onde veio**: subpanels Atividades × Histórico (Calls/Meetings/Tasks/Leads/Opportunities).
- **Vale a pena?** Sim — combina com o UX doc (próxima ação como convite, timeline no fim) e não exige mudança de banco.
- **Como ficaria**: sem coluna nova — na UI (R2), `lead_atividades` é classificada: «Em aberto» = tipo `proxima_acao` com data futura/não concluída (+ ligação `feita=false`); «Histórico» = demais. Se quiser reforço no banco depois, flag `concluida INTEGER DEFAULT 0` na tabela (P7).

### P4 — Resultado da ligação não atendida + contador de tentativas (RECOMENDADA — melhora o filtro «Sem contato»)
- **Conceito**: ao registrar ligação não realizada, escolher o resultado (não atendeu / ocupado / caiu caixa postal / recusou) e contar tentativas por lead.
- **De onde veio**: Calls — reagendamento com motivo obrigatório + histórico/contador de tentativas.
- **Vale a pena?** Sim para o BDR — distingue «nunca tentei» de «tentei e não consegui» (o filtro «Sem contato» atual mistura os dois) e padroniza o motivo.
- **Como ficaria**: colunas `ligacao_tentativas INTEGER NOT NULL DEFAULT 0` e `ligacao_ultimo_resultado TEXT NOT NULL DEFAULT ''`; `POST /ligacao` aceita `resultado` quando `feita=false` (constantes `RESULTADOS_LIGACAO` em `app/funil.py`); atividade registra «ligação não realizada — não atendeu»; filtro opcional «tentado sem sucesso».

### P5 — Detecção de duplicatas na criação (RECOMENDADA — baixo custo, dados limpos)
- **Conceito**: ao salvar um lead (captura ou manual), verificar se já existe outro com o mesmo WhatsApp/e-mail/empresa+contato e pedir confirmação antes de criar.
- **De onde veio**: Leads/Opportunities — checagem automática de duplicatas na criação/conversão + Find Duplicates.
- **Vale a pena?** Sim — o mesmo cartão fotografado duas vezes não deve virar dois leads; combina com o item 53 (confirmações) e o UX doc (não quebrar o fluxo).
- **Como ficaria**: sem coluna nova — em `POST /leads`, antes de salvar, buscar `whatsapp`/`email`/`nome_empresa+nome_contato` normalizados; resposta ganha `possiveis_duplicatas: [{id, nome_empresa, nome_contato, whatsapp}]`; o frontend mostra «Já existe um lead parecido — continuar mesmo assim?».

### P6 — Distinguir perdido «morto» de «recuperável» (NÃO RECOMENDADA)
- **Conceito**: status terminal com flag de recuperável (Reciclado = pode voltar; Morto = definitivo).
- **De onde veio**: Leads (`status` Dead / Recycled).
- **Vale a pena?** Não — o LeadScan já reabre perdido preservando motivo e histórico (itens 29/30), o que cobre o caso «reciclado»; a flag de «morto definitivo» seria mais um campo sem retorno claro.
- **Como ficaria**: n/a — registrar a decisão de não implementar.

### P7 — Auditoria de campos editados (ADIAR)
- **Conceito**: guardar valor anterior/novo de cada campo editado nos dados do lead.
- **De onde veio**: flag auditable (Lead/Opportunity — estágio, valor, probabilidade, datas...).
- **Vale a pena?** Opcional — útil para responsabilidade (quem editou o quê), mas custo médio e baixa urgência para o time. Adiar para depois da R2.
- **Como ficaria**: tabela `auditoria_campos (id, lead_id, campo, valor_anterior, valor_novo, data_hora, responsavel)`; escrita em `atualizar_lead` quando o valor muda; exibição em aba «Auditoria» no detalhe.

### P8 — «Próximo passo» como texto curto (JÁ COBERTO — não implementar)
- **Conceito**: campo textual de próxima etapa na oportunidade.
- **De onde veio**: Opportunities (`next_step`).
- **Vale a pena?** Não como item novo — o LeadScan já tem `proxima_acao` + `data_proxima_acao` (estruturado, com filtros atrasados/retorno hoje), o que é melhor que texto solto.
- **Como ficaria**: n/a — registrar como já resolvido.

### P9 — Atalho de filtro «Pipeline» (apenas abertos) (RECOMENDADA — trivial)
- **Conceito**: botão/filtro que mostra tudo exceto Fechado e Perdido, com contador.
- **De onde veio**: Opportunities (`open_only`).
- **Vale a pena?** Sim — 1 parâmetro no backend + 1 chip no frontend; complementa os presets BDR/SDR do UX doc.
- **Como ficaria**: `listar_funil(aberto_only=True)` → `AND estagio NOT IN ('fechado','perdido')`; chip «🔓 Pipeline» no frontend (R2).

### P10 — Lembretes, recorrência, convidados, campanhas, multi-moeda, ACL (NÃO SE APLICA)
- Documentado em 2.2 — não entrar no roadmap.

---

## 4. Recomendação de prioridade

| Prioridade | Itens | Quando |
|---|---|---|
| Adotar | P1 (probabilidade), P3 (aberto×histórico), P4 (resultado de ligação), P5 (duplicatas), P9 (pipeline) | R2 em diante, após revisão deste documento |
| Avaliar | P2 (valor estimado), P7 (auditoria de campos) | Sprints seguintes, com decisão de produto |
| Não implementar | P6 (morto/recuperável), P8 (próximo passo), P10 (fora de escopo) | — |

Próximo passo: revisar este documento (principalmente P1/P4/P5, que mexem em banco/backend) antes de qualquer código.
