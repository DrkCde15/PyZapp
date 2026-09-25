# PyZapp Python SDK

Elegant HTTP client for the PyZapp API. No Node.js, no Baileys here —
just `httpx` + `pydantic` with typed models and mapped errors.

## Install

```bash
pip install -e .
```

## Use

```python
from whatsapp_sdk import WhatsAppClient

with WhatsAppClient(base_url="http://localhost:8000", api_key="...") as client:
    inst = client.create_instance()
    client.print_qr(inst.instance_id)   # ASCII no terminal; escaneie com o WhatsApp
    client.send_message(inst.instance_id, "+5511999999999", "Olá!")
```

Methods: `create_instance`, `list_instances`, `get_instance`,
`delete_instance`, `connect`, `get_qr`, `print_qr`, `get_status`, `send_message`,
`request_pairing_code` (returns the 8-digit string), `set_webhook(url, secret?)`.

Errors (all subclass `WhatsAppSDKError`, with stable `.code`):
`AuthenticationError`, `InstanceNotFoundError`, `NotConnectedError`,
`QRNotAvailableError`, `ValidationError`, `ServiceError`.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest   # httpx.MockTransport, no network
```
