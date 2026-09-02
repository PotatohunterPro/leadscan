# UX — Tela de Funil (LeadScan)

Documento de experiência para a tela que BDR e SDR usam todo dia. Não é
documentação técnica (isso já está no `funil_implement_v2.md`) — é como a
tela deve se comportar e comunicar, pra guiar decisões de layout, estados e
texto na implementação.

## Premissa de uso

Quem abre essa tela não é analista de sistema — é alguém no telefone o dia
inteiro, alternando entre ligar, registrar e ligar de novo. A tela precisa
ser rápida de escanear e rápida de agir, não bonita para admirar. Cada
elemento na tela tem que responder "o que eu faço agora com este lead?".

## Papéis

- **BDR** — trabalha a ponta de entrada do funil: leads em **Novo**,
  responsável por fazer a primeira ligação e decidir se virou lead
  (**Ligação feita → Qualificado**).
- **SDR** — assume a partir de **Qualificado**, conduz **Negociação** até
  **Fechado** ou **Perdido**.
- Os dois usam a mesma tela — o que muda é o filtro que cada um deixa
  fixado (BDR filtra por "Novo" e "Sem contato"; SDR filtra por
  "Qualificado" e "Atrasados"). Não há tela separada por papel — seria
  manutenção duplicada pra um time pequeno.

*(Assumindo que BDR e SDR compartilham o mesmo `responsavel_atual` por
lead e a passagem de bastão acontece só pela mudança de estágio — se na
prática vocês têm um handoff formal com troca de responsável, me avisa que
ajusto o fluxo.)*

## Mapa da tela

```
┌─────────────────────────────────────────────────────────┐
│  Funil de Vendas                    [+ Novo Lead]         │
│  ── contadores por estágio ──                              │
│  Novo 12 · Ligação feita 4 · Qualificado 7 · Negociação 3  │
│  · Fechado 21 · Perdido 9                                   │
│                                                              │
│  [Meus leads ▾] [🔴 Atrasados] [Retorno hoje] [Sem contato] │
│  [Origem ▾] [Buscar...]                                     │
│                                                              │
│  ┌─Novo──┐ ┌─Ligaç─┐ ┌─Qualif.─┐ ┌─Negoc.─┐ ┌─Fech.─┐    │
│  │ card  │ │  card   │ │  card   │ │  card  │ │ card  │    │
│  │ card  │ │  card   │ │  card   │ │  card  │ │ card  │    │
│  └───────┘ └─────────┘ └─────────┘ └────────┘ └───────┘    │
└─────────────────────────────────────────────────────────┘
```

Kanban horizontal com scroll lateral em desktop. Em mobile (a maior parte
do uso real, já que a SDR pode estar em campo ou entre ligações no
celular), vira **lista vertical com um seletor de estágio no topo** em vez
de colunas lado a lado — colunas espremidas em tela pequena obrigam a
zoom e isso mata a velocidade de uso.

## Anatomia do card

Cada card precisa responder três perguntas com o olho, sem clicar:
**quem é**, **há quanto tempo está parado**, **o que fazer a seguir**.

```
┌──────────────────────────────┐
│ [foto]  Padaria Bela Vista     │
│         João Silva · Varejo    │
│         📇  🔔 retorno hoje    │
│         há 2 dias · Maria (SDR)│
└──────────────────────────────┘
```

- Foto do cartão em miniatura só se `origem = cartao` (dá contexto visual
  instantâneo — "esse eu peguei no evento").
- Segmento como texto simples, não badge colorido — cor deve ser reservada
  pra sinalizar urgência, não decorar categoria.
- Tempo no estágio: texto neutro até 3 dias; passado isso, destaque (cor +
  peso de fonte, não ícone piscando) — estagnação é informação de
  prioridade, não decoração.
- `🔔` só aparece quando existe próxima ação agendada; se a data já
  passou, o card inteiro pode ganhar uma borda de atenção (sutil, uma
  linha, não um card vermelho inteiro — muito alarme banaliza o alarme).
- Toque/clique no card inteiro abre o detalhe — sem precisar acertar um
  botão pequeno específico.

## Tela de detalhe

Abre por cima da tela (modal ou painel lateral, o que for mais rápido de
fechar sem perder a posição no Kanban). Três blocos, nessa ordem — do mais
usado pro menos usado no dia a dia:

**1. Ações rápidas** (topo, sempre visível, sem scroll)
`📞 Ligar` · `📲 WhatsApp` · `➡ Mudar estágio` · `✏ Editar`

Isso é o que a SDR faz 90% das vezes que abre um lead — não deve estar
escondido embaixo dos dados cadastrais.

**2. Acompanhamento** (o que importa pro trabalho comercial)
- Estágio atual + responsável
- Última interação (data + tipo)
- Próxima ação: se não tem, é um convite a criar uma ("Nenhuma ação
  agendada — agendar retorno"), não um campo vazio mudo
- Histórico da ligação (feita? virou lead? observação)
- `[+ Registrar interação]` — abre um mini-formulário inline (tipo +
  texto curto), não uma página nova
- Timeline de atividades, mais recente primeiro, com ícone por tipo

**3. Dados do lead** (consulta, não é o que se edita toda hora)
- Contato, empresa, telefone, e-mail, segmento, sistema atual, mensalidade
- Bloco separado "📇 Cartão" só se existir foto/OCR — frente/verso,
  colapsado por padrão pra não empurrar o que importa pra baixo

## Fluxos principais

**BDR — ligação de prospecção**
1. Abre a tela já filtrada em "Novo" + "Sem contato"
2. Clica no card → `📞 Ligar`
3. Depois da ligação, registra direto ali: feita? virou lead?
   observação curta
4. Se virou lead → sistema já habilita mover pra "Qualificado"; se não →
   fica em "Ligação feita" com o motivo registrado (evita perder o
   contexto de por que não avançou)

**SDR — condução até fechamento**
1. Abre filtrado em "Qualificado" + "Atrasados"
2. Prioriza quem está com `🔔` vencido
3. Ao fechar: `➡ Mudar estágio → Fechado`, sistema pede observação final
   (não motivo — motivo é só pra perdido) e registra atividade "✅ Lead
   fechado" automaticamente
4. Ao perder: seleciona motivo de uma lista curta (não digita do zero toda
   vez — decisão rápida, dado consistente pra métricas depois)

## Vazio e erro

- Kanban sem nenhum lead ainda: convite direto — "Nenhum lead capturado
  ainda. Use o app de captura ou [+ Novo Lead] pra começar." — não uma
  ilustração genérica de caixa vazia.
- Coluna de estágio vazia (ex: ninguém em "Negociação" hoje): texto simples
  "Nenhum lead aqui no momento", sem tratar como erro.
- Falha ao salvar (ligação, atividade, mudança de estágio): mensagem diz o
  que não foi salvo e o que fazer — "Não foi possível registrar a ligação.
  Tente novamente." — nunca um erro técnico cru na tela.

## Linguagem

- Botões descrevem a ação, não o sistema: "Registrar ligação", não
  "Submeter"; "Mudar estágio", não "Atualizar status".
- Consistência de nome do fim ao fim: se o botão diz "Registrar ligação",
  a confirmação diz "Ligação registrada" — nunca troca de vocabulário no
  meio do fluxo.
- Sem jargão técnico em nenhuma tela do time comercial — nada de "origem",
  "payload", "sync" aparecendo cru; usar "de onde veio o lead" em vez de
  "origem" como rótulo, por exemplo.

## Direção visual

Ferramenta de uso intenso e repetitivo, não uma vitrine — a prioridade é
legibilidade e velocidade de escaneamento, não impressionar.

- **Cor**: paleta neutra de base (cinzas quentes) com uma única cor de
  destaque reservada exclusivamente para "precisa de atenção agora"
  (atrasado, estagnado). Se tudo tem cor, nada chama atenção.
- **Tipografia**: uma família só, sem serifa (tela de trabalho, não
  editorial), com bom contraste em tamanhos pequenos — os cards vão ter
  bastante texto compacto.
- **Densidade**: preferir mais leads visíveis por scroll a cards grandes e
  espaçosos — quem usa isso o dia inteiro quer ver o panorama, não rolar
  sem parar.
- Evitar cards com sombra e borda arredondada padrão de SaaS genérico —
  usar divisórias simples (linha fina) entre estágios; a hierarquia vem do
  agrupamento por coluna, não de decoração por card.
