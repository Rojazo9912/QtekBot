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
from app import sheets, drive
from app.bot_logic import procesar_mensaje_web
from app.state import get_estado

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
            print(f"[telegram] secret_token no coincide. Recibido={header!r}")
            return {"status": "forbidden"}

    update = await request.json()

    if "callback_query" in update:
        _manejar_seleccion_tecnico(update["callback_query"])
        return {"status": "ok"}

    if "message" in update:
        message = update["message"]
        if "photo" in message:
            _manejar_foto(message)
        else:
            _manejar_mensaje(message)
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


def _manejar_foto(message: dict):
    chat_id = message["chat"]["id"]
    tecnico = SESIONES.get(chat_id)
    if not tecnico:
        tg.send_text(chat_id, "Primero manda /start para identificarte.", con_teclado=False)
        return

    estado = get_estado(tecnico)
    if not estado.folio_activo:
        tg.send_text(chat_id, "No tienes ninguna actividad activa a la cual adjuntar esta foto. Inicia o reanuda una actividad primero.")
        return

    tg.send_text(chat_id, "Subiendo evidencia…", con_teclado=False)
    try:
        # Telegram manda varios tamaños de la misma foto; usamos la más grande (última).
        file_id = message["photo"][-1]["file_id"]
        contenido, file_path = tg.descargar_foto(file_id)
        nombre_archivo = f"{estado.folio_activo}_{file_path.split('/')[-1]}"
        link = drive.upload_photo(contenido, nombre_archivo)
        guardado = sheets.add_evidence(estado.folio_activo, link)
        if guardado:
            tg.send_text(chat_id, f"Evidencia guardada en la actividad {estado.folio_activo}. ✅")
        else:
            tg.send_text(chat_id, f"La foto se subió a Drive, pero no encontré la fila del folio {estado.folio_activo} en el Sheet para anexarla. Revísalo a mano: {link}")
    except Exception as e:
        print(f"[evidencia] error subiendo foto: {e}")
        tg.send_text(chat_id, "No pude subir la evidencia. Intenta de nuevo en un momento; si sigue fallando, avísale a tu supervisor.")


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
