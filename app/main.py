"""
Piloto FieldTI AI — Bot de Telegram + Web App para registro de actividades.
Los datos viven en Supabase Postgres (app/db.py) y el admin descarga el
reporte en Excel (app/excel.py).

Punto de entrada principal para Railway y desarrollo local.
Comando de inicio: uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
import datetime as dt
import hmac
import os
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import telegram_client as tg
from app import db, excel, storage, bot_logic
from app.bot_logic import procesar_mensaje_web
from app.state import get_estado
from app.config import ADMIN_TECNICOS, CATALOGO_UBICACION, CATALOGO_ESTADO_REPORTE, ZONA_HORARIA
app = FastAPI(title="FieldTI AI - Telegram Bot")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

SESIONES: dict[int, str] = {}
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
REPORTE_ADMIN_SECRET = os.environ.get("REPORTE_ADMIN_SECRET")
# La web app de pruebas (/ y /api/chat) no tiene login: cualquiera que conozca
# la URL podría escribir como cualquier técnico, incluido el admin. Por eso
# está apagada salvo que se active explícitamente (solo en local / pruebas).
WEBAPP_HABILITADA = os.environ.get("WEBAPP_HABILITADA", "").strip().lower() in ("1", "true", "si", "yes")

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

if not WEBHOOK_SECRET:
    print("[telegram] AVISO: TELEGRAM_WEBHOOK_SECRET no está configurado; "
          "cualquiera podría mandar updates falsos al webhook.")


def _secreto_valido(recibido: str | None, esperado: str | None) -> bool:
    """Compara en tiempo constante. Sin secreto configurado, rechaza (falla
    en cerrado)."""
    if not esperado or not recibido:
        return False
    return hmac.compare_digest(recibido.encode(), esperado.encode())


def _admin_autorizado(request: Request, secret: str) -> bool:
    """Endpoints de admin: acepta el secreto en el header X-Admin-Secret o,
    por comodidad al pegar la URL en el navegador, en ?secret=. Si
    REPORTE_ADMIN_SECRET no está configurado, nadie queda autorizado."""
    recibido = request.headers.get("X-Admin-Secret") or secret
    return _secreto_valido(recibido, REPORTE_ADMIN_SECRET)


def _no_encontrado() -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


_PROHIBIDO = {"status_code": 403, "content": {"status": "forbidden"}}


def _periodo(desde: str = "", hasta: str = "") -> tuple[dt.date, dt.date]:
    """Fechas YYYY-MM-DD → (inicio, fin). Sin fechas: semana calendario
    actual (lunes a domingo). ValueError si son inválidas o están al revés."""
    if desde or hasta:
        inicio, fin = dt.date.fromisoformat(desde), dt.date.fromisoformat(hasta)
        if fin < inicio:
            raise ValueError("fecha final anterior a la inicial")
        return inicio, fin
    hoy = dt.datetime.now(ZONA_HORARIA).date()
    inicio = hoy - dt.timedelta(days=hoy.weekday())
    return inicio, inicio + dt.timedelta(days=6)


# Pasos de la conversación en los que el bot ofrece un catálogo fijo de opciones
CATALOGOS_POR_ESTADO = {
    "ticket": ["Sin ticket"],
    "ubicacion": CATALOGO_UBICACION,
    "actividad": [],
    "estado": CATALOGO_ESTADO_REPORTE,
    "evidencia": ["Omitir"],
    "confirmacion": ["✅ Guardar", "✏️ Editar", "❌ Cancelar"],
    "continuar_pendiente_estado": CATALOGO_ESTADO_REPORTE,
}


@app.get("/")
def index():
    """Health check, o la interfaz web de pruebas si WEBAPP_HABILITADA."""
    index_file = STATIC_DIR / "index.html"
    if WEBAPP_HABILITADA and index_file.exists():
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
    if not WEBAPP_HABILITADA:
        return _no_encontrado()
    try:
        return {"tecnicos": db.listar_tecnicos()}
    except Exception as e:
        print(f"[api/tecnicos] error listando técnicos: {e}")
        return JSONResponse(status_code=503, content={"tecnicos": []})


@app.get("/api/exportar-excel")
def exportar_excel(request: Request, secret: str = "", desde: str = "", hasta: str = ""):
    """Descarga el reporte en Excel del periodo `desde`–`hasta` (YYYY-MM-DD,
    ambos inclusive). Sin fechas, usa la semana calendario actual. Protegido
    con REPORTE_ADMIN_SECRET."""
    if not _admin_autorizado(request, secret):
        return JSONResponse(**_PROHIBIDO)
    try:
        inicio, fin = _periodo(desde, hasta)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "detalle": "Fechas inválidas. Usa desde=YYYY-MM-DD&hasta=YYYY-MM-DD."},
        )
    try:
        contenido, nombre = excel.generar_excel(db.reportes_en_periodo(inicio, fin), inicio, fin)
    except Exception as e:
        print(f"[exportar-excel] error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "detalle": str(e)})
    return Response(
        content=contenido,
        media_type=MIME_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@app.get("/api/codigo-activacion")
def obtener_codigo_activacion(request: Request, secret: str = "", nombre: str = ""):
    """Recupera el código de activación de un técnico que todavía no vinculó
    ningún chat de Telegram. Solo hace falta para el/los técnico(s) semilla
    de config.TECNICOS: como nadie les ha escrito al bot todavía, /nuevo_tecnico
    no puede mandárselo por chat (no existe ese chat). Para cualquier técnico
    agregado después con /nuevo_tecnico, el código ya sale directo en la
    respuesta de ese comando — este endpoint no hace falta. Protegido con
    REPORTE_ADMIN_SECRET."""
    if not _admin_autorizado(request, secret):
        return JSONResponse(**_PROHIBIDO)
    try:
        codigo = db.codigo_activacion_pendiente(nombre)
    except Exception as e:
        print(f"[codigo-activacion] error consultando código: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "detalle": str(e)})
    if not codigo:
        return JSONResponse(
            status_code=404,
            content={"status": "not_found", "detalle": "Técnico no encontrado, o ya activó su cuenta."},
        )
    return {"status": "ok", "nombre": nombre, "codigo": codigo}


@app.post("/api/chat")
def chat(mensaje: MensajeIn):
    if not WEBAPP_HABILITADA:
        return _no_encontrado()
    try:
        tecnicos_validos = db.listar_tecnicos()
    except Exception as e:
        print(f"[api/chat] error listando técnicos: {e}")
        tecnicos_validos = []

    if mensaje.tecnico not in tecnicos_validos:
        return {
            "respuestas": ["Técnico no reconocido. Recarga la página e intenta de nuevo."],
            "opciones": [],
            "esperando": None,
            "es_admin": False,
        }
    respuestas = procesar_mensaje_web(mensaje.tecnico, mensaje.texto)
    estado = get_estado(mensaje.tecnico)
    opciones = CATALOGOS_POR_ESTADO.get(estado.esperando, [])
    es_admin = mensaje.tecnico in ADMIN_TECNICOS
    return {
        "respuestas": respuestas,
        "opciones": opciones,
        "esperando": estado.esperando,
        "es_admin": es_admin,
    }


# Webhook para Telegram Bot
@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    if WEBHOOK_SECRET:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not _secreto_valido(header, WEBHOOK_SECRET):
            print("[telegram] secret_token no coincide; update rechazado.")
            return JSONResponse(status_code=403, content={"status": "forbidden"})

    try:
        update = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"status": "invalid_json"})

    if "message" in update:
        message = update["message"]
        if "photo" in message or "document" in message:
            _manejar_foto(message)
        else:
            _manejar_mensaje(message)
        return {"status": "ok"}

    return {"status": "ignored"}


def _manejar_foto(message: dict):
    """Descarga la foto de Telegram, la sube a Supabase Storage y la anexa al borrador de evidencias."""
    chat_id = message["chat"]["id"]
    tecnico = _tecnico_de(chat_id)
    es_admin = tecnico in ADMIN_TECNICOS if tecnico else False
    if not tecnico:
        tg.send_text(chat_id, "Primero manda /start <código> para identificarte.", con_teclado=False)
        return

    estado = get_estado(tecnico)
    if estado.esperando != "evidencia":
        tg.send_text(chat_id, "Para registrar un nuevo reporte pulsa '➕ Nuevo reporte'.", es_admin=es_admin)
        return

    tg.send_text(chat_id, "Subiendo foto de evidencia…", con_teclado=False)
    try:
        if "photo" in message:
            file_id = message["photo"][-1]["file_id"]
            mime_type = "image/jpeg"
        elif "document" in message:
            doc = message["document"]
            file_id = doc["file_id"]
            mime_type = doc.get("mime_type", "application/octet-stream")
        else:
            tg.send_text(chat_id, "Tipo de archivo no soportado como evidencia.", es_admin=es_admin)
            return

        contenido, file_path = tg.descargar_archivo(file_id)
        nombre_archivo = f"evidencia_{tecnico.replace(' ', '_')}_{file_path.split('/')[-1]}"

        url = storage.upload_evidence(contenido, nombre_archivo, mime_type=mime_type)
        msg_resp = bot_logic.registrar_evidencia_foto(tecnico, url)
        tg.send_opciones(chat_id, msg_resp, ["Omitir", "Continuar"])
    except Exception as e:
        print(f"[evidencia] error subiendo evidencia: {e}")
        tg.send_text(chat_id, "No pude subir la evidencia. Intenta de nuevo en un momento.", es_admin=es_admin)


def _tecnico_de(chat_id: int) -> str | None:
    """Técnico identificado en este chat. SESIONES es solo una caché en
    memoria (se pierde si el bot se reinicia); la fuente de verdad durable
    es el chat_id vinculado en la tabla `tecnicos` (ver db.tecnico_por_chat_id)."""
    tecnico = SESIONES.get(chat_id)
    if tecnico:
        return tecnico
    try:
        tecnico = db.tecnico_por_chat_id(chat_id)
        if tecnico:
            SESIONES[chat_id] = tecnico
    except Exception as e:
        print(f"[auth] error consultando técnico por chat_id: {e}")
    return tecnico


def _manejar_mensaje(message: dict):
    chat_id = message["chat"]["id"]
    texto = message.get("text", "")

    if not texto.strip():
        tg.send_text(chat_id, "Por ahora solo proceso mensajes de texto y fotos de evidencia.")
        return

    comando = texto.split()[0].lower()
    if comando == "/start":
        _manejar_start(chat_id, texto)
        return

    tecnico = _tecnico_de(chat_id)
    if not tecnico:
        tg.send_text(chat_id, "Primero manda /start <código> para identificarte.", con_teclado=False)
        return

    es_admin = tecnico in ADMIN_TECNICOS

    if comando == "/nuevo_tecnico":
        _admin_nuevo_tecnico(chat_id, tecnico, texto)
        return
    if comando == "/reporte" or bot_logic._remover_acentos(texto) == "exportar excel":
        _admin_exportar_excel(chat_id, tecnico, texto)
        return

    texto_normalizado = tg.normalizar_texto_boton(texto)
    respuestas = procesar_mensaje_web(tecnico, texto_normalizado)
    if not respuestas:
        return

    for r in respuestas[:-1]:
        tg.send_text(chat_id, r, es_admin=es_admin)

    opciones = CATALOGOS_POR_ESTADO.get(get_estado(tecnico).esperando)
    if opciones:
        tg.send_opciones(chat_id, respuestas[-1], opciones)
    else:
        tg.send_text(chat_id, respuestas[-1], es_admin=es_admin)


def _manejar_start(chat_id: int, texto: str):
    tecnico_existente = _tecnico_de(chat_id)
    if tecnico_existente:
        es_admin = tecnico_existente in ADMIN_TECNICOS
        tg.send_text(chat_id, f"Hola de nuevo, {tecnico_existente.split(' ')[0]}. Usa los botones o escribe libremente.", es_admin=es_admin)
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

    try:
        nombre = db.activar_tecnico_por_codigo(codigo, chat_id)
    except Exception as e:
        print(f"[start] error activando técnico: {e}")
        tg.send_text(chat_id, "Hubo un error de conexión con la base de datos. Intenta más tarde.", con_teclado=False)
        return

    if not nombre:
        tg.send_text(chat_id, "Código inválido o ya usado. Pídele al admin un código nuevo.", con_teclado=False)
        return

    SESIONES[chat_id] = nombre
    es_admin = nombre in ADMIN_TECNICOS
    tg.send_text(chat_id, f"Hola, {nombre.split(' ')[0]}. Tu cuenta quedó activada. Usa los botones o escribe libremente.", es_admin=es_admin)


def _admin_nuevo_tecnico(chat_id: int, tecnico: str, texto: str):
    if tecnico not in ADMIN_TECNICOS:
        tg.send_text(chat_id, "No tienes permiso para usar este comando.", con_teclado=False)
        return
    nombre = texto.removeprefix("/nuevo_tecnico").strip()
    if not nombre:
        tg.send_text(chat_id, "Usa: /nuevo_tecnico Nombre Completo", con_teclado=False)
        return
    try:
        codigo = db.agregar_tecnico(nombre)
    except Exception as e:
        print(f"[nuevo_tecnico] error: {e}")
        tg.send_text(chat_id, "No pude agregar al técnico por un error con la base de datos. Intenta más tarde.", es_admin=True)
        return

    if not codigo:
        tg.send_text(chat_id, f"{nombre} ya estaba en la lista de técnicos.", es_admin=True)
        return
    tg.send_text(
        chat_id,
        f"Técnico agregado: {nombre}.\n"
        f"Mándale este código para que active su cuenta (funciona una sola vez):\n"
        f"/start {codigo}",
        es_admin=True,
    )


def _admin_exportar_excel(chat_id: int, tecnico: str, texto: str):
    """/reporte → semana actual; /reporte AAAA-MM-DD AAAA-MM-DD → ese periodo.
    El botón '📊 Exportar Excel' equivale a /reporte sin fechas."""
    if tecnico not in ADMIN_TECNICOS:
        tg.send_text(chat_id, "No tienes permiso para usar este comando.", con_teclado=False)
        return
    partes = texto.split()[1:] if texto.split()[0].lower() == "/reporte" else []
    try:
        if len(partes) not in (0, 2):
            raise ValueError
        inicio, fin = _periodo(*partes)
    except ValueError:
        tg.send_text(chat_id, "Usa: /reporte  o  /reporte AAAA-MM-DD AAAA-MM-DD", es_admin=True)
        return

    tg.send_text(chat_id, f"Generando Excel del {inicio.isoformat()} al {fin.isoformat()}…", con_teclado=False)
    try:
        reportes = db.reportes_en_periodo(inicio, fin)
        contenido, nombre = excel.generar_excel(reportes, inicio, fin)
    except Exception as e:
        print(f"[exportar_excel] error: {e}")
        tg.send_text(chat_id, "No pude generar el Excel. Intenta más tarde.", es_admin=True)
        return
    tg.send_document(
        chat_id, contenido, nombre,
        caption=f"📊 {len(reportes)} reporte(s) del {inicio.isoformat()} al {fin.isoformat()}.\n"
                f"Otro periodo: /reporte AAAA-MM-DD AAAA-MM-DD",
        mime_type=MIME_XLSX,
    )
