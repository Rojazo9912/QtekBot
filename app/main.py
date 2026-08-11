"""
Piloto FieldTI AI — bot de WhatsApp que llena el reporte en Google Sheets.

Este archivo YA NO tiene la lógica de conversación adentro — vive en
app/bot_logic.py (procesar_mensaje_web) y aquí solo se adapta al canal
WhatsApp: se recibe el webhook y se manda cada respuesta con whatsapp.send_text.
Esto es para que WhatsApp y la web app (app/webapp.py) compartan EXACTAMENTE
la misma lógica de negocio y no se puedan desincronizar entre sí.

NO cubre en este piloto (a propósito, para no inflar el alcance):
- Evidencias (fotos/audios).
- Dashboard — el propio Google Sheet ES el dashboard del piloto.
- Multi-actividad simultánea real — una actividad activa a la vez por técnico.
"""
import os
from fastapi import FastAPI, Request, Response

from app import whatsapp
from app.bot_logic import procesar_mensaje_web

app = FastAPI()

VERIFY_TOKEN = os.environ["WHATSAPP_VERIFY_TOKEN"]

# Mapeo temporal número -> nombre de técnico para el piloto (2-3 personas).
# En producción esto debe salir de una tabla "technicians", no de un dict fijo.
TECNICOS = {
    "526182692461": "Miguel Abraham Lopez Ortiz",
}


@app.get("/webhook")
def verify(request: Request):
    """Meta llama esto una sola vez al configurar el webhook en su consola."""
    params = request.query_params
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receive(request: Request):
    payload = await request.json()
    try:
        entry = payload["entry"][0]["changes"][0]["value"]
        if "messages" not in entry:
            return {"status": "ignored"}  # son eventos de "status" (entregado/leído), no mensajes
        msg = entry["messages"][0]
        contacts = entry.get("contacts", [])
        from_number = contacts[0]["wa_id"] if contacts else msg["from"]
        texto = msg.get("text", {}).get("body", "")
    except (KeyError, IndexError):
        return {"status": "ignored"}

    tecnico = TECNICOS.get(from_number)
    if not tecnico:
        whatsapp.send_text(from_number, "Tu número no está registrado como técnico. Contacta a tu supervisor.")
        return {"status": "unregistered"}

    respuestas = procesar_mensaje_web(tecnico, texto)
    for r in respuestas:
        whatsapp.send_text(from_number, r)
    return {"status": "ok"}
