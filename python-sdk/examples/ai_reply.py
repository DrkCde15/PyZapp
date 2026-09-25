"""Enable AI auto-reply on an instance. Usage:
    API_KEY=... AI_API_KEY=... python examples/ai_reply.py <instance_id>
"""

import os
import sys

from whatsapp_sdk import WhatsAppClient

(instance_id,) = sys.argv[1:]

with WhatsAppClient(
    base_url=os.environ.get("API_URL", "http://localhost:8000"),
    api_key=os.environ["API_KEY"],
) as client:
    cfg = client.set_ai(
        instance_id,
        provider=os.environ.get("AI_PROVIDER", "groq"),
        api_key=os.environ.get("AI_API_KEY"),
        system_prompt="Você é um atendente objetivo. Responda em poucas linhas.",
        cooldown_s=30,
    )
    print("AI enabled:", cfg.provider, cfg.model)
