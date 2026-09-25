# PyZapp Python SDK

Send and receive WhatsApp messages from Python. No Node.js, no browser
automation — just `pip install pyzapp-sdk` and an API key.

```bash
pip install pyzapp-sdk
```

```python
from whatsapp_sdk import WhatsAppClient

with WhatsAppClient(base_url="https://sua-api.com", api_key="...") as client:
    inst = client.create_instance()
    client.print_qr(inst.instance_id)  # scan with WhatsApp
    client.send_message(inst.instance_id, "+5511999999999", "Olá!")
```

No QR? Use a pairing code instead:

```python
print(client.request_pairing_code(inst.instance_id, "+5511999999999"))
# type the 8-digit code on your phone
```

AI auto-reply (OpenAI, Groq, OpenRouter, Ollama, Gemini, Anthropic):

```python
client.set_ai(inst.instance_id, provider="groq", system_prompt="Seja breve.")
```

## Methods

Instances: `create_instance`, `list_instances`, `get_instance`,
`delete_instance`, `connect`, `get_qr`, `print_qr`, `get_status`.

Messaging: `send_message`, `request_pairing_code`, `set_webhook(url, secret?)`.

AI: `set_ai`, `get_ai`, `disable_ai`.

## Errors

All subclass `WhatsAppSDKError` and carry a stable `.code`:

`AuthenticationError`, `InstanceNotFoundError`, `NotConnectedError`,
`QRNotAvailableError`, `ValidationError`, `ServiceError`.

```python
from whatsapp_sdk import NotConnectedError, WhatsAppClient

try:
    client.send_message(iid, phone, text)
except NotConnectedError:
    print("scan the QR first")
```

## Requirements

Python 3.10+. Server side (FastAPI + Baileys) is operated separately —
see the [main repo](https://github.com/DrkCde15/PyZapp) to self-host with Podman.

## Development

```bash
pip install -e ".[dev]"
python -m pytest   # httpx.MockTransport, no network
```
