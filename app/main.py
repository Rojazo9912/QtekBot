"""
Piloto FieldTI AI — Bot de Telegram + Web App para registro de actividades en Google Sheets.

Punto de entrada principal para Railway y desarrollo local.
Comando de inicio: uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
import datetime as dt
import os
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import telegram_client as tg
from app import sheets, storage
from app.bot_logic import procesar_mensaje_web
from app.config import ADMIN_TECNICOS, CATALOGO_AREA, CATALOGO_PRIORIDAD, CATALOGO_TIPO_FALLA
from app.state import get_estado

app = FastAPI(title="FieldTI AI - Telegram Bot")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# chat_id de Telegram -> nombre de técnico. Caché en memoria (se pierde si el
# bot se reinicia, ver aviso en app/state.py); la fuente de verdad durable es
# el chat_id ya vinculado en la hoja "Técnicos" (ver _tecnico_de más abajo).
SESIONES: dict[int, str] = {}

WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
REPORTE_ADMIN_SECRET = os.environ.get("REPORTE_ADMIN_SECRET")

# URL pública de este servicio (la misma que usas para el webhook de
# Telegram, ej. https://tu-app.up.railway.app). Sirve para armar el link de
# /evidencia/ que usan las miniaturas =IMAGE() del Sheet — ver _manejar_foto.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

# Pasos de la conversación en los que el bot ofrece un catálogo fijo de
# opciones (en vez del teclado persistente de atajos).
CATALOGOS_POR_ESTADO = {
    "area": CATALOGO_AREA,
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
    return {"tecnicos": sheets.listar_tecnicos()}


@app.get("/evidencia/{ruta:path}")
def servir_evidencia(ruta: str):
    """Re-sirve un archivo de Supabase Storage sin el header X-Robots-Tag que
    Supabase agrega por default: ese header es respetado por el fetcher de
    imágenes de Google Sheets (=IMAGE()) y hace que la miniatura no
    renderice, aunque la URL directa de Supabase funcione bien en el
    navegador. Solo se usa para las miniaturas del Sheet — el link "de
    verdad" que se guarda en la columna Evidencias sigue siendo la URL
    directa de Supabase."""
    try:
        contenido, mime_type = storage.download_evidence(ruta)
    except Exception:
        return JSONResponse(status_code=404, content={"status": "not_found"})
    return Response(content=contenido, media_type=mime_type)


@app.get("/api/reporte-periodo")
def fijar_periodo_reporte(secret: str = "", desde: str = "", hasta: str = ""):
    """Fija el periodo del reporte contractual (celdas C13/E13 de 'Reporte
    PDF'): con eso, las fórmulas de esa hoja recalculan solas la tabla de
    Actividades, % de Avance Real y Tickets Atendidos por técnico a partir de
    'Registro de Tickets' — no hay nada más que reescribir desde Python.
    Pensado para que un admin de Qtek lo dispare a mano (pegando la URL en el
    navegador) antes de mandar el reporte a First Majestic — no se llama
    desde el chat.

    Sin `desde`/`hasta` (formato YYYY-MM-DD), usa la semana calendario actual
    (lunes a domingo). Protegido con REPORTE_ADMIN_SECRET.
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
    sheets.set_periodo_reporte(fecha_inicio, fecha_fin)
    return {"status": "ok", "periodo": f"{fecha_inicio.isoformat()} a {fecha_fin.isoformat()}"}


@app.get("/api/codigo-activacion")
def obtener_codigo_activacion(secret: str = "", nombre: str = ""):
    """Recupera el código de activación de un técnico que todavía no vinculó
    ningún chat de Telegram. Solo hace falta para el/los técnico(s) semilla
    de config.TECNICOS: como nadie les ha escrito al bot todavía, /nuevo_tecnico
    no puede mandárselo por chat (no existe ese chat). Para cualquier técnico
    agregado después con /nuevo_tecnico, el código ya sale directo en la
    respuesta de ese comando — este endpoint no hace falta. Protegido con
    REPORTE_ADMIN_SECRET, igual que /api/reporte-periodo."""
    if REPORTE_ADMIN_SECRET and secret != REPORTE_ADMIN_SECRET:
        return JSONResponse(status_code=403, content={"status": "forbidden"})
    codigo = sheets.codigo_activacion_pendiente(nombre)
    if not codigo:
        return JSONResponse(
            status_code=404,
            content={"status": "not_found", "detalle": "Técnico no encontrado, o ya activó su cuenta."},
        )
    return {"status": "ok", "nombre": nombre, "codigo": codigo}


@app.post("/api/chat")
def chat(mensaje: MensajeIn):
    if mensaje.tecnico not in sheets.listar_tecnicos():
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

    if "message" in update:
        message = update["message"]
        if "photo" in message or "document" in message:
            _manejar_foto(message)
        else:
            _manejar_mensaje(message)
        return {"status": "ok"}

    return {"status": "ignored"}


def _manejar_foto(message: dict):
    """Descarga la foto/documento de Telegram y la sube a Supabase Storage.
    Guarda la URL pública permanente en la columna Evidencias del Sheet.
    """
    chat_id = message["chat"]["id"]
    tecnico = _tecnico_de(chat_id)
    if not tecnico:
        tg.send_text(chat_id, "Primero manda /start <código> para identificarte.", con_teclado=False)
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
        ruta = storage.ruta_normalizada(nombre_archivo)
        url_miniatura = f"{PUBLIC_BASE_URL}/evidencia/{ruta}" if PUBLIC_BASE_URL else None
        guardado = sheets.add_evidence(estado.folio_activo, url, mime_type=mime_type, link_miniatura=url_miniatura)

        if guardado:
            tg.send_text(chat_id, f"Evidencia guardada en la actividad {estado.folio_activo}. ✅")
        else:
            tg.send_text(chat_id, f"La evidencia se subió, pero no encontré la fila del folio {estado.folio_activo} en el Sheet. Link: {url}")
    except Exception as e:
        print(f"[evidencia] error subiendo evidencia: {e}")
        tg.send_text(chat_id, f"No pude subir la evidencia. Error: {e}")



def _tecnico_de(chat_id: int) -> str | None:
    """Técnico identificado en este chat. SESIONES es solo una caché en
    memoria (se pierde si el bot se reinicia); la fuente de verdad durable
    es el chat_id ya vinculado en la hoja 'Técnicos' (ver
    sheets.tecnico_por_chat_id)."""
    tecnico = SESIONES.get(chat_id)
    if tecnico:
        return tecnico
    tecnico = sheets.tecnico_por_chat_id(chat_id)
    if tecnico:
        SESIONES[chat_id] = tecnico
    return tecnico


def _manejar_mensaje(message: dict):
    chat_id = message["chat"]["id"]
    texto = message.get("text", "")

    if texto.startswith("/start"):
        _manejar_start(chat_id, texto)
        return

    tecnico = _tecnico_de(chat_id)
    if not tecnico:
        tg.send_text(chat_id, "Primero manda /start <código> para identificarte.", con_teclado=False)
        return

    if texto.startswith("/nuevo_tecnico"):
        _admin_nuevo_tecnico(chat_id, tecnico, texto)
        return
    if texto.startswith("/reporte"):
        _admin_generar_reporte(chat_id, tecnico, texto)
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


def _manejar_start(chat_id: int, texto: str):
    """/start [código]. Tres casos:
    1. Este chat ya está vinculado a un técnico (columna Chat ID de
       'Técnicos') — lo re-identifica sin pedir nada.
    2. Trae un código de activación válido — vincula este chat a ese
       técnico para siempre (lo consume, no sirve dos veces) y lo identifica.
    3. Cualquier otro caso — no hay forma de identificarse sin un código
       real, así que no se ofrece ninguna lista de nombres para elegir (eso
       es justo lo que permitiría a cualquiera hacerse pasar por otro
       técnico)."""
    tecnico_existente = _tecnico_de(chat_id)
    if tecnico_existente:
        tg.send_text(chat_id, f"Hola de nuevo, {tecnico_existente.split(' ')[0]}. Usa los botones o escribe libremente.")
        return

    partes = texto.split(maxsplit=1)
    codigo = partes[1].strip() if len(partes) > 1 else ""
    if not codigo:
        tg.send_text(
            chat_id,
            "Necesitas un código de activación para usar este bot. Pídeselo al admin y mándalo así: /start CÓDIGO",
            con_teclado=False,
        )
        return

    nombre = sheets.activar_tecnico_por_codigo(codigo, chat_id)
    if not nombre:
        tg.send_text(chat_id, "Código inválido o ya usado. Pídele al admin un código nuevo.", con_teclado=False)
        return

    SESIONES[chat_id] = nombre
    tg.send_text(chat_id, f"Hola, {nombre.split(' ')[0]}. Tu cuenta quedó activada. Usa los botones o escribe libremente.")


def _admin_nuevo_tecnico(chat_id: int, tecnico: str, texto: str):
    """/nuevo_tecnico Nombre Completo — solo ADMIN_TECNICOS. Da de alta un
    técnico en la hoja 'Técnicos' del Sheet con un código de activación de
    un solo uso; el admin se lo reenvía al técnico por fuera del bot
    (WhatsApp, en persona) para que active su cuenta con /start CÓDIGO."""
    if tecnico not in ADMIN_TECNICOS:
        tg.send_text(chat_id, "No tienes permiso para usar este comando.", con_teclado=False)
        return
    nombre = texto.removeprefix("/nuevo_tecnico").strip()
    if not nombre:
        tg.send_text(chat_id, "Usa: /nuevo_tecnico Nombre Completo", con_teclado=False)
        return
    codigo = sheets.agregar_tecnico(nombre)
    if not codigo:
        tg.send_text(chat_id, f"{nombre} ya estaba en la lista de técnicos.")
        return
    tg.send_text(
        chat_id,
        f"Técnico agregado: {nombre}.\n"
        f"Mándale este código para que active su cuenta (funciona una sola vez):\n"
        f"/start {codigo}",
    )


def _admin_generar_reporte(chat_id: int, tecnico: str, texto: str):
    """/reporte [AAAA-MM-DD AAAA-MM-DD] — solo ADMIN_TECNICOS. Fija el
    periodo del reporte contractual en 'Reporte PDF'; las fórmulas de esa
    hoja recalculan solas. El PDF real se descarga desde Google Sheets
    (Archivo > Descargar > PDF) — el bot no genera el archivo."""
    if tecnico not in ADMIN_TECNICOS:
        tg.send_text(chat_id, "No tienes permiso para usar este comando.", con_teclado=False)
        return
    partes = texto.split()[1:]
    try:
        if len(partes) == 2:
            fecha_inicio = dt.date.fromisoformat(partes[0])
            fecha_fin = dt.date.fromisoformat(partes[1])
        elif not partes:
            hoy = dt.datetime.now(sheets.ZONA_HORARIA).date()
            fecha_inicio = hoy - dt.timedelta(days=hoy.weekday())
            fecha_fin = fecha_inicio + dt.timedelta(days=6)
        else:
            raise ValueError
    except ValueError:
        tg.send_text(chat_id, "Usa: /reporte  o  /reporte AAAA-MM-DD AAAA-MM-DD", con_teclado=False)
        return
    sheets.set_periodo_reporte(fecha_inicio, fecha_fin)
    tg.send_text(
        chat_id,
        f"Reporte listo para el periodo {fecha_inicio.isoformat()} a {fecha_fin.isoformat()}. "
        "Descárgalo desde Google Sheets: hoja 'Reporte PDF' > Archivo > Descargar > PDF.",
    )

