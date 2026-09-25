# baileys-service

Internal Node.js service that fully encapsulates Baileys (@whiskeysockets/baileys 6.7.x).
Called **only** by the FastAPI layer over HTTP (`X-Internal-Key`).

```text
Route -> WhatsAppManager -> WhatsAppInstance -> Baileys
```

## Run

```bash
npm install
INTERNAL_API_KEY=dev-internal SESSION_DIR=./sessions node src/server.js
```

Env vars: `BAILEYS_PORT` (3001), `INTERNAL_API_KEY`, `SESSION_DIR`,
`LOG_LEVEL`, `NODE_ENV`.

## Internal contract

| Method | Path | Notes |
|---|---|---|
| POST | /internal/instances `{instance_id}` | creates + starts connecting, 201 |
| GET | /internal/instances | list snapshots (boot re-sync) |
| GET | /internal/instances/{id}/status | live connection state |
| GET | /internal/instances/{id}/qr | 200 `{qr}` or 409 `qr_not_available` |
| POST | /internal/instances/{id}/connect | (re)connect, 202 |
| POST | /internal/instances/{id}/messages `{to, text}` | requires connected |
| POST | /internal/instances/{id}/pairing-code `{phone}` | 8-digit code for phone linking |
| PUT | /internal/instances/{id}/webhook `{url, secret?}` | inbound delivery target |
| DELETE | /internal/instances/{id} | destroys socket + wipes session |
| GET | /health | public, `{status, service, instances, uptime_s}` |

Statuses: `created | connecting | qr_pending | connected | disconnected | logged_out`
(+ transient 409 `connection_not_ready` when the socket is still handshaking).
Auto-reconnect with capped backoff; `loggedOut (401)` wipes the session and waits
for a fresh `connect`. Sessions persist in `SESSION_DIR/{instance_id}` (auth state
+ `webhook.json`) and are restored on boot.

## Tests

```bash
npm test   # node --test, fake-socket harness, no network
```

## Inbound messages

`messages.upsert` is normalized to `{event: message.received, instance_id,
message_id, from, text, timestamp}` for 1:1 text chats only (groups, status,
newsletters and media are skipped in this MVP) and POSTed to the configured
webhook with `X-Webhook-Secret`, 5s timeout, 3 attempts with backoff.
Delivery is fire-and-forget: failures are logged, never raised.
