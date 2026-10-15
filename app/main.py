"""
Piloto FieldTI AI — Bot de Telegram + Web App para registro de actividades.
Los datos viven en Supabase Postgres (app/db.py) y el admin descarga el
reporte en Excel (app/excel.py) y fotos en ZIP (app/zip_export.py).

Punto de entrada principal para Railway y desarrollo local.
Comando de inicio: uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
import asyncio
import datetime as dt
import hmac
import io
import os
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image

from app import telegram_client as tg
from app import db, excel, storage, bot_logic
from app.bot_logic import procesar_mensaje_web
from app.state import get_estado
from app.config import ADMIN_TECNICOS, CATALOGO_UBICACION, CATALOGO_ESTADO_REPORTE, ZONA_HORARIA
from app.watermark import aplicar_marca_de_agua
from app.zip_export import generar_zip_evidencias

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
MIME_ZIP = "application/zip"

if not WEBHOOK_SECRET:
    print("[telegram] AVISO: TELEGRAM_WEBHOOK_SECRET no está configurado; "
          "cualquiera podría mandar updates falsos al webhook.")


def _secreto_valido(recibido: str | None, esperado: str | None) -> bool:
    """Compara en tiempo constante. Sin secreto configurado, rechaza (falla en cerrado)."""
    if not esperado or not recibido:
        return False
    return hmac.compare_digest(recibido.encode(), esperado.encode())


def _admin_autorizado(request: Request, secret: str = "") -> bool:
    """Endpoints de admin: acepta el secreto en el header X-Admin-Secret o,
    por comodidad al pegar la URL en el navegador, en ?secret=. Si
    REPORTE_ADMIN_SECRET no está configurado, nadie queda autorizado."""
    recibido = request.headers.get("X-Admin-Secret") or request.query_params.get("secret")
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
    "departamento": [],
    "ubicacion": CATALOGO_UBICACION,
    "actividad": [],
    "estado": CATALOGO_ESTADO_REPORTE,
    "evidencia": ["Omitir"],
    "confirmacion": ["✅ Guardar", "✏️ Editar", "❌ Cancelar"],
    "editar_campo_seleccion": ["🎫 Ticket", "🏢 Departamento", "📍 Zona", "📝 Actividad", "📊 Estado", "📷 Fotos", "🔄 Reiniciar todo", "↩️ Volver"],
    "editar_fotos": ["🗑️ Borrar fotos", "➕ Agregar fotos", "↩️ Volver"],
    "editar_estado": CATALOGO_ESTADO_REPORTE,
    "continuar_pendiente_estado": CATALOGO_ESTADO_REPORTE,
}


def _obtener_opciones(esperando: str | None) -> list[str]:
    if not esperando:
        return []
    if esperando in ("departamento", "editar_departamento"):
        try:
            return db.listar_departamentos()
        except Exception:
            return ["Infraestructura"]
    if esperando in ("ubicacion", "editar_zona"):
        try:
            return db.listar_zonas() + ["Otra"]
        except Exception:
            return CATALOGO_UBICACION + ["Otra"]
    return CATALOGOS_POR_ESTADO.get(esperando, [])


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
def exportar_excel(request: Request, desde: str = "", hasta: str = ""):
    """Descarga el reporte en Excel del periodo `desde`–`hasta` (YYYY-MM-DD,
    ambos inclusive). Sin fechas, usa la semana calendario actual. Protegido
    con REPORTE_ADMIN_SECRET."""
    if not _admin_autorizado(request, ""):
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


@app.get("/api/exportar-fotos")
def exportar_fotos(request: Request, desde: str = "", hasta: str = ""):
    """Descarga un archivo ZIP con las fotos de evidencias del periodo.
    Protegido con REPORTE_ADMIN_SECRET."""
    if not _admin_autorizado(request, ""):
        return JSONResponse(**_PROHIBIDO)
    try:
        inicio, fin = _periodo(desde, hasta)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "detalle": "Fechas inválidas. Usa desde=YYYY-MM-DD&hasta=YYYY-MM-DD."},
        )
    try:
        reportes = db.reportes_en_periodo(inicio, fin)
        contenido, nombre = generar_zip_evidencias(reportes, inicio, fin)
    except Exception as e:
        print(f"[exportar-fotos] error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "detalle": str(e)})
    return Response(
        content=contenido,
        media_type=MIME_ZIP,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@app.get("/api/codigo-activacion")
def obtener_codigo_activacion(request: Request, nombre: str = ""):
    """Recupera el código de activación de un técnico que todavía no vinculó
    ningún chat de Telegram."""
    if not _admin_autorizado(request, ""):
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
    opciones = _obtener_opciones(estado.esperando)
    es_admin = db.es_admin(mensaje.tecnico)
    return {
        "respuestas": respuestas,
        "opciones": opciones,
        "esperando": estado.esperando,
        "es_admin": es_admin,
    }


# Webhook para Telegram Bot
@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not _secreto_valido(header, WEBHOOK_SECRET):
        print("[telegram] secret_token ausente, inválido o no configurado; update rechazado.")
        return JSONResponse(status_code=403, content={"status": "forbidden"})

    try:
        update = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"status": "invalid_json"})

    if "message" in update:
        message = update["message"]
        if "photo" in message or "document" in message:
            # Procesar foto en hilo separado para no bloquear el bucle de eventos
            await asyncio.to_thread(_manejar_foto, message)
        else:
            await asyncio.to_thread(_manejar_mensaje, message)
        return {"status": "ok"}

    return {"status": "ignored"}


def _manejar_foto(message: dict):
    """Descarga la foto de Telegram, le aplica marca de agua automática,
    la sube a Supabase Storage y la anexa al borrador de evidencias."""
    chat_id = message["chat"]["id"]
    tecnico = _tecnico_de(chat_id)
    es_admin = db.es_admin(tecnico) if tecnico else False
    if not tecnico:
        tg.send_text(chat_id, "Primero manda /start <código> para identificarte.", con_teclado=False)
        return

    estado = get_estado(tecnico)
    if estado.esperando != "evidencia":
        tg.send_text(chat_id, "Para registrar un nuevo reporte pulsa '➕ Nuevo reporte'.", es_admin=es_admin)
        return

    tg.send_text(chat_id, "Subiendo foto y aplicando marca de agua…", con_teclado=False)
    try:
        if "photo" in message:
            file_id = message["photo"][-1]["file_id"]
            mime_type = "image/jpeg"
        elif "document" in message:
            doc = message["document"]
            if doc.get("file_size", 0) > 10 * 1024 * 1024:
                tg.send_text(chat_id, "La evidencia supera el límite de 10 MB.", es_admin=es_admin)
                return
            file_id = doc["file_id"]
            mime_type = doc.get("mime_type", "application/octet-stream")
        else:
            tg.send_text(chat_id, "Tipo de archivo no soportado como evidencia.", es_admin=es_admin)
            return

        contenido, file_path = tg.descargar_archivo(file_id)
        if len(contenido) > 10 * 1024 * 1024:
            tg.send_text(chat_id, "La evidencia supera el límite de 10 MB.", es_admin=es_admin)
            return
        if not mime_type.startswith("image/"):
            tg.send_text(chat_id, "Solo se permiten imágenes como evidencia.", es_admin=es_admin)
            return
        try:
            with Image.open(io.BytesIO(contenido)) as imagen:
                imagen.verify()
        except Exception:
            tg.send_text(chat_id, "El archivo no es una imagen válida.", es_admin=es_admin)
            return

        # Aplicar marca de agua con datos del reporte
        try:
            contenido_procesado = aplicar_marca_de_agua(
                contenido,
                ticket=estado.borrador.get("ticket"),
                tecnico=tecnico,
                zona=estado.borrador.get("ubicacion"),
            )
        except Exception as err_wm:
            print(f"[evidencia] advertencia aplicando marca de agua: {err_wm}")
            contenido_procesado = contenido

        nombre_archivo = f"evidencia_{tecnico.replace(' ', '_')}_{file_path.split('/')[-1]}"

        url = storage.upload_evidence(contenido_procesado, nombre_archivo, mime_type=mime_type)
        msg_resp = bot_logic.registrar_evidencia_foto(tecnico, url)
        tg.send_opciones(chat_id, msg_resp, ["Omitir", "Continuar"])
    except Exception as e:
        print(f"[evidencia] error subiendo evidencia: {e}")
        tg.send_text(chat_id, "No pude subir la evidencia. Intenta de nuevo en un momento.", es_admin=es_admin)


def _tecnico_de(chat_id: int) -> str | None:
    """Técnico identificado en este chat."""
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

    es_admin = db.es_admin(tecnico)

    if comando == "/nuevo_tecnico":
        _admin_nuevo_tecnico(chat_id, tecnico, texto)
        return
    if comando in ("/nuevo_departamento", "/nuevodepartamento"):
        _admin_nuevo_departamento(chat_id, tecnico, texto)
        return
    if comando in ("/departamentos", "/departamento") or bot_logic._remover_acentos(texto) in ("departamentos", "departamento", "ver departamentos"):
        _admin_listar_departamentos(chat_id, tecnico)
        return
    if comando == "/reporte" or bot_logic._remover_acentos(texto) == "exportar excel":
        _admin_exportar_excel(chat_id, tecnico, texto)
        return
    if comando == "/fotos" or bot_logic._remover_acentos(texto) == "descargar fotos":
        _admin_exportar_fotos(chat_id, tecnico, texto)
        return

    texto_normalizado = tg.normalizar_texto_boton(texto)
    respuestas = procesar_mensaje_web(tecnico, texto_normalizado)
    if not respuestas:
        return

    for r in respuestas[:-1]:
        tg.send_text(chat_id, r, con_teclado=False)

    esperando = get_estado(tecnico).esperando
    opciones = _obtener_opciones(esperando)
    if opciones:
        tg.send_opciones(chat_id, respuestas[-1], opciones)
    elif esperando:
        tg.send_opciones(chat_id, respuestas[-1], ["❌ Cancelar"])
    else:
        tg.send_text(chat_id, respuestas[-1], con_teclado=True, es_admin=es_admin)


def _manejar_start(chat_id: int, texto: str):
    tecnico_existente = _tecnico_de(chat_id)
    if tecnico_existente:
        estado = get_estado(tecnico_existente)
        estado.esperando = None
        estado.borrador = {}
        estado.folio_activo = None
        es_admin = db.es_admin(tecnico_existente)
        tg.send_text(chat_id, f"Hola de nuevo, {tecnico_existente.split(' ')[0]}. Conversación reiniciada. Usa los botones o escribe libremente.", es_admin=es_admin)
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
    es_admin = db.es_admin(nombre)
    tg.send_text(chat_id, f"Hola, {nombre.split(' ')[0]}. Tu cuenta quedó activada. Usa los botones o escribe libremente.", es_admin=es_admin)


def _admin_nuevo_tecnico(chat_id: int, tecnico: str, texto: str):
    if not db.es_admin(tecnico):
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
    """/reporte → semana actual; /reporte AAAA-MM-DD AAAA-MM-DD → ese periodo."""
    if not db.es_admin(tecnico):
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


def _admin_exportar_fotos(chat_id: int, tecnico: str, texto: str):
    """/fotos → semana actual; /fotos AAAA-MM-DD AAAA-MM-DD → ese periodo en archivo ZIP."""
    if not db.es_admin(tecnico):
        tg.send_text(chat_id, "No tienes permiso para usar este comando.", con_teclado=False)
        return
    partes = texto.split()[1:] if texto.split()[0].lower() == "/fotos" else []
    try:
        if len(partes) not in (0, 2):
            raise ValueError
        inicio, fin = _periodo(*partes)
    except ValueError:
        tg.send_text(chat_id, "Usa: /fotos  o  /fotos AAAA-MM-DD AAAA-MM-DD", es_admin=True)
        return

    tg.send_text(chat_id, f"Comprimiendo evidencias fotográficas del {inicio.isoformat()} al {fin.isoformat()}…", con_teclado=False)
    try:
        reportes = db.reportes_en_periodo(inicio, fin)
        contenido, nombre = generar_zip_evidencias(reportes, inicio, fin)
    except Exception as e:
        print(f"[exportar_fotos] error: {e}")
        tg.send_text(chat_id, "No pude empaquetar las evidencias en ZIP. Intenta más tarde.", es_admin=True)
        return
    tg.send_document(
        chat_id, contenido, nombre,
        caption=f"📷 Evidencias fotográficas del {inicio.isoformat()} al {fin.isoformat()}.\n"
                f"Otro periodo: /fotos AAAA-MM-DD AAAA-MM-DD",
        mime_type=MIME_ZIP,
    )


def _admin_nuevo_departamento(chat_id: int, tecnico: str, texto: str):
    if not db.es_admin(tecnico):
        tg.send_text(chat_id, "No tienes permiso para crear departamentos.", con_teclado=False)
        return
    nombre = texto.removeprefix("/nuevo_departamento").removeprefix("/nuevodepartamento").strip()
    if not nombre:
        get_estado(tecnico).esperando = "admin_nombre_departamento"
        tg.send_opciones(chat_id, "🏢 Escribe el nombre del nuevo departamento que deseas registrar (o Cancelar):", ["❌ Cancelar"])
        return
    try:
        creado = db.agregar_departamento(nombre)
    except Exception as e:
        print(f"[nuevo_departamento] error: {e}")
        tg.send_text(chat_id, "No pude crear el departamento. Intenta más tarde.", es_admin=True)
        return
    tg.send_text(chat_id, (f"✅ Departamento creado: *{nombre}*" if creado else f"El departamento *{nombre}* ya existe o es inválido."), es_admin=True)


def _admin_listar_departamentos(chat_id: int, tecnico: str):
    if not db.es_admin(tecnico):
        tg.send_text(chat_id, "No tienes permiso para consultar departamentos.", con_teclado=False)
        return
    try:
        nombres = db.listar_departamentos()
    except Exception as e:
        print(f"[departamentos] error: {e}")
        tg.send_text(chat_id, "No pude consultar los departamentos.", es_admin=True)
        return
    texto = "🏢 *Departamentos disponibles:*\n\n" + ("\n".join(f"{i}. {n}" for i, n in enumerate(nombres, 1)) or "No hay departamentos registrados.")
    tg.send_opciones(chat_id, texto, ["➕ Nuevo departamento", "➕ Nuevo reporte", "❌ Cancelar"])