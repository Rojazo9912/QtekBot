"""
Piloto mínimo FieldTI AI — bot de WhatsApp que llena el reporte en Google Sheets.

Cubre del PRD (Fase 1 + parte de Fase 2):
- Nueva actividad, con ticket o folio interno.
- Pausar / Reanudar / Finalizar.
- "Mis actividades" (consulta de pendientes).
- Interpretación de lenguaje natural vía OpenAI, con confirmación si hay ambigüedad
  (regla de negocio del PRD, sección 15).

NO cubre en este piloto (a propósito, para no inflar el alcance):
- Evidencias (fotos/audios) — Cloud API las manda como media_id; falta el código
  para descargarlas y subirlas a algún storage. Es la siguiente pieza obvia.
- Dashboard / reportes PDF-Excel — para el piloto, el propio Google Sheet ES el
  dashboard.
- Multi-actividad simultánea real — el piloto asume una actividad activa a la vez
  por técnico, como en el ejemplo de la sección 6 del PRD.
"""
import os
from fastapi import FastAPI, Request, Response

from app import sheets, whatsapp
from app.ai_extract import interpretar_mensaje
from app.state import get_estado

app = FastAPI()

VERIFY_TOKEN = os.environ["WHATSAPP_VERIFY_TOKEN"]

# Mapeo temporal número -> nombre de técnico para el piloto (2-3 personas).
# En producción esto debe salir de una tabla "technicians", no de un dict fijo.
TECNICOS = {
    "5216182692461": "Miguel Abraham Lopez Ortiz",
    "5216189876543": "Alonso Ibarra Mata",
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
        from_number = msg["from"]
        texto = msg.get("text", {}).get("body", "")
    except (KeyError, IndexError):
        return {"status": "ignored"}

    tecnico = TECNICOS.get(from_number)
    if not tecnico:
        whatsapp.send_text(from_number, "Tu número no está registrado como técnico. Contacta a tu supervisor.")
        return {"status": "unregistered"}

    manejar_mensaje(tecnico, from_number, texto)
    return {"status": "ok"}


def manejar_mensaje(tecnico: str, numero: str, texto: str):
    estado = get_estado(tecnico)

    # --- Si el bot está a mitad de una conversación de varios pasos, prioriza eso ---
    if estado.esperando == "ticket_si_no":
        _procesar_ticket_si_no(estado, numero, texto)
        return
    if estado.esperando == "numero_ticket":
        estado.borrador["ticket"] = texto.strip()
        estado.esperando = "problema"
        whatsapp.send_text(numero, "Descríbeme brevemente el problema o la actividad.")
        return
    if estado.esperando == "problema":
        estado.borrador["problema"] = texto.strip()
        estado.esperando = "area"
        whatsapp.send_text(numero, "¿En qué área o ubicación es?")
        return
    if estado.esperando == "area":
        estado.borrador["area"] = texto.strip()
        folio = sheets.start_activity(
            tecnico=tecnico,
            ticket=estado.borrador.get("ticket"),
            area=estado.borrador["area"],
            problema=estado.borrador["problema"],
        )
        estado.folio_activo = folio
        estado.esperando = None
        estado.borrador = {}
        whatsapp.send_text(numero, f"Actividad iniciada. Folio/ticket: {folio}. Escribe 'pausar' o 'finalizar' cuando corresponda.")
        return
    if estado.esperando == "solucion":
        estado.borrador["solucion"] = texto.strip()
        estado.esperando = "receptor"
        whatsapp.send_text(numero, "¿Quién recibió el trabajo?")
        return
    if estado.esperando == "receptor":
        estado.borrador["receptor"] = texto.strip()
        sheets.finish_activity(estado.folio_activo, estado.borrador["solucion"], estado.borrador["receptor"])
        whatsapp.send_text(numero, f"Actividad {estado.folio_activo} finalizada. Buen trabajo.")
        estado.folio_activo = None
        estado.esperando = None
        estado.borrador = {}
        return
    if estado.esperando == "confirmacion":
        _procesar_confirmacion(estado, numero, texto)
        return

    # --- Si no hay conversación pendiente, interpretamos el mensaje libre ---
    interpretacion = interpretar_mensaje(texto)

    if interpretacion["confianza"] == "baja":
        estado.esperando = "confirmacion"
        estado.borrador["intencion_propuesta"] = interpretacion["intencion"]
        whatsapp.send_text(
            numero,
            f"No estoy seguro de haber entendido. ¿Quisiste decir '{interpretacion['intencion'].replace('_', ' ')}'? Responde sí o no.",
        )
        return

    _ejecutar_intencion(estado, numero, interpretacion["intencion"])


def _ejecutar_intencion(estado, numero: str, intencion: str):
    if intencion == "nueva_actividad":
        if estado.folio_activo:
            whatsapp.send_text(numero, f"Ya tienes la actividad {estado.folio_activo} activa. Escribe 'pausar' antes de iniciar otra.")
            return
        estado.esperando = "ticket_si_no"
        whatsapp.send_text(numero, "¿Esta actividad tiene ticket? (sí/no)")

    elif intencion == "pausar":
        if not estado.folio_activo:
            whatsapp.send_text(numero, "No tienes ninguna actividad activa para pausar.")
            return
        sheets.pause_activity(estado.folio_activo)
        whatsapp.send_text(numero, f"Actividad {estado.folio_activo} pausada.")
        estado.folio_activo = None

    elif intencion == "reanudar":
        pendientes = sheets.list_open_activities(estado.nombre)
        pausadas = [a for a in pendientes if a.get("Estado") == "Pausada"]
        if not pausadas:
            whatsapp.send_text(numero, "No tienes actividades pausadas para reanudar.")
            return
        folio = pausadas[0]["Folio"]
        sheets.resume_activity(folio)
        estado.folio_activo = folio
        whatsapp.send_text(numero, f"Actividad {folio} reanudada.")

    elif intencion == "finalizar":
        if not estado.folio_activo:
            whatsapp.send_text(numero, "No tienes ninguna actividad activa para finalizar.")
            return
        estado.esperando = "solucion"
        whatsapp.send_text(numero, "¿Cuál fue la solución?")

    elif intencion == "consultar":
        pendientes = sheets.list_open_activities(estado.nombre)
        if not pendientes:
            whatsapp.send_text(numero, "No tienes actividades abiertas ni pausadas.")
        else:
            lineas = [f"- {a['Folio']} ({a['Estado']}): {a['Problema']}" for a in pendientes]
            whatsapp.send_text(numero, "Tus actividades pendientes:\n" + "\n".join(lineas))

    else:
        whatsapp.send_text(numero, "No entendí. Puedes decir: nueva actividad, pausar, reanudar, finalizar o mis actividades.")


def _procesar_ticket_si_no(estado, numero: str, texto: str):
    respuesta = texto.strip().lower()
    if respuesta in ("si", "sí", "s"):
        estado.esperando = "numero_ticket"
        whatsapp.send_text(numero, "Dame el número de ticket.")
    elif respuesta in ("no", "n"):
        estado.borrador["ticket"] = None
        estado.esperando = "problema"
        whatsapp.send_text(numero, "Ok, se generará un folio interno. Descríbeme el problema o la actividad.")
    else:
        whatsapp.send_text(numero, "Responde solo 'sí' o 'no': ¿tiene ticket esta actividad?")


def _procesar_confirmacion(estado, numero: str, texto: str):
    respuesta = texto.strip().lower()
    estado.esperando = None
    if respuesta in ("si", "sí", "s"):
        intencion = estado.borrador.pop("intencion_propuesta")
        _ejecutar_intencion(estado, numero, intencion)
    else:
        estado.borrador = {}
        whatsapp.send_text(numero, "Ok, cancelado. Dime de nuevo qué necesitas hacer.")
