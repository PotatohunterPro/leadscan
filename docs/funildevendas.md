Você é o engenheiro principal responsável por transformar o projeto:

PotatohunterPro/leadscan

em uma ferramenta operacional de coleta e acompanhamento comercial.

============================================================
VISÃO DO PRODUTO
============================================================

O LeadScan começou como uma ferramenta de captura de cartões de visita.

Hoje ele:

- recebe foto do cartão;
- usa OCR/IA local;
- extrai informações;
- guarda o lead;
- possui formulário para coleta manual;
- possui informações extraídas do cartão;
- permite envio de foto + texto para WhatsApp.

Agora o produto deve evoluir para:

CAPTURA + COLETA + QUALIFICAÇÃO + FUNIL + ACOMPANHAMENTO

O objetivo NÃO é criar um CRM complexo.

O objetivo é criar uma ferramenta simples, rápida e prática para uso diário de uma equipe comercial.

============================================================
DECISÃO DE PRODUTO
============================================================

Existe UMA única conta de acesso compartilhada pelo time.

NÃO criar:

- login individual;
- usuário por SDR;
- cadastro de usuários;
- permissões por pessoa;
- RBAC;
- gestão de usuários;
- perfil individual;
- troca de senha por usuário.

Existe apenas:

LOGIN ÚNICO DA EQUIPE

A senha pode continuar sendo armazenada em variável de ambiente/configuração segura.

============================================================
IMPORTANTE SOBRE ADMIN
============================================================

NÃO criar um painel administrativo.

NÃO usar /admin como interface comercial.

A aplicação deve ter uma tela operacional:

/funil

ou:

/leads

Essa é a tela principal do time.

A interface deve ser feita para uso diário pela SDR/vendedor.

O usuário não deve precisar saber nada sobre:

- Ollama;
- Docker;
- banco;
- configuração;
- modelo;
- servidor;
- infraestrutura.

Essas informações são técnicas e não pertencem à interface comercial.

============================================================
1. PRESERVAR O QUE JÁ FUNCIONA
============================================================

NÃO quebrar o fluxo atual:

FOTO
↓
OCR/IA
↓
INFORMAÇÕES DO CARTÃO
↓
DADOS DO LEAD
↓
WHATSAPP

A camada de funil será adicionada SOBRE esse fluxo.

O LeadScan deve continuar permitindo:

- captura de cartão;
- frente;
- verso;
- OCR;
- IA;
- dados do formulário;
- informações do cartão;
- envio para WhatsApp.

============================================================
2. DADOS DO LEAD
============================================================

Manter TODOS os campos existentes.

Os campos atuais pertencem à coleta comercial.

Eles são preenchidos pelo vendedor.

Não remover.

Não substituir.

Não simplificar.

Manter, no mínimo:

Nome da Loja / Fantasia

Endereço / Bairro / Cidade

Nome do Contato

Cargo

WhatsApp do Contato

Aceita demonstração?

Anotações / Dor principal do cliente

Telefone fixo / loja

E-mail da loja

Segmento

Possui sistema?

Qual sistema?

Mensalidade

Suporte é bom?

Trocaria por melhor suporte?

Trocaria por melhor preço?

Qualquer outro campo existente deve ser preservado.

============================================================
3. INFORMAÇÕES DO CARTÃO
============================================================

Continuar utilizando uma área separada:

📇 INFORMAÇÕES DO CARTÃO

Ela pertence ao mesmo Lead.

Ela representa os dados encontrados nas fotos.

Pode conter:

empresa

nome fantasia

nome de contato

cargo

telefones

WhatsApps

e-mail

endereço

logradouro

número

complemento

bairro

cidade

UF

CEP

site

redes sociais

outras informações

OCR bruto

imagem da frente

imagem do verso

metadados da extração

A IA NÃO pode substituir os dados manuais.

============================================================
4. NOVA CAMADA: FUNIL
============================================================

Adicionar acompanhamento comercial ao mesmo Lead.

Estágios padrão:

1. Novo
2. Ligação feita
3. Qualificado
4. Em negociação
5. Fechado
6. Perdido

Esses estágios devem ser configurados em código/backend.

NÃO criar tela de administração de estágios.

============================================================
5. SIGNIFICADO DOS ESTÁGIOS
============================================================

NOVO

Lead acabou de ser capturado/criado e ainda não houve contato comercial.

LIGAÇÃO FEITA

A SDR fez uma ligação.

QUALIFICADO

A SDR confirmou que existe potencial comercial real.

EM NEGOCIAÇÃO

Existe proposta, condição comercial, negociação ou intenção clara de compra.

FECHADO

Virou cliente.

PERDIDO

Foi desqualificado, recusou ou não seguirá.

============================================================
6. REGRA DE QUALIFICAÇÃO
============================================================

Um lead só pode entrar em:

QUALIFICADO

quando:

ligacao.feita = true

E:

ligacao.virou_lead = true

Se a ligação foi feita e:

virou_lead = false

o usuário deve poder enviar o lead para:

PERDIDO

com motivo obrigatório.

============================================================
7. NOVA TELA PRINCIPAL
============================================================

Criar:

/funil

Essa será a tela principal do time.

Pode existir:

/

redirecionando para /funil

caso faça sentido.

Não exigir navegação por painel administrativo.

============================================================
8. KANBAN
============================================================

A tela principal deve ser um Kanban.

Colunas:

NOVO

LIGAÇÃO FEITA

QUALIFICADO

EM NEGOCIAÇÃO

FECHADO

PERDIDO

Cada coluna deve mostrar contador:

NOVO
12

LIGAÇÃO FEITA
8

QUALIFICADO
6

etc.

============================================================
9. CARD DO LEAD NO KANBAN
============================================================

Cada card deve mostrar:

Nome da empresa

Nome do contato

WhatsApp

Segmento

Responsável

Tempo no estágio atual

Próxima ação

Data da próxima ação

Indicador de cartão disponível

Exemplo:

┌─────────────────────────────┐
│ 📇 ARTE & TEAR              │
│ Carlos — Proprietário      │
│                             │
│ 📱 (16) 99726-9098          │
│ 🏷 Varejo                   │
│                             │
│ 👤 Responsável: João        │
│                             │
│ ⏱ 2 dias neste estágio      │
│ 🔔 Retorno: amanhã          │
└─────────────────────────────┘

Não mostrar excesso de informações no card.

O card deve ser visualmente compacto.

============================================================
10. TEMPO NO ESTÁGIO
============================================================

Mostrar quanto tempo o lead está no estágio atual.

Exemplo:

Hoje

1 dia

3 dias

7 dias

12 dias

Destacar visualmente leads parados por muito tempo.

Sugestão:

> 3 dias = normal

> 7 dias = atenção

> 14 dias = estagnado

Esses valores devem ser constantes configuráveis no código.

Não criar configuração administrativa.

============================================================
11. DRAG AND DROP
============================================================

Permitir mover leads entre colunas por drag-and-drop.

Ao mover:

registrar mudança de estágio.

Atualizar:

estagio_atual

data_estagio_atual

registrar histórico.

IMPORTANTE:

Mover por drag-and-drop NÃO pode ignorar regras de negócio.

Exemplo:

Não permitir:

Novo → Qualificado

sem:

ligacao.feita = true

e:

ligacao.virou_lead = true

Se tentativa inválida:

mostrar mensagem clara.

============================================================
12. SUPORTE MOBILE
============================================================

A aplicação será usada em:

celular

tablet

notebook

Portanto:

Kanban desktop:

colunas lado a lado.

Mobile:

scroll horizontal.

Os cards devem continuar legíveis.

Não obrigar o usuário a usar desktop.

Também deve existir uma forma alternativa de mudar estágio:

"Alterar estágio"

no detalhe do lead.

Isso é importante para celular.

============================================================
13. DETALHE DO LEAD
============================================================

Ao clicar em um card:

abrir detalhe do Lead.

O detalhe deve mostrar claramente três grandes grupos:

-----------------------------------------------
👤 DADOS DO LEAD
-----------------------------------------------

Informações coletadas pelo vendedor.

-----------------------------------------------
📇 INFORMAÇÕES DO CARTÃO
-----------------------------------------------

Informações extraídas da foto.

-----------------------------------------------
📊 ACOMPANHAMENTO COMERCIAL
-----------------------------------------------

Informações do funil.

============================================================
14. DADOS DO LEAD NO DETALHE
============================================================

Mostrar todos os campos existentes.

O usuário deve conseguir editar.

Não ocultar campos importantes.

Manter a lógica atual.

============================================================
15. INFORMAÇÕES DO CARTÃO NO DETALHE
============================================================

Mostrar:

empresa

contatos

telefones

WhatsApps

e-mail

endereço

CEP

site

redes sociais

outras informações

frente

verso

texto OCR

Mostrar:

🤖 Extraído do cartão

Nunca misturar visualmente com os dados manuais.

============================================================
16. ACOMPANHAMENTO COMERCIAL
============================================================

Mostrar:

Estágio atual

Responsável

Data em que entrou no estágio

Tempo no estágio

Data da última interação

Próxima ação

Data da próxima ação

============================================================
17. RESPONSÁVEL
============================================================

Apesar de existir apenas UM LOGIN compartilhado:

o lead pode possuir:

responsavel_atual

Esse campo representa a pessoa da equipe que está cuidando do lead.

Não implementar contas individuais.

O responsável pode ser um texto simples.

Exemplo:

João

Maria

Wellington

Carlos

A interface pode permitir selecionar um responsável a partir de uma lista fixa/configurada no código ou permitir texto.

Não criar autenticação individual.

============================================================
18. ORIGEM DO LEAD
============================================================

Adicionar:

origem

Possíveis valores:

cartao

manual

Não confundir origem com informações do cartão.

Um lead manual pode posteriormente receber um cartão.

Portanto:

origem = manual

não significa:

sem cartão.

============================================================
19. LIGAÇÃO
============================================================

Adicionar área:

📞 REGISTRAR LIGAÇÃO

Botão:

[ Registrar ligação ]

Ao clicar:

Data/hora:
preencher automaticamente com agora, permitindo alteração.

Ligação realizada:
Sim

Virou lead:
Sim / Não

Observação:
campo livre

Salvar.

Ao registrar:

ligacao.feita = true

ligacao.data_ligacao = timestamp

ligacao.virou_lead = true/false

ligacao.observacao = texto

Adicionar atividade no histórico.

============================================================
20. LIGAÇÃO NÃO VIROU LEAD
============================================================

Se:

virou_lead = não

permitir:

Mover para Perdido

e pedir:

Motivo da perda

Esse motivo é obrigatório.

Exemplos:

Sem interesse

Já possui solução

Preço

Sem orçamento

Sem necessidade

Concorrente

Contato inválido

Outro

Pode existir um select com "Outro" + campo livre.

============================================================
21. PRÓXIMA AÇÃO
============================================================

Adicionar ao acompanhamento:

Próxima ação

Exemplos:

Ligar

Enviar WhatsApp

Retornar ligação

Enviar proposta

Apresentar sistema

Fazer demonstração

Aguardar cliente

Outro

E:

Data da próxima ação

E:

Observação da próxima ação

============================================================
22. ÚLTIMA INTERAÇÃO
============================================================

Guardar:

data_ultima_interacao

Atualizar quando ocorrer:

ligação

WhatsApp registrado

mudança de estágio

observação comercial relevante

proposta enviada

outra atividade comercial

============================================================
23. HISTÓRICO
============================================================

Não criar apenas histórico de estágios.

Criar um histórico comercial geral.

Exemplo:

02/09 09:20
📞 Ligação
"Falou com Carlos. Gostou da apresentação."

02/09 09:30
➡ Estágio alterado
Novo → Ligação feita

02/09 09:40
➡ Estágio alterado
Ligação feita → Qualificado

04/09 14:10
💬 WhatsApp
"Enviei apresentação."

05/09 08:00
📋 Proposta enviada

07/09 16:30
➡ Estágio alterado
Em negociação → Fechado

O histórico deve possuir:

id

lead_id

tipo

data_hora

descricao

usuario_responsavel

estagio_anterior

estagio_novo

============================================================
24. TIPOS DE ATIVIDADE
============================================================

Criar tipos padronizados:

estagio

ligacao

whatsapp

email

proposta

observacao

proxima_acao

outro

Não precisa implementar integração de e-mail.

É apenas classificação da atividade.

============================================================
25. OBSERVAÇÃO RÁPIDA
============================================================

No detalhe do lead:

[ + Registrar interação ]

Abrir formulário simples:

Tipo:

Ligação
WhatsApp
E-mail
Proposta
Observação
Outro

Descrição:

[........................]

Salvar.

Isso entra no histórico.

============================================================
26. MUDANÇA DE ESTÁGIO
============================================================

Ao mudar estágio:

registrar:

estagio_anterior

estagio_novo

data_hora

responsável

observação opcional

Atualizar:

estagio_atual

data_estagio_atual

data_ultima_interacao

============================================================
27. FECHADO
============================================================

Quando entrar em:

FECHADO

registrar histórico:

✅ Lead fechado

Permitir observação:

"Cliente contratou sistema X."

Não exigir burocracia.

============================================================
28. PERDIDO
============================================================

Ao mover para:

PERDIDO

abrir modal:

Motivo da perda:

[ obrigatório ]

Observação:

[ opcional ]

Não permitir salvar Perdido sem motivo.

============================================================
29. REABRIR LEAD PERDIDO
============================================================

Permitir mudar um lead perdido de volta para o funil.

Exemplo:

Perdido → Qualificado

Nesse caso:

registrar histórico.

Manter o motivo original da perda.

Não apagar o histórico antigo.

============================================================
30. FECHADO TAMBÉM PODE SER REABERTO
============================================================

Permitir reabrir um lead fechado quando necessário.

Registrar no histórico.

Não apagar o fechamento anterior.

============================================================
31. FILTROS
============================================================

Na tela /funil:

Busca:

Empresa

Contato

WhatsApp

Telefone

E-mail

Filtros:

Estágio

Responsável

Origem

Período de captura

Próxima ação

Leads atrasados

Leads sem contato

============================================================
32. FILTRO "SEM CONTATO"
============================================================

Criar filtro:

Sem contato

Mostra leads onde:

ligacao.feita = false

============================================================
33. FILTRO "ATRASADOS"
============================================================

Criar filtro:

Atrasados

Mostra leads onde:

data_proxima_acao < agora

e lead não está:

Fechado

nem:

Perdido

============================================================
34. FILTRO "RETORNO HOJE"
============================================================

Criar:

Retorno hoje

Mostra leads cuja:

data_proxima_acao

é hoje.

Isso deve ser útil para a SDR começar o dia.

============================================================
35. MÉTRICAS NO TOPO
============================================================

Não criar dashboard separado.

Mostrar pequenas métricas no topo da própria tela.

Exemplo:

TOTAL
42

NOVOS
12

QUALIFICADOS
8

NEGOCIAÇÃO
6

FECHADOS
3

PERDIDOS
5

Esses números devem respeitar os filtros aplicados quando fizer sentido.

============================================================
36. CONVERSÃO
============================================================

Mostrar:

Taxa de conversão

=

Fechados / Leads capturados

No período selecionado.

Não complicar a fórmula.

Mostrar de forma simples:

Conversão:
7,1%

============================================================
37. TEMPO MÉDIO
============================================================

Mostrar métricas leves:

Tempo médio até qualificação

Tempo médio em negociação

Tempo médio até fechamento

Pode ser mostrado em:

dias

horas quando apropriado.

Não criar gráficos complexos.

============================================================
38. BANCO DE DADOS
============================================================

ATENÇÃO:

Não transformar tudo em JSON.

O projeto atual usa SQLite.

MANTER SQLite.

MANTER Python/FastAPI.

Não trocar para PostgreSQL simplesmente porque agora existe um funil.

O projeto continua pequeno e de uso interno.

Criar tabelas relacionais adicionais.

Sugestão:

leads
  id
  ...
  estagio_atual
  data_estagio_atual
  responsavel_atual
  origem
  data_ultima_interacao
  data_proxima_acao
  proxima_acao
  ...

lead_ligacoes

lead_atividades

lead_estagio_historico

Mas antes de implementar:

analise o schema atual.

Escolha a menor alteração necessária.

NÃO apagar dados existentes.

============================================================
39. ESTRUTURA RECOMENDADA
============================================================

Pode utilizar algo semelhante:

ALTER TABLE leads ADD COLUMN estagio_atual TEXT NOT NULL DEFAULT 'novo';

ALTER TABLE leads ADD COLUMN data_estagio_atual TEXT;

ALTER TABLE leads ADD COLUMN responsavel_atual TEXT NOT NULL DEFAULT '';

ALTER TABLE leads ADD COLUMN origem TEXT NOT NULL DEFAULT 'manual';

ALTER TABLE leads ADD COLUMN data_ultima_interacao TEXT;

ALTER TABLE leads ADD COLUMN data_proxima_acao TEXT;

ALTER TABLE leads ADD COLUMN proxima_acao TEXT NOT NULL DEFAULT '';

ALTER TABLE leads ADD COLUMN proxima_acao_observacao TEXT NOT NULL DEFAULT '';

Tabela:

lead_ligacoes

id
lead_id
feita
data_ligacao
virou_lead
observacao
criado_em

Tabela:

lead_atividades

id
lead_id
tipo
descricao
data_hora
responsavel

Tabela:

lead_estagio_historico

id
lead_id
estagio_anterior
estagio_novo
data_hora
responsavel
observacao

Usar foreign keys.

Ativar foreign_keys no SQLite.

============================================================
40. NÃO DUPLICAR INFORMAÇÃO DESNECESSARIAMENTE
============================================================

Não criar outra tabela de clientes.

Não criar outra tabela de empresas.

Não criar outro CRM.

Um Lead continua sendo a entidade principal.

O cartão continua em:

lead_cartao

O funil aponta para:

lead_id

============================================================
41. AUTENTICAÇÃO
============================================================

NÃO criar autenticação por usuário.

Existe:

1 login compartilhado.

Fluxo:

/login

usuário informa:

senha

Se correto:

criar sessão.

Depois:

/funil

deve estar protegido.

O login pode utilizar o mecanismo de sessão já existente.

Não criar:

/admin

Não criar:

/users

Não criar:

/roles

Não criar:

/permissions

============================================================
42. ROTA PRINCIPAL
============================================================

Sugestão:

/login

/funil

/leads

/leads/{id}

Mas não criar excesso de páginas.

A experiência deve parecer uma única aplicação.

============================================================
43. TELA DE LEAD
============================================================

O detalhe pode ser modal/drawer ou página.

Escolher a solução que funcione melhor em:

desktop

tablet

celular.

Preferência:

desktop:
drawer lateral ou página dedicada.

mobile:
página dedicada ou modal adaptado.

============================================================
44. AÇÃO DE WHATSAPP
============================================================

Preservar o fluxo atual:

foto + texto → WhatsApp.

No detalhe do Lead:

botão:

📲 WhatsApp

deve continuar funcionando.

Pode reutilizar o mesmo mecanismo existente.

Não quebrar.

============================================================
45. AÇÃO DE LIGAÇÃO
============================================================

Quando houver WhatsApp/telefone:

permitir ação rápida:

📞 Ligar

Em celular usar:

tel:

Quando houver WhatsApp:

📲 WhatsApp

Não é necessário integrar API do WhatsApp.

Usar os recursos existentes.

============================================================
46. DADOS DO CARTÃO NO KANBAN
============================================================

O card do Kanban pode indicar:

📇 cartão

quando o lead possui cartão.

Não colocar todos os dados do cartão no card.

No detalhe, mostrar tudo.

============================================================
47. LEADS MANUAIS
============================================================

Criar lead manualmente deve continuar sendo possível.

Ao criar manualmente:

origem = manual

estagio = novo

Se posteriormente o usuário fotografar cartão:

adicionar lead_cartao.

NÃO criar novo lead.

============================================================
48. LEADS COM CARTÃO
============================================================

Quando um cartão for capturado:

criar:

lead

+

lead_cartao

+

estagio = novo

+

origem = cartao

Esse lead entra automaticamente no Kanban.

============================================================
49. IMPORTANTE: CARTÃO E DADOS MANUAIS
============================================================

Nunca misturar.

No detalhe:

👤 DADOS DO LEAD

e:

📇 INFORMAÇÕES DO CARTÃO

devem continuar independentes.

A IA não altera o conteúdo manual.

============================================================
50. FORMULÁRIO DE NOVO LEAD
============================================================

Além da captura por cartão:

deve existir:

[ + Novo Lead ]

Permitir cadastro manual.

Campos:

Nome da empresa

Nome do contato

WhatsApp

Telefone

E-mail

Endereço

Segmento

Observação

e demais campos existentes.

Depois o usuário pode completar os demais campos.

============================================================
51. UX DA SDR
============================================================

Pensar como ferramenta diária.

A SDR deve conseguir:

1. Abrir /funil.
2. Ver quem precisa de contato.
3. Abrir o lead.
4. Ligar.
5. Registrar ligação.
6. Marcar se virou lead.
7. Qualificar.
8. Definir próxima ação.
9. Fazer follow-up.
10. Registrar negociação.
11. Fechar ou perder.

Tudo deve exigir poucos cliques.

============================================================
52. ESTADOS VAZIOS
============================================================

Cada coluna deve ter estado vazio amigável.

Exemplo:

Nenhum lead novo.

Isso é melhor que tabela vazia.

============================================================
53. CONFIRMAÇÕES
============================================================

Não pedir confirmação para ações triviais.

Mas pedir confirmação quando:

- marcar como perdido;
- substituir informação manual;
- fechar lead;
- excluir alguma atividade, se exclusão existir.

Evitar excesso de modais.

============================================================
54. EXCLUSÃO
============================================================

Não criar exclusão de lead inicialmente.

Preferir preservar histórico.

Se existir exclusão atual:

analisar antes de remover.

Não apagar silenciosamente leads.

============================================================
55. PERFORMANCE
============================================================

Kanban pode mostrar muitos leads.

Não carregar informações pesadas desnecessariamente.

Não carregar OCR completo no card.

Não carregar imagens em tamanho grande no Kanban.

Usar miniaturas.

Detalhe pode carregar:

foto

OCR

informações completas.

============================================================
56. API
============================================================

Criar endpoints simples e claros.

Exemplo:

GET /funil

GET /api/funil/leads

GET /api/leads/{id}

POST /api/leads

PATCH /api/leads/{id}

POST /api/leads/{id}/estagio

POST /api/leads/{id}/ligacao

POST /api/leads/{id}/atividade

POST /api/leads/{id}/proxima-acao

GET /api/funil/metricas

Escolher rotas compatíveis com o projeto atual.

Não quebrar os endpoints existentes.

============================================================
57. DRAG AND DROP API
============================================================

Ao soltar:

PATCH /api/leads/{id}/estagio

payload:

{
  "estagio": "qualificado"
}

Backend deve validar.

Não confiar na validação do frontend.

============================================================
58. REGRAS NO BACKEND
============================================================

Todas as regras críticas devem ser aplicadas no backend.

Nunca depender apenas do JavaScript.

Exemplos:

Novo → Qualificado:

bloquear se ligação não feita.

Qualificado:

bloquear se ligação não virou lead.

Perdido:

motivo obrigatório.

Registrar histórico:

obrigatório.

============================================================
59. CONSISTÊNCIA
============================================================

Mudança de estágio deve ser transacional.

Na mesma operação:

1. atualizar lead;
2. atualizar data;
3. criar histórico;
4. atualizar última interação.

Ou nenhuma mudança deve persistir.

Usar transação SQLite.

============================================================
60. HISTÓRICO NÃO DEVE SER APAGADO
============================================================

Nunca apagar histórico quando:

- mudar estágio;
- reabrir lead;
- fechar novamente;
- perder novamente.

O histórico é cumulativo.

============================================================
61. COMPATIBILIDADE COM LEADS EXISTENTES
============================================================

Leads antigos devem automaticamente receber:

estagio = novo

se não tiverem estágio.

Não perder informação existente.

Não exigir que o usuário faça migração manual.

============================================================
62. MIGRAÇÃO
============================================================

Criar migração idempotente.

Pode usar:

PRAGMA table_info

para verificar colunas.

Não executar:

DROP TABLE

Não recriar o banco do zero.

Não apagar:

leads

lead_cartao

fotos

============================================================
63. TECNOLOGIA
============================================================

ANTES DE TROCAR A STACK:

analise o projeto atual.

A princípio:

MANTER:

Python

FastAPI

SQLite

HTML/CSS/JavaScript

Ollama

LFM2.5-VL-450M

Pillow

Tesseract/OCR, caso já tenha sido implementado.

NÃO introduzir um framework frontend pesado sem necessidade.

NÃO adicionar React/Vue/Angular apenas para fazer Kanban.

Preferir JavaScript existente.

============================================================
64. MEMÓRIA
============================================================

A máquina pode possuir apenas aproximadamente:

1 GB RAM.

O módulo de funil NÃO deve aumentar significativamente o consumo.

Não adicionar:

frameworks enormes

serviços extras

bancos externos

containers adicionais desnecessários.

============================================================
65. FRONTEND
============================================================

O frontend deve parecer um aplicativo comercial.

Sugestão visual:

Cabeçalho:

LeadScan
Funil de vendas

lado direito:

🔎 Buscar

Filtros

+ Novo Lead

Corpo:

cards de métricas

Kanban

============================================================
66. RESPONSIVIDADE
============================================================

Desktop:

Kanban com colunas.

Tablet:

Kanban horizontal.

Celular:

scroll horizontal entre colunas.

Cards devem ter toque fácil.

Botões devem ter tamanho confortável.

============================================================
67. FILTROS DE FUNIL
============================================================

Topo:

🔎 Buscar lead...

[Todos os estágios]

[Todos os responsáveis]

[Todos os períodos]

[Todos]

☑ Sem contato

☑ Atrasados

☑ Retorno hoje

============================================================
68. DETALHE
============================================================

No topo do detalhe:

Empresa

Contato

Estágio

Responsável

Botões:

📞 Ligar

📲 WhatsApp

✏ Editar

➡ Alterar estágio

============================================================
69. SEÇÃO ACOMPANHAMENTO
============================================================

Mostrar:

ESTÁGIO

Qualificado

RESPONSÁVEL

João

ÚLTIMA INTERAÇÃO

01/09/2026 14:30

PRÓXIMA AÇÃO

Enviar proposta

03/09/2026

============================================================
70. SEÇÃO LIGAÇÃO
============================================================

Mostrar:

📞 Ligações

Última ligação:

01/09/2026

Virou lead:

Sim

Observação:

"Interessado em demonstração."

Botão:

[ Registrar nova ligação ]

============================================================
71. TIMELINE
============================================================

Mostrar a timeline em ordem decrescente ou ascendente de forma clara.

Exemplo:

Hoje

✅ Ligação registrada
"Cliente interessado."

Ontem

➡ Mudou para Qualificado

28/08

📲 WhatsApp
"Apresentação enviada."

20/08

📇 Cartão capturado

============================================================
72. MÉTRICAS
============================================================

No topo:

Total

Novos

Ligação feita

Qualificados

Negociação

Fechados

Perdidos

Conversão

Não criar dashboard separado.

Tudo na mesma tela.

============================================================
73. TEMPO MÉDIO
============================================================

Mostrar de forma simples.

Exemplo:

Qualificação:
2,4 dias

Negociação:
6,1 dias

Fechamento:
9,3 dias

Se não houver dados:

mostrar:

— 

============================================================
74. RELATÓRIO
============================================================

Não criar BI complexo.

Mas manter possibilidade de consulta e exportação posteriormente.

Não priorizar CSV agora se isso aumentar muito o escopo.

============================================================
75. ORDEM DE IMPLEMENTAÇÃO
============================================================

Implementar nesta ordem:

FASE 1

Auditar projeto atual.

FASE 2

Migrar banco.

FASE 3

Adicionar estágio.

FASE 4

Adicionar responsável.

FASE 5

Adicionar próxima ação.

FASE 6

Adicionar ligação.

FASE 7

Adicionar histórico.

FASE 8

Adicionar tela /funil.

FASE 9

Adicionar Kanban.

FASE 10

Adicionar filtros.

FASE 11

Adicionar métricas.

FASE 12

Integrar detalhe completo do Lead.

FASE 13

Testar mobile.

FASE 14

Testar compatibilidade com leads existentes.

============================================================
76. TESTES DE BANCO
============================================================

Criar testes para:

novo lead → estágio novo

ligação registrada

ligação virou lead

qualificação

mudança de estágio

perdido sem motivo → bloqueado

perdido com motivo → permitido

fechado

reabertura

histórico

próxima ação

responsável

origem

lead antigo recebendo estágio novo

============================================================
77. TESTES DE API
============================================================

Testar:

GET /funil

GET leads

GET detalhe

PATCH estágio

POST ligação

POST atividade

POST próxima ação

métricas

filtros

============================================================
78. TESTES DE REGRA
============================================================

Teste:

Novo → Qualificado

DEVE FALHAR.

Ligação feita = true

virou_lead = false

→ Qualificado

DEVE FALHAR.

Ligação feita = true

virou_lead = true

→ Qualificado

DEVE FUNCIONAR.

Perdido sem motivo

DEVE FALHAR.

Perdido com motivo

DEVE FUNCIONAR.

Toda mudança de estágio

DEVE criar histórico.

============================================================
79. TESTE CRÍTICO DE DADOS
============================================================

Criar lead:

Nome do contato:
Carlos

Dor:
"Está insatisfeito com o suporte."

Depois adicionar cartão:

Empresa:
Arte & Tear

WhatsApp:
(16) 99726-9098

O resultado deve conter:

DADOS DO LEAD:

Carlos

"Está insatisfeito com o suporte."

+

INFORMAÇÕES DO CARTÃO:

Arte & Tear

(16) 99726-9098

Nenhuma informação deve sobrescrever a outra.

============================================================
80. TESTE DE CARTÃO
============================================================

Usar as fotos reais fornecidas.

Verificar se o sistema preserva:

empresa

telefones

WhatsApps

endereço

CEP

site

redes sociais

OCR

frente

verso.

============================================================
81. LOGIN ÚNICO
============================================================

Implementar apenas:

/login

Senha compartilhada.

Depois da autenticação:

/funil

O usuário permanece autenticado pela sessão.

Não criar usuário individual.

Não exibir nome de usuário na interface.

O responsável do Lead é uma informação comercial, não uma conta de autenticação.

============================================================
82. REMOVER/EVITAR CONCEITO DE ADMIN
============================================================

A aplicação NÃO deve depender de uma área:

/admin

para operar.

Se o projeto atual possui funcionalidades técnicas em /admin:

não necessariamente remover imediatamente sem analisar dependências.

Mas NÃO desenvolver o novo módulo comercial dentro de /admin.

O novo sistema deve ter:

/login

/funil

como fluxo principal.

============================================================
83. STATUS TÉCNICO
============================================================

Não mostrar na tela comercial:

Ollama conectado

modelo instalado

Docker

RAM

logs

health técnico

Essas informações não pertencem à SDR.

============================================================
84. SEGURANÇA
============================================================

Manter sessão segura.

Cookie:

HttpOnly

Secure quando HTTPS

SameSite apropriado.

Proteger:

/funil

/apis de alteração

/leads completos

histórico

atividades.

Não proteger dados públicos de forma incoerente.

Como existe uma única conta compartilhada, NÃO criar diferenciação por usuário autenticado.

============================================================
85. ARQUITETURA FINAL
============================================================

A aplicação deve ficar conceitualmente assim:

                    LEADSCAN
                        │
          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼
       CAPTURA      DADOS DO LEAD   FUNIL
        CARTÃO       👤 VENDEDOR      📊
          │             │             │
          ▼             │             ├── estágio
      OCR + IA          │             ├── responsável
          │             │             ├── ligação
          ▼             │             ├── próxima ação
   INFORMAÇÕES          │             ├── atividades
    DO CARTÃO           │             └── histórico
        📇              │
          └─────────────┴──────────────┘
                        │
                        ▼
                    LEAD ÚNICO
                        │
                        ▼
                   WHATSAPP