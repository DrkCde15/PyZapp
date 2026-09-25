# PyZapp API

Public FastAPI layer: `X-API-Key` auth, E.164 validation, instance metadata,
and proxying to `baileys-service`. Holds no WhatsApp logic.

## Run

```bash
pip install -e ".[dev]"
API_KEY=dev INTERNAL_API_KEY=dev-internal uvicorn app.main:app --port 8000
```

Docs: http://localhost:8000/docs

## Layout

```text
app/main.py             app factory, lifespan, error envelopes, CORS
app/config.py           env-based settings (pydantic-settings)
app/auth.py             X-API-Key dependency
app/routes/            instances.py (CRUD + qr/status/messages), health.py
app/services/baileys.py httpx client for the internal contract
app/store.py            in-memory metadata (swap for Postgres later)
app/schemas.py          validation (phone E.164, text 1-4096)
app/errors.py           stable error codes
```

## Tests

```bash
python -m pytest   # TestClient + FakeBaileys, no network
```
