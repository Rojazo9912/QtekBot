"""
Envío de mensajes salientes usando WhatsApp Cloud API (Meta), directo, sin Twilio.

Requiere en Meta for Developers:
- Una app de tipo "Business" con el producto "WhatsApp" agregado.
- WHATSAPP_TOKEN: token de acceso (temporal de prueba o permanente de una System User).
- WHATSAPP_PHONE_ID: el "Phone number ID" que aparece en la consola de WhatsApp > API Setup.
"""
import os
import httpx

TOKEN = os.environ["WHATSAPP_TOKEN"]
PHONE_ID = os.environ["WHATSAPP_PHONE_ID"]
API_URL = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"


def send_text(to: str, body: str) -> None:
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    with httpx.Client(timeout=10) as http:
        r = http.post(API_URL, headers=headers, json=payload)
        if r.status_code >= 400:
            # No tumbamos el webhook por un error de envío; solo lo dejamos en logs.
            print(f"[whatsapp] error {r.status_code}: {r.text}")
