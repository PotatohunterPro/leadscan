# 🃏 LeadScan — captura de cartão de visita com IA local

Sistema pessoal e simples: **tire foto de um cartão de visita → a IA (rodando localmente via Ollama) extrai os dados → o lead é salvo → envie no WhatsApp com foto + texto já prontos.**

Versão enxuta do antigo HubLead, redesenhado para eliminar a classe de bug que derrubou aquele projeto: **uma fonte de verdade só, sem cópias de código**. Não existe diretório de deploy separado — o docker-compose.yml builda direto do clone git.

## Arquitetura

| Camada | Escolha | Por quê |
|---|---|---|
| IA | Ollama local (host, porta 11434) | Já validado, roda em CPU, sem custo de API |
| Backend | Python + FastAPI, 1 processo | Simples, sem framework de hooks separado |
| Banco | SQLite (arquivo único em data/) | Uso pessoal, zero serviço extra |
| Frontend | 1 arquivo HTML + JS puro (sem build) | Sem etapa de build, fácil de editar |
| WhatsApp | Web Share API com foto(s) + texto; fallback wa.me só texto | Sem QR code, sem sessão, sem dependência externa |
| Deploy | docker-compose.yml que builda direto do clone git | Elimina a possibilidade de duas cópias dessincronizadas |
| Acesso público | Nginx do host + Let's Encrypt, container só em 127.0.0.1:8000 | TLS termina no Nginx; app nunca exposto direto |
| Painel admin | Rota /admin no próprio FastAPI, senha única (bcrypt + cookie assinado) | Sem serviço extra, sem outro domínio |

## Estrutura

```
leadscan/
├── app/
│   ├── main.py              # FastAPI: /health, /extract, /leads, /admin/*, estáticos
│   ├── db.py                # SQLite: schema + CRUD simples
│   ├── ollama_client.py     # extrair_dados(imagem_bytes) -> dict (parse JSON defensivo)
│   ├── auth.py              # sessão/cookie do admin (bcrypt + itsdangerous)
│   └── requirements.txt
├── static/
│   └── index.html           # UI única: captura, /extract, formulário, WhatsApp
├── templates/
│   ├── admin_login.html     # login do admin
│   ├── admin_status.html    # dashboard: status da IA + últimos leads
│   └── admin_leads.html     # lista/busca/filtro/CSV/detalhe dos leads
├── nginx/
│   └── hublead.conf         # server block do domínio (TLS via certbot)
├── data/                    # volume persistente: leadscan.db + fotos/ (gitignored)
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── install.sh
└── README.md
```

## Deploy na VPS

Pré-requisitos na VPS: Docker + compose plugin, Nginx, Certbot, e o **Ollama já rodando na porta 11434** com o modelo de visão baixado (ollama list deve mostrar hf.co/LiquidAI/LFM2.5-VL-450M-GGUF:Q8_0; se não, o install.sh baixa sozinho).

### Passo zero — desinstalar o HubLead antigo

O domínio hublead.pradodacostasolucoes.com.br vai ser reaproveitado, então o projeto antigo precisa sair antes de subir o novo. Já existe script pronto no clone antigo:

```bash
sudo bash ~/hublead/infra/uninstall.sh
# digite DESINSTALAR quando pedir
```

Ele remove containers/volumes Docker, o systemd unit, o site do Nginx, o certificado SSL (via certbot delete), o cron de backup, /opt/hubleads (guardando backups/) e o usuário de sistema. Observações:

- O certificado SSL é apagado junto — o certbot --nginx do LeadScan vai emitir um certificado novo pro mesmo domínio (normal, sem ação extra).
- Os backups ficam preservados em /opt/hubleads/backups/ (apague com sudo rm -rf /opt/hubleads/backups se não precisar).
- O clone ~/hublead não é removido pelo script — pode manter como referência ou apagar depois.

### Instalação

```bash
git clone <seu-repositorio>/leadscan.git && cd leadscan
cp .env.example .env
# preencha .env:
#   ADMIN_PASSWORD_HASH: python3 -c "import bcrypt; print(bcrypt.hashpw(b'SUA_SENHA', bcrypt.gensalt()).decode())"
#   SESSION_SECRET:      openssl rand -hex 32
sudo bash install.sh
```

O install.sh é **idempotente**: instalação inicial e atualização usam o mesmo comando. Antes de rodar de novo após alterações, sempre git pull primeiro.

**Atualizar o LeadScan:**

```bash
git pull && sudo bash install.sh
```

### Domínio + HTTPS (Nginx + Certbot)

Com o DNS apontando o subdomínio pro IP da VM:

```bash
sudo cp nginx/hublead.conf /etc/nginx/sites-available/hublead.conf
sudo ln -s /etc/nginx/sites-available/hublead.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d hublead.pradodacostasolucoes.com.br
```

O certbot --nginx ajusta o server block pra HTTPS (443 + redirect) e configura a renovação automática.

## Uso

1. Abra https://hublead.pradodacostasolucoes.com.br/ no celular.
2. Toque em **Frente do cartão** — a câmera abre; fotografe o cartão.
3. A IA preenche o formulário (campos 🤖); complete os manuais (qualificação, anotações, etc.).
4. Toque em **Enviar no WhatsApp**: a folha de compartilhamento nativa abre com a **foto + texto juntos** — escolha o contato e envie.
   - Em navegadores sem suporte a arquivos na Web Share API (desktop), cai no fallback wa.me só com o texto + aviso pra anexar a foto manualmente (com botão de download).
5. **Salvar lead** grava o formulário completo no SQLite (a extração da frente já salva um lead parcial automaticamente).

### Painel admin

https://hublead.pradodacostasolucoes.com.br/admin — pede a senha do .env. Mostra:

- **Status da IA**: 🟢/🔴 conectividade com o Ollama, modelo configurado × instalado, última extração bem-sucedida, botão "Testar agora".
- **Leads**: lista completa com busca por nome/contato/whatsapp, filtro por período, detalhe com fotos e **exportação CSV**.

## API

| Rota | Método | Descrição |
|---|---|---|
| /health | GET | {"status":"ok"} — healthcheck do Docker e do install.sh |
| / | GET | UI (static/index.html) |
| /extract | POST | multipart image (+ verso opcional). Redimensiona, extrai com IA, salva o lead. Sucesso: {"success":true,"id":N,"data":{...}}. Erros: 422 (JSON inválido/imagem inválida), 502 (Ollama fora), 500 (interno) — sempre com mensagem específica |
| /leads | GET | últimos leads (JSON, limite padrão 20) |
| /leads | POST | persiste o formulário completo (multipart; com lead_id atualiza em vez de duplicar) |
| /config | GET | defaults da UI (ex.: DDI do WhatsApp) |
| /admin/login | GET/POST | login por senha (cookie assinado httponly+secure) |
| /admin, /admin/leads | GET | painel (exige sessão) |
| /api/status | GET | status do Ollama/modelo/última extração (admin) |
| /api/leads | GET | lista com busca/de/ate/limite (admin) |
| /api/leads/export | GET | CSV com os mesmos filtros (admin) |
| /api/leads/{id} | GET | detalhe completo (admin) |
| /fotos/{nome} | GET | serve fotos salvas (admin) |

### Exemplo de extração via curl

```bash
curl -F "image=@cartao.jpg" http://127.0.0.1:8000/extract
# {"success": true, "id": 1, "data": {"nome_empresa": "...", "whatsapp": "...", ...}}
```

> Upload sempre via **multipart (corpo HTTP)** — nunca base64 como argumento de linha de comando (lição "Argument list too long" do projeto anterior).

## Critérios de aceite

1. sudo bash install.sh numa VPS limpa (com Docker) termina em "instalado e verificado com sucesso".
2. curl -X GET http://127.0.0.1:8000/extract retorna 405, não 404 nem timeout.
3. curl -F "image=@cartao.jpg" http://127.0.0.1:8000/extract retorna 200 com JSON coerente em menos de 30s.
4. No celular: foto → dados extraídos → completar manuais → "Enviar no WhatsApp" abre a folha nativa com **foto + texto juntos**.
5. git pull && sudo bash install.sh de novo, sem alterações, não quebra nada (idempotente) e reconfirma /extract e /admin/login.
6. https://hublead.pradodacostasolucoes.com.br/ carrega com cadeado válido.
7. /admin pede senha; logado, mostra status do Ollama (🟢/🔴 + modelo + última extração) e a lista de leads.

## Lições do projeto anterior — por que este é diferente

- **Uma fonte de verdade só.** O docker-compose.yml builda direto do clone git (COPY . .). Não existe /opt/leadscan com outra cópia. Atualizar é sempre git pull && sudo bash install.sh.
- **Erros específicos, nunca mensagem genérica.** Toda falha de /extract devolve {"success": false, "error": "..."} com a causa real (Ollama fora, JSON inválido, imagem inválida...).
- **Upload via multipart**, nunca base64 em argumento de linha de comando.
- **Imagem redimensionada** (máx 1024px, JPEG q80) antes do modelo — evita timeout com foto de celular.
- **O install.sh valida as rotas com HTTP real** ao final — nunca assume que "container up" = "rota funcionando".

## Desenvolvimento local (sem Docker)

```bash
cd leadscan
python3 -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt
export DATA_DIR=./data
export OLLAMA_URL=http://localhost:11434/api/generate   # se Ollama local
export ADMIN_PASSWORD_HASH="<hash bcrypt>" SESSION_SECRET="dev-secret"
uvicorn app.main:app --reload
# abra http://127.0.0.1:8000
```

Testes rápidos (parse JSON defensivo + CRUD do banco):

```bash
python -m unittest discover -s tests -v
```