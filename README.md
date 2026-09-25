# PyZapp — WhatsApp API + Python SDK (MVP)

Control WhatsApp from Python without installing Node.js. You use the **Python SDK**;
we run **FastAPI** + a **Baileys (Node.js) service** for you — via Docker.

```text
Aplicação Python do usuário
        │  Python SDK (httpx, sem Node.js)
        ▼
   Nossa API REST (FastAPI :8000)
        │  HTTP interno + X-Internal-Key
        ▼
Baileys Service (Node.js :3001)
        │
        ▼
    WhatsApp
```

## Status do MVP

Funcional: subir stack, criar instância, obter QR **ou pairing code**, detectar
estado, sessão persistida (inclui config de webhook), enviar texto, **receber
textos via webhook**, erros padronizados, health checks, testes.

Fora do escopo (futuro): multi-tenant avançado, filas, Postgres/Redis,
mídia, grupos, dashboard, IA, automações.

## Pré-requisitos

- Docker + Docker Compose (para rodar tudo), **ou**
- Python 3.11+ e Node 20+ (para rodar local sem Docker)

## Como executar (Docker)

```bash
cp .env.example .env
# edite .env: gere segredos com  openssl rand -hex 32
docker compose up --build
# ou com podman:
podman compose up --build
```

- API: http://localhost:8000 — docs interativas: http://localhost:8000/docs
- Baileys (interno): http://localhost:3001/health

## Como executar local (sem Docker)

```bash
# 1. Baileys service
cd baileys-service && npm install
INTERNAL_API_KEY=dev-internal SESSION_DIR=./sessions node src/server.js

# 2. API (outro terminal)
cd api && pip install -e ".[dev]"
INTERNAL_API_KEY=dev-internal BAILEYS_BASE_URL=http://localhost:3001 \
  uvicorn app.main:app --port 8000

# 3. SDK
cd python-sdk && pip install -e ".[dev]"
```

## Uso do SDK

```python
from whatsapp_sdk import WhatsAppClient

client = WhatsAppClient(base_url="http://localhost:8000", api_key="...")

instance = client.create_instance()          # já começa a conectar
client.print_qr(instance.id)                 # ASCII no terminal; escaneie no WhatsApp

# Alternativa ao QR: digite o código no aparelho
# (WhatsApp > Aparelhos conectados > Conectar com número de telefone)
print(client.request_pairing_code(instance.id, "+5511999999999"))

client.get_status(instance.id)               # qr_pending -> connected

# Receber mensagens: registre um webhook (POST JSON a cada texto recebido)
client.set_webhook(instance.id, "https://sua-app.com/wa", secret="...")

client.send_message(instance.id, "+5511999999999", "Olá!")
```

Renderizar o QR é direto (o SDK já inclui `qrcode`):

```python
client.print_qr(instance.id)
```

Ou abra `http://localhost:8000/docs`, chame `GET /instances/{id}/qr` e use
qualquer leitor de QR.

## Endpoints da API

Todos (exceto `/health`) exigem header `X-API-Key`.

```http
POST   /instances
GET    /instances
GET    /instances/{id}
DELETE /instances/{id}
POST   /instances/{id}/connect
GET    /instances/{id}/qr
GET    /instances/{id}/status
POST   /instances/{id}/messages      {"phone": "+5511999999999", "text": "Olá!"}
POST   /instances/{id}/pairing-code   {"phone": "+5511999999999"} -> {"pairing_code": "ABCD-1234"}
PUT    /instances/{id}/webhook        {"url": "https://sua-app.com/wa", "secret": "..."}
PUT    /instances/{id}/ai             {"provider": "groq", "system_prompt": "..."} -> config
GET    /instances/{id}/ai             -> config atual (sem expor a chave)
DELETE /instances/{id}/ai             -> desliga o auto-reply
GET    /health
```

Webhook enviado a cada texto recebido (somente conversas 1:1 neste MVP):

```json
{
  "event": "message.received",
  "instance_id": "...",
  "message_id": "...",
  "from": "5511999999999",
  "text": "Olá!",
  "timestamp": 1700000000
}
```

Header `X-Webhook-Secret` acompanha quando configurado. Entrega com 3
tentativas (backoff); sem webhook configurado, inbound é descartado com log.

Erros seguem o envelope `{ "success": false, "error": {"code": "...", "message": "..."} }`
com códigos estáveis: `unauthorized`, `instance_not_found`, `not_connected`,
`qr_not_available`, `validation_error`, `baileys_unreachable`, `baileys_error`.

## IA auto-reply (opcional)

```python
client.set_ai(
    instance.id,
    provider="groq",            # openai | groq | openrouter | ollama | gemini | anthropic
    model="llama-3.3-70b-versatile",
    system_prompt="Você é o atendente da loja. Seja breve.",
    cooldown_s=30,
)
```

Providers OpenAI-compatíveis usam `base_url` padrão (sobrescreva para gateway
próprio); chaves via env (`OPENAI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`,
`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`) ou por instância (`api_key=`). Ollama
local dispensa chave. Histórico das últimas N mensagens por conversa (SQLite),
cooldown por remetente e opt-out (`SAIR`/`STOP`/`PARAR`) inclusos.

## Estrutura

```text
python-sdk/       cliente HTTP elegante (httpx + pydantic), sem lógica Baileys
api/              FastAPI: auth, validação, metadados, proxy p/ o Baileys
baileys-service/  Node.js: WhatsAppManager -> WhatsAppInstance -> Baileys 6.x
docker-compose.yml
.env.example
```

## Testes

```bash
cd baileys-service && npm test            # node --test, 16 testes
cd api && pip install -e ".[dev]" && python -m pytest   # 13 testes
cd python-sdk && pip install -e ".[dev]" && python -m pytest  # 9 testes
```

## Decisões arquiteturais

- **Baileys 6.7.x estável** (não a v7 RC): evita breaking changes (ESM-only, LIDs)
  num MVP fundacional. Upgrade para v7 é possível sem tocar API/SDK.
- **JavaScript (não TS)** no serviço: menos toolchain; `WhatsAppManager` isola o
  Baileys para migração futura.
- **Sessões em disco** via `useMultiFileAuthState`, atrás da interface
  `SessionStore` (`load/clear/listIds`) — o ponto de troca por PostgreSQL.
- **Metadados da API em SQLite** (`DATABASE_PATH`, stdlib — sem dependências):
  `InstanceStore` usa memória quando o caminho é vazio e SQLite quando
  informado; no compose, persiste no volume `api-data`.
- **FastAPI sem estado próprio**: metadados em memória + ressync do Baileys no boot.

## Segurança

Secrets só via `.env` (veja `.env.example`); `X-Internal-Key` entre API e Baileys;
telefones validados (E.164); telefones mascarados nos logs; sem credenciais nos
logs; CORS configurável; `API_KEY` obrigatória em produção.
