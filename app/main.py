"""
Piloto FieldTI AI — Bot de Telegram + Web App para registro de actividades en Google Sheets.

Punto de entrada principal para Railway y desarrollo local.
Comando de inicio: uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
import datetime as dt
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import telegram_client as tg
from app import sheets, storage
from app.bot_logic import procesar_mensaje_web
from app.config import CATALOGO_PRIORIDAD, CATALOGO_TIPO_FALLA, TECNICOS
from app.state import get_estado

app = FastAPI(title="FieldTI AI - Telegram Bot")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# chat_id de Telegram -> nombre de técnico. En memoria (ver aviso en app/state.py)
SESIONES: dict[int, str] = {}

WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
REPORTE_ADMIN_SECRET = os.environ.get("REPORTE_ADMIN_SECRET")

# Pasos de la conversación en los que el bot ofrece un catálogo fijo de
# opciones (en vez del teclado persistente de atajos).
CATALOGOS_POR_ESTADO = {
    "tipo_falla": CATALOGO_TIPO_FALLA,
    "prioridad": CATALOGO_PRIORIDAD,
}


@app.get("/")
def index():
    """Health check o interfaz web local si existe."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"status": "ok", "service": "FieldTI AI Telegram Bot"}


@app.get("/health")
def health():
    return {"status": "healthy"}


# API para la Web App de pruebas local
class MensajeIn(BaseModel):
    tecnico: str
    texto: str


@app.get("/api/tecnicos")
def listar_tecnicos():
    return {"tecnicos": TECNICOS}


@app.get("/api/reporte-semanal")
def generar_reporte_semanal(secret: str = "", desde: str = "", hasta: str = ""):
    """Reconstruye las pestañas 'Resumen Semanal' y 'Reporte Semanal' a partir
    de lo capturado en 'Reporte Diario'. Pensado para que un admin de Qtek lo
    dispare a mano (pegando la URL en el navegador) antes de mandar el
    reporte semanal a First Majestic — no se llama desde el chat.

    Sin `desde`/`hasta` (formato YYYY-MM-DD), usa la semana calendario actual
    (lunes a domingo). Protegido con REPORTE_ADMIN_SECRET porque reescribe
    esas dos pestañas por completo.
    """
    if REPORTE_ADMIN_SECRET and secret != REPORTE_ADMIN_SECRET:
        return JSONResponse(status_code=403, content={"status": "forbidden"})
    try:
        if desde and hasta:
            fecha_inicio = dt.date.fromisoformat(desde)
            fecha_fin = dt.date.fromisoformat(hasta)
        else:
            hoy = dt.datetime.now(sheets.ZONA_HORARIA).date()
            fecha_inicio = hoy - dt.timedelta(days=hoy.weekday())
            fecha_fin = fecha_inicio + dt.timedelta(days=6)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "detalle": "Fechas inválidas. Usa formato YYYY-MM-DD."},
        )
    resumen = sheets.generar_reporte_semanal(fecha_inicio, fecha_fin)
    return {"status": "ok", **resumen}


@app.post("/api/chat")
def chat(mensaje: MensajeIn):
    if mensaje.tecnico not in TECNICOS:
        return {"respuestas": ["Técnico no reconocido. Recarga la página e intenta de nuevo."]}
    respuestas = procesar_mensaje_web(mensaje.tecnico, mensaje.texto)
    return {"respuestas": respuestas}


# Webhook para Telegram Bot
@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    if WEBHOOK_SECRET:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if header != WEBHOOK_SECRET:
            print(f"[telegram] secret_token no coincide. Recibido={header!r}")
            return JSONResponse(status_code=403, content={"status": "forbidden"})

    update = await request.json()

    if "callback_query" in update:
        _manejar_seleccion_tecnico(update["callback_query"])
        return {"status": "ok"}

    if "message" in update:
        message = update["message"]
        if "photo" in message or "document" in message:
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
    """Descarga la foto/documento de Telegram y la sube a Supabase Storage.
    Guarda la URL pública permanente en la columna Evidencias del Sheet.
    """
    chat_id = message["chat"]["id"]
    tecnico = SESIONES.get(chat_id)
    if not tecnico:
        tg.send_text(chat_id, "Primero manda /start para identificarte.", con_teclado=False)
        return

    estado = get_estado(tecnico)
    if not estado.folio_activo:
        tg.send_text(chat_id, "No tienes ninguna actividad activa a la cual adjuntar esta evidencia. Inicia o reanuda una actividad primero.")
        return

    tg.send_text(chat_id, "Subiendo evidencia…", con_teclado=False)
    try:
        if "photo" in message:
            file_id = message["photo"][-1]["file_id"]
            mime_type = "image/jpeg"
        elif "document" in message:
            doc = message["document"]
            file_id = doc["file_id"]
            mime_type = doc.get("mime_type", "application/octet-stream")
        else:
            tg.send_text(chat_id, "Tipo de archivo no soportado como evidencia.")
            return

        contenido, file_path = tg.descargar_archivo(file_id)
        nombre_archivo = f"{estado.folio_activo}_{file_path.split('/')[-1]}"

        url = storage.upload_evidence(contenido, nombre_archivo, mime_type=mime_type)
        guardado = sheets.add_evidence(estado.folio_activo, url, mime_type=mime_type)

        if guardado:
            tg.send_text(chat_id, f"Evidencia guardada en la actividad {estado.folio_activo}. ✅")
        else:
            tg.send_text(chat_id, f"La evidencia se subió, pero no encontré la fila del folio {estado.folio_activo} en el Sheet. Link: {url}")
    except Exception as e:
        print(f"[evidencia] error subiendo evidencia: {e}")
        tg.send_text(chat_id, f"No pude subir la evidencia. Error: {e}")



def _manejar_mensaje(message: dict):
    chat_id = message["chat"]["id"]
    texto = message.get("text", "")

    if texto == "/start":
        if len(TECNICOS) == 1:
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
    if not respuestas:
        return

    for r in respuestas[:-1]:
        tg.send_text(chat_id, r)

    opciones = CATALOGOS_POR_ESTADO.get(get_estado(tecnico).esperando)
    if opciones:
        tg.send_opciones(chat_id, respuestas[-1], opciones)
    else:
        tg.send_text(chat_id, respuestas[-1])

