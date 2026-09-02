# 🃏 LeadScan — captura de cartão de visita com IA local

Sistema pessoal e simples: **tire foto de um cartão de visita → a IA (OCR local + modelo de visão via Ollama) extrai as 📇 INFORMAÇÕES DO CARTÃO → você decide o que copiar para o lead → 💾 salva tudo junto → envie no WhatsApp com foto + texto já prontos.**

O cartão é uma camada **complementar** do lead (V2): o que o vendedor digita nunca é sobrescrito, frente + verso formam um único cartão, e as duas fontes — 👤 manual e 🤖 cartão — são salvas no MESMO lead.

Versão enxuta do antigo HubLead, redesenhado para eliminar a classe de bug que derrubou aquele projeto: **uma fonte de verdade só, sem cópias de código**. Não existe diretório de deploy separado — o docker-compose.yml builda direto do clone git.

## Arquitetura

| Camada | Escolha | Por quê |
|---|---|---|
| IA | Ollama local (host, porta 11434) | Já validado, roda em CPU, sem custo de API |
| OCR local | Tesseract (`tesseract-ocr-por`) no container, via pytesseract | Telefone/CEP/e-mail/URL lidos de forma determinística; roda dentro do container com ~1 GB de RAM |
| Backend | Python + FastAPI, 1 processo | Simples, sem framework de hooks separado |
| Banco | SQLite (arquivo único em data/) | Uso pessoal, zero serviço extra |
| Frontend | 1 arquivo HTML + JS puro (sem build) | Sem etapa de build, fácil de editar |
| WhatsApp | Web Share API com foto(s) + texto; fallback wa.me só texto | Sem QR code, sem sessão, sem dependência externa |
| Deploy | docker-compose.yml que builda direto do clone git (network_mode host, Linux) | Elimina a possibilidade de duas cópias dessincronizadas |
| Acesso público | Nginx do host + Let's Encrypt; container em network_mode host com app só em 127.0.0.1:8000 | TLS termina no Nginx; app nunca exposto direto |
| Painel admin | Rota /admin no próprio FastAPI, senha única (bcrypt + cookie assinado) | Sem serviço extra, sem outro domínio |

## Estrutura

```
leadscan/
├── app/
│   ├── main.py              # FastAPI: /health, /extract, /leads, /admin/*, estáticos
│   ├── cartao.py            # pipeline frente+verso: OCR → VLM → fusão → validação → 📇
│   ├── imagem.py            # pré-processamento (EXIF, escala 1800/1024, contraste, Otsu)
│   ├── ocr.py               # Tesseract local (por+eng, PSM 6, rotação 90/180/270)
│   ├── validadores.py       # validação determinística (telefone, CEP, e-mail, URL, CNPJ)
│   ├── db.py                # SQLite: schema + CRUD + tabela lead_cartao (1:1 com leads)
│   ├── ollama_client.py     # LFM2.5-VL-450M: visão/interpretação (parse JSON defensivo)
│   ├── auth.py              # sessão/cookie do admin (bcrypt + itsdangerous)
│   └── requirements.txt
├── static/
│   └── index.html           # UI única: captura, 📇 do cartão, formulário, WhatsApp
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

Pré-requisito: **apenas o registro DNS** do subdomínio apontando pro IP da VPS (e, se quiser HTTPS automático, o e-mail do Let's Encrypt no .env). O install.sh instala sozinho o que faltar: git, Docker + plugin compose, Ollama + modelo, Nginx e Certbot.

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

### Instalação (VPS nova ou atualização)

```bash
git clone <seu-repositorio>/leadscan.git && cd leadscan
cp .env.example .env
# preencha .env:
#   ADMIN_PASSWORD_HASH: python3 -c "import bcrypt; print(bcrypt.hashpw(b'SUA_SENHA', bcrypt.gensalt()).decode())"
#   SESSION_SECRET:      openssl rand -hex 32
#   CERTBOT_EMAIL:       seu e-mail (opcional — ativa HTTPS automático)
sudo bash install.sh
```

O install.sh é **idempotente**: instalação inicial e atualização usam o mesmo comando. Numa VPS limpa ele instala Docker, Ollama, modelo, Nginx e Certbot automaticamente; valida as rotas com HTTP real no final; e, se CERTBOT_EMAIL estiver preenchido, emite o certificado HTTPS sozinho (o DNS já precisa apontar pra VPS). Antes de rodar de novo após alterações, sempre git pull primeiro.

**Swap (memória):** o Ollama carrega o modelo de visão em RAM — em VPS pequena (1–2 GB) isso estoura com OOM ao puxar/rodar o modelo. O install.sh cria **2 GB de swap** automaticamente se ainda não existir `/swapfile` (idempotente). Se você configurou o swap manualmente antes, nada muda — o script detecta o `/swapfile` e pula. Para aumentar manualmente:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # persistir no boot
```

**Atualizar o LeadScan:**

```bash
git pull && sudo bash install.sh
```

### Domínio + HTTPS (Nginx + Certbot)

Com o DNS apontando o subdomínio pro IP da VM:

```bash
# se CERTBOT_EMAIL estiver no .env, o install.sh já faz tudo (nginx + certbot);
# senão, manualmente:
sudo cp nginx/hublead.conf /etc/nginx/sites-available/hublead.conf
sudo ln -s /etc/nginx/sites-available/hublead.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d hublead.pradodacostasolucoes.com.br
```

O certbot --nginx ajusta o server block pra HTTPS (443 + redirect) e configura a renovação automática. O container do app fica em network_mode host escutando só em 127.0.0.1:8000 — quem termina o TLS é o Nginx do host.

## Uso

1. Abra https://hublead.pradodacostasolucoes.com.br/ no celular.
2. Toque em **Frente do cartão** — a câmera abre; fotografe o cartão (o verso é opcional; fotografar o verso re-analisa frente+verso juntos).
3. A IA mostra a seção **📇 INFORMAÇÕES DO CARTÃO** — ela **não mexe no formulário**. Para aproveitar um dado, toque em **[ Usar no Lead ]**: ele só copia para campos **vazios**; o que você já digitou nunca é substituído (regra absoluta do V2).
4. Complete/confira os campos manuais (**👤 Dados do lead**) e toque em **Enviar no WhatsApp**: a folha de compartilhamento nativa abre com a **foto + texto juntos** — escolha o contato e envie.
   - Em navegadores sem suporte a arquivos na Web Share API (desktop), cai no fallback wa.me só com o texto + aviso pra anexar a foto manualmente (com botão de download).
5. **💾 Salvar lead** grava no SQLite **o lead único**: dados manuais + INFORMAÇÕES DO CARTÃO (tabela `lead_cartao`, 1:1). A análise da foto NÃO salva nada sozinha.

### Painel admin

https://hublead.pradodacostasolucoes.com.br/admin — pede a senha do .env. Mostra:

- **Status da IA**: 🟢/🔴 conectividade com o Ollama, modelo configurado × instalado, **Tesseract (OCR local) disponível/ausente**, última extração bem-sucedida, botão "Testar agora".
- **Leads**: lista completa com busca por nome/contato/whatsapp, filtro por período, detalhe com fotos, **📇 informações do cartão** quando houver e **exportação CSV**.

## API

| Rota | Método | Descrição |
|---|---|---|
| /health | GET | {"status":"ok"} — healthcheck do Docker e do install.sh |
| / | GET | UI (static/index.html) |
| /extract | POST | multipart image (+ verso opcional). Pré-processa → OCR → IA de visão → fusão → validação e devolve `cartao` (📇), `data` (formato antigo), `fotos` (paths já salvos) e `avisos`. **NÃO cria lead** (regra 9 — só com `salvar=1`, compatibilidade). Erros: 422 (imagem/JSON), 413 (grande), 502 (Ollama fora), 500 (interno) — sempre com mensagem específica |
| /leads | GET | últimos leads (JSON, limite padrão 20) |
| /leads | POST | persiste o formulário completo (multipart): campos manuais + `cartao_json` (📇) + `foto_frente_path`/`foto_verso_path` (reaproveitados do /extract); com `lead_id` atualiza em vez de duplicar |
| /config | GET | defaults da UI (ex.: DDI do WhatsApp) |
| /admin/login | GET/POST | login por senha (cookie assinado httponly+secure) |
| /admin, /admin/leads | GET | painel (exige sessão) |
| /api/status | GET | status do Ollama/modelo/última extração + Tesseract (OCR local) (admin) |
| /api/leads | GET | lista com busca/de/ate/limite (admin) |
| /api/leads/export | GET | CSV com os mesmos filtros (admin) |
| /api/leads/{id} | GET | detalhe completo (admin) |
| /fotos/{nome} | GET | serve fotos salvas (admin) |

### Exemplo de extração via curl

```bash
curl -F "image=@cartao.jpg" http://127.0.0.1:8000/extract
# {"success": true, "id": null, "cartao": {...}, "data": {...}, "fotos": {"frente": "fotos/...jpg", "verso": ""}, "avisos": []}
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

## 🎨 Design (UX)

Tokens de cor compartilhados entre o app e o painel admin (ver `PLANO-UX.md`):

- **Verde** (`--verde`) = lead / ação principal (💾 salvar, 📲 WhatsApp, sucesso)
- **Roxo** (`--ia`) = 🤖 IA / cartão de visita (seção 📇, botões "[ Usar no Lead ]")
- **Vermelho** (`--erro`) = erro / destrutivo
- **Cinzas** = neutro / texto secundário

Regras do app: o cartão **nunca** sobrescreve campos manuais (o "[ Usar no Lead ]" só copia para campo vazio); toda ação tem feedback visível perto dela; empty states sempre oferecem o próximo passo; alvos de toque ≥ 44px e `prefers-reduced-motion` respeitado.

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
# pré-requisito do OCR local (sem ele o app continua de pé, mas só com a IA de visão):
#   Debian/Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-por
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