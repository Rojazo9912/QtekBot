"""
La misma máquina de estados que main.py (bot de WhatsApp), pero desacoplada del
canal: en vez de llamar a whatsapp.send_text() directo, junta las respuestas en
una lista y las regresa. Así el mismo cerebro del bot sirve tanto para WhatsApp
como para la web app.
"""
from app import sheets
from app.ai_extract import interpretar_mensaje
from app.config import CATALOGO_PRIORIDAD, CATALOGO_TIPO_FALLA
from app.state import get_estado

_SIN_DATO = ("no", "ninguna", "ninguno", "n/a", "na")


def _prompt_tipo_falla() -> str:
    return "¿Qué tipo de falla es? Elige una opción:\n" + "\n".join(CATALOGO_TIPO_FALLA)


def _prompt_prioridad() -> str:
    return "¿Qué prioridad tiene? Elige una opción:\n" + "\n".join(CATALOGO_PRIORIDAD)


def _match_catalogo(texto: str, catalogo: list[str]) -> str | None:
    """Compara sin importar mayúsculas/acentos exactos; regresa el valor
    canónico del catálogo o None si no hay coincidencia."""
    texto_norm = texto.strip().lower()
    for opcion in catalogo:
        if opcion.lower() == texto_norm:
            return opcion
    return None


def procesar_mensaje_web(tecnico: str, texto: str) -> list[str]:
    """Devuelve la lista de mensajes que el bot 'contesta' para este turno."""
    respuestas: list[str] = []

    def decir(msg: str):
        respuestas.append(msg)

    estado = get_estado(tecnico)

    if estado.esperando == "ticket_si_no":
        _procesar_ticket_si_no(estado, texto, decir)
        return respuestas
    if estado.esperando == "numero_ticket":
        estado.borrador["ticket"] = texto.strip()
        estado.esperando = "tipo_falla"
        decir(_prompt_tipo_falla())
        return respuestas
    if estado.esperando == "tipo_falla":
        valor = _match_catalogo(texto, CATALOGO_TIPO_FALLA)
        if not valor:
            decir("No reconozco esa opción.\n" + _prompt_tipo_falla())
            return respuestas
        estado.borrador["tipo_falla"] = valor
        estado.esperando = "prioridad"
        decir(_prompt_prioridad())
        return respuestas
    if estado.esperando == "prioridad":
        valor = _match_catalogo(texto, CATALOGO_PRIORIDAD)
        if not valor:
            decir("No reconozco esa opción.\n" + _prompt_prioridad())
            return respuestas
        estado.borrador["prioridad"] = valor
        estado.esperando = "problema"
        decir("Descríbeme brevemente el problema o la actividad.")
        return respuestas
    if estado.esperando == "problema":
        estado.borrador["problema"] = texto.strip()
        estado.esperando = "area"
        decir("¿En qué área o ubicación es?")
        return respuestas
    if estado.esperando == "area":
        estado.borrador["area"] = texto.strip()
        folio = sheets.start_activity(
            tecnico=tecnico,
            ticket=estado.borrador.get("ticket"),
            area=estado.borrador["area"],
            problema=estado.borrador["problema"],
            tipo_falla=estado.borrador["tipo_falla"],
            prioridad=estado.borrador["prioridad"],
        )
        estado.folio_activo = folio
        estado.esperando = None
        estado.borrador = {}
        decir(f"Actividad iniciada. Folio/ticket: {folio}. Escribe 'pausar' o 'finalizar' cuando corresponda.")
        return respuestas
    if estado.esperando == "evidencias":
        respuesta = texto.strip().lower()
        if respuesta in ("listo", "no", "omitir", "ninguna", "ya"):
            estado.esperando = "solucion"
            decir("¿Cuál fue la solución?")
        else:
            decir("Manda tus fotos ahora (una o varias), o escribe 'listo' si ya terminaste / no tienes fotos.")
        return respuestas
    if estado.esperando == "solucion":
        estado.borrador["solucion"] = texto.strip()
        estado.esperando = "recomendaciones"
        decir("¿Alguna recomendación para evitar que se repita? (o escribe 'ninguna')")
        return respuestas
    if estado.esperando == "recomendaciones":
        valor = texto.strip()
        estado.borrador["recomendaciones"] = "" if valor.lower() in _SIN_DATO else valor
        estado.esperando = "materiales"
        decir("¿Usaste algún material o repuesto? Escríbelos separados por coma, o 'no'.")
        return respuestas
    if estado.esperando == "materiales":
        valor = texto.strip()
        estado.borrador["materiales"] = "" if valor.lower() in _SIN_DATO else valor
        estado.esperando = "receptor"
        decir("¿Quién recibió el trabajo?")
        return respuestas
    if estado.esperando == "receptor":
        estado.borrador["receptor"] = texto.strip()
        sheets.finish_activity(
            estado.folio_activo,
            solucion=estado.borrador["solucion"],
            recomendaciones=estado.borrador.get("recomendaciones", ""),
            receptor=estado.borrador["receptor"],
            materiales=estado.borrador.get("materiales", ""),
        )
        decir(f"Actividad {estado.folio_activo} finalizada. Buen trabajo.")
        estado.folio_activo = None
        estado.esperando = None
        estado.borrador = {}
        return respuestas
    if estado.esperando == "confirmacion":
        _procesar_confirmacion(estado, texto, decir)
        return respuestas

    interpretacion = interpretar_mensaje(texto)

    if interpretacion["confianza"] == "baja":
        estado.esperando = "confirmacion"
        estado.borrador["intencion_propuesta"] = interpretacion["intencion"]
        decir(f"No estoy seguro de haber entendido. ¿Quisiste decir '{interpretacion['intencion'].replace('_', ' ')}'? Responde sí o no.")
        return respuestas

    _ejecutar_intencion(estado, interpretacion["intencion"], decir)
    return respuestas


def _ejecutar_intencion(estado, intencion: str, decir):
    if intencion == "nueva_actividad":
        if estado.folio_activo:
            decir(f"Ya tienes la actividad {estado.folio_activo} activa. Escribe 'pausar' antes de iniciar otra.")
            return
        estado.esperando = "ticket_si_no"
        decir("¿Esta actividad tiene ticket? (sí/no)")

    elif intencion == "pausar":
        if not estado.folio_activo:
            decir("No tienes ninguna actividad activa para pausar.")
            return
        sheets.pause_activity(estado.folio_activo)
        decir(f"Actividad {estado.folio_activo} pausada.")
        estado.folio_activo = None

    elif intencion == "reanudar":
        pendientes = sheets.list_open_activities(estado.nombre)
        pausadas = [a for a in pendientes if a.get("_en_pausa")]
        if not pausadas:
            decir("No tienes actividades pausadas para reanudar.")
            return
        folio = pausadas[0]["Ticket"]
        sheets.resume_activity(folio)
        estado.folio_activo = folio
        decir(f"Actividad {folio} reanudada.")

    elif intencion == "finalizar":
        if not estado.folio_activo:
            decir("No tienes ninguna actividad activa para finalizar.")
            return
        estado.esperando = "evidencias"
        decir("Manda tus fotos de evidencia (una o varias). Cuando termines, escribe 'listo'. Si no tienes fotos, escribe 'no'.")

    elif intencion == "consultar":
        pendientes = sheets.list_open_activities(estado.nombre)
        if not pendientes:
            decir("No tienes actividades abiertas ni pausadas.")
        else:
            lineas = [
                f"- {a['Ticket']} ({'Pausada' if a.get('_en_pausa') else 'En proceso'}): {a['Tipo de Falla']}"
                for a in pendientes
            ]
            decir("Tus actividades pendientes:\n" + "\n".join(lineas))

    else:
        decir("No entendí. Puedes decir: nueva actividad, pausar, reanudar, finalizar o mis actividades.")


def _procesar_ticket_si_no(estado, texto: str, decir):
    respuesta = texto.strip().lower()
    if respuesta in ("si", "sí", "s"):
        estado.esperando = "numero_ticket"
        decir("Dame el número de ticket.")
    elif respuesta in ("no", "n"):
        estado.borrador["ticket"] = None
        estado.esperando = "tipo_falla"
        decir("Ok, se generará un folio interno. " + _prompt_tipo_falla())
    else:
        decir("Responde solo 'sí' o 'no': ¿tiene ticket esta actividad?")


def _procesar_confirmacion(estado, texto: str, decir):
    respuesta = texto.strip().lower()
    estado.esperando = None
    if respuesta in ("si", "sí", "s"):
        intencion = estado.borrador.pop("intencion_propuesta")
        _ejecutar_intencion(estado, intencion, decir)
    else:
        estado.borrador = {}
        decir("Ok, cancelado. Dime de nuevo qué necesitas hacer.")
