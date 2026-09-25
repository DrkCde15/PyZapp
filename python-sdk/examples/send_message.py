"""Connect and send your first message. Usage:
    API_KEY=... API_URL=http://localhost:8000 python examples/send_message.py
"""

import os
import time

from whatsapp_sdk import NotConnectedError, WhatsAppClient

client = WhatsAppClient(
    base_url=os.environ.get("API_URL", "http://localhost:8000"),
    api_key=os.environ["API_KEY"],
)

inst = client.create_instance()
print("instance:", inst.instance_id)

client.print_qr(inst.instance_id)
input("Scan the QR, then press Enter...")

for _ in range(12):
    if client.get_status(inst.instance_id).connected:
        break
    time.sleep(5)
else:
    raise SystemExit("Instance did not connect in time")

try:
    sent = client.send_message(inst.instance_id, os.environ["TO_PHONE"], "Olá! via PyZapp")
    print("sent:", sent.message_id)
except NotConnectedError:
    raise SystemExit("Not connected — scan the QR first")
