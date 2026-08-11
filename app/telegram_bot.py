"""
Bot de Telegram para el piloto FieldTI AI — misma lógica de negocio que
WhatsApp y la web app (app/bot_logic.py), pero con la sensación de app de
chat nativa: notificaciones push, historial, teclado de atajos persistente.

Flujo:
1. El técnico busca el bot en Telegram y le manda /start.
2. El bot le muestra botones con los nombres de los técnicos del piloto.
3. Al elegir su nombre, ese chat_id queda ligado a ese técnico (en memoria —
   misma limitación documentada en app/state.py: si Railway reinicia, hay
   que volver a mandar /start, pero las actividades ya guardadas no se pierden).
4. De ahí en adelante, escribe libre o usa los botones de acciones rápidas.
"""
import os
from fastapi import FastAPI, Request

from app import telegram_client as tg
from app.bot_logic import procesar_mensaje_web

app = FastAPI()

# Mismo piloto de 2-3 técnicos. Cámbialo por los nombres reales de tu equipo.
TECNICOS = ["Miguel Abraham Lopez Ortiz"]

# chat_id de Telegram -> nombre de técnico. En memoria, ver limitación arriba.
SESIONES: dict[int, str] = {}

WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")  # opcional pero recomendado


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    if WEBHOOK_SECRET:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if header != WEBHOOK_SECRET:
            return {"status": "forbidden"}

    update = await request.json()

    if "callback_query" in update:
        _manejar_seleccion_tecnico(update["callback_query"])
        return {"status": "ok"}

    if "message" in update:
        _manejar_mensaje(update["message"])
        return {"status": "ok"}

    return {"status": "ignored"}


def _manejar_seleccion_tecnico(callback_query: dict):
    chat_id = callback_query["message"]["chat"]["id"]
    data = callback_query.get("data", "")
    tg.responder_callback(callback_query["id"])
    if not data.startswith("login:"):
        return
    nombre = data.removeprefix("login:")
    if nombre not in TECNICOS:
        tg.send_text(chat_id, "Técnico no reconocido. Manda /start de nuevo.", con_teclado=False)
        return
    SESIONES[chat_id] = nombre
    tg.send_text(chat_id, f"Hola, {nombre.split(' ')[0]}. Usa los botones o escribe libremente.")


def _manejar_mensaje(message: dict):
    chat_id = message["chat"]["id"]
    texto = message.get("text", "")

    if texto == "/start":
        if len(TECNICOS) == 1:
            # Con un solo técnico en el piloto, nos ahorramos el paso de elegir.
            SESIONES[chat_id] = TECNICOS[0]
            tg.send_text(chat_id, f"Hola, {TECNICOS[0].split(' ')[0]}. Usa los botones o escribe libremente.")
        else:
            tg.send_seleccion_tecnico(chat_id, TECNICOS)
        return

    tecnico = SESIONES.get(chat_id)
    if not tecnico:
        tg.send_text(chat_id, "Primero manda /start para identificarte.", con_teclado=False)
        return

    texto_normalizado = tg.normalizar_texto_boton(texto)
    respuestas = procesar_mensaje_web(tecnico, texto_normalizado)
    for r in respuestas:
        tg.send_text(chat_id, r)
