"""
La misma máquina de estados que main.py, pero desacoplada del
canal: en vez de llamar a un cliente directo, junta las respuestas en
una lista y las regresa. Así el mismo cerebro del bot sirve tanto para Telegram
como para la web app.
"""
import re
import unicodedata
from app import sheets
from app.ai_extract import interpretar_mensaje
from app.config import CATALOGO_AREA, CATALOGO_PRIORIDAD, CATALOGO_TIPO_FALLA
from app.state import get_estado

_SIN_DATO = ("no", "ninguna", "ninguno", "n/a", "na", "-", "ningun")
_CANCELAR_COMANDOS = ("cancelar", "cancel", "abortar", "/cancel", "salir")

# Comandos directos que no requieren pasar por IA
_COMANDOS_DIRECTOS = {
    "nueva actividad": "nueva_actividad",
    "+ nueva actividad": "nueva_actividad",
    "/nueva_actividad": "nueva_actividad",
    "pausar": "pausar",
    "/pausar": "pausar",
    "reanudar": "reanudar",
    "/reanudar": "reanudar",
    "finalizar": "finalizar",
    "/finalizar": "finalizar",
    "mis actividades": "consultar",
    "/mis_actividades": "consultar",
    "consultar": "consultar",
}


def _remover_acentos(texto: str) -> str:
    """Elimina acentos/diacríticos y pasa a minúsculas para comparaciones robustas."""
    if not texto:
        return ""
    nfd = unicodedata.normalize("NFD", texto)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower().strip()


def _prompt_area() -> str:
    opciones = [f"{i+1}. {op}" for i, op in enumerate(CATALOGO_AREA)]
    return "¿Es un ticket de Infraestructura o de Soporte?\n" + "\n".join(opciones)


def _prompt_tipo_falla() -> str:
    opciones = [f"{i+1}. {op}" for i, op in enumerate(CATALOGO_TIPO_FALLA)]
    return "¿Qué tipo de falla es? Elige una opción:\n" + "\n".join(opciones)


def _prompt_prioridad() -> str:
    opciones = [f"{i+1}. {op}" for i, op in enumerate(CATALOGO_PRIORIDAD)]
    return "¿Qué prioridad tiene? Elige una opción:\n" + "\n".join(opciones)


def _match_catalogo(texto: str, catalogo: list[str]) -> str | None:
    """Compara sin importar mayúsculas, minúsculas ni acentos.
    Permite también seleccionar por número (ej. '1', '2', etc.).
    Regresa el valor canónico del catálogo o None si no hay coincidencia."""
    texto_limpio = texto.strip()
    if not texto_limpio:
        return None

    # 1. Selección por número de opción (1-indexado)
    if texto_limpio.isdigit():
        idx = int(texto_limpio) - 1
        if 0 <= idx < len(catalogo):
            return catalogo[idx]

    # 2. Coincidencia exacta ignorando acentos y mayúsculas
    texto_norm = _remover_acentos(texto_limpio)
    for opcion in catalogo:
        if _remover_acentos(opcion) == texto_norm:
            return opcion

    # 3. Coincidencia si el texto del usuario comienza o está contenido claramente
    coincidencias = [
        opcion for opcion in catalogo
        if texto_norm in _remover_acentos(opcion) or _remover_acentos(opcion) in texto_norm
    ]
    if len(coincidencias) == 1:
        return coincidencias[0]

    return None


def procesar_mensaje_web(tecnico: str, texto: str) -> list[str]:
    """Devuelve la lista de mensajes que el bot 'contesta' para este turno."""
    respuestas: list[str] = []

    def decir(msg: str):
        respuestas.append(msg)

    texto_limpio = texto.strip()
    if not texto_limpio:
        return respuestas

    estado = get_estado(tecnico)

    # Permitir cancelar en cualquier paso
    if _remover_acentos(texto_limpio) in _CANCELAR_COMANDOS:
        estado.esperando = None
        estado.borrador = {}
        decir("Operación cancelada. Puedes escribir 'nueva actividad' o usar los botones cuando estés listo.")
        return respuestas

    if estado.esperando == "ticket_si_no":
        _procesar_ticket_si_no(estado, texto_limpio, decir)
        return respuestas
    if estado.esperando == "numero_ticket":
        estado.borrador["ticket"] = texto_limpio
        estado.esperando = "area"
        decir(_prompt_area())
        return respuestas
    if estado.esperando == "area":
        valor = _match_catalogo(texto_limpio, CATALOGO_AREA)
        if not valor:
            decir("No reconozco esa opción.\n" + _prompt_area())
            return respuestas
        estado.borrador["area"] = valor
        estado.esperando = "tipo_falla"
        decir(_prompt_tipo_falla())
        return respuestas
    if estado.esperando == "tipo_falla":
        valor = _match_catalogo(texto_limpio, CATALOGO_TIPO_FALLA)
        if not valor:
            decir("No reconozco esa opción.\n" + _prompt_tipo_falla())
            return respuestas
        estado.borrador["tipo_falla"] = valor
        estado.esperando = "prioridad"
        decir(_prompt_prioridad())
        return respuestas
    if estado.esperando == "prioridad":
        valor = _match_catalogo(texto_limpio, CATALOGO_PRIORIDAD)
        if not valor:
            decir("No reconozco esa opción.\n" + _prompt_prioridad())
            return respuestas
        estado.borrador["prioridad"] = valor
        estado.esperando = "problema"
        decir("Descríbeme brevemente el problema o la actividad.")
        return respuestas
    if estado.esperando == "problema":
        estado.borrador["problema"] = texto_limpio
        estado.esperando = "ubicacion"
        decir("¿En qué área o ubicación es?")
        return respuestas
    if estado.esperando == "ubicacion":
        estado.borrador["ubicacion"] = texto_limpio
        try:
            folio = sheets.start_activity(
                tecnico=tecnico,
                ticket=estado.borrador.get("ticket"),
                area=estado.borrador["area"],
                ubicacion=estado.borrador["ubicacion"],
                problema=estado.borrador["problema"],
                tipo_falla=estado.borrador["tipo_falla"],
                prioridad=estado.borrador["prioridad"],
            )
            estado.folio_activo = folio
            estado.esperando = None
            estado.borrador = {}
            decir(f"Actividad iniciada. Folio/ticket: {folio}. Escribe 'pausar' o 'finalizar' cuando corresponda.")
        except Exception as e:
            print(f"[bot_logic] error iniciando actividad en sheets: {e}")
            decir("Hubo un error registrando la actividad en Google Sheets. Intenta de nuevo o contacta al administrador.")
        return respuestas

    if estado.esperando == "evidencias":
        respuesta = _remover_acentos(texto_limpio)
        if respuesta in ("listo", "no", "omitir", "ninguna", "ya", "listo.", "sin fotos"):
            estado.esperando = "solucion"
            decir("¿Cuál fue la solución aplicada?")
        else:
            decir("Manda tus fotos ahora (una o varias), o escribe 'listo' si ya terminaste / no tienes fotos.")
        return respuestas

    if estado.esperando == "solucion":
        estado.borrador["solucion"] = texto_limpio
        estado.esperando = "recomendaciones"
        decir("¿Alguna recomendación para evitar que se repita? (o escribe 'ninguna')")
        return respuestas

    if estado.esperando == "recomendaciones":
        valor = texto_limpio
        estado.borrador["recomendaciones"] = "" if _remover_acentos(valor) in _SIN_DATO else valor
        estado.esperando = "materiales"
        decir("¿Usaste algún material o repuesto? Escríbelos separados por coma, o 'no'.")
        return respuestas

    if estado.esperando == "materiales":
        valor = texto_limpio
        estado.borrador["materiales"] = "" if _remover_acentos(valor) in _SIN_DATO else valor
        estado.esperando = "receptor"
        decir("¿Quién recibió el trabajo?")
        return respuestas

    if estado.esperando == "receptor":
        estado.borrador["receptor"] = texto_limpio
        try:
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
        except Exception as e:
            print(f"[bot_logic] error finalizando actividad en sheets: {e}")
            decir("Hubo un error guardando el cierre de la actividad en Google Sheets. Intenta de nuevo.")
        return respuestas

    if estado.esperando == "confirmacion":
        _procesar_confirmacion(estado, texto_limpio, decir)
        return respuestas

    # Reconocimiento rápido de comandos directos sin invocar OpenAI
    texto_norm_cmd = _remover_acentos(texto_limpio)
    if texto_norm_cmd in _COMANDOS_DIRECTOS:
        _ejecutar_intencion(estado, _COMANDOS_DIRECTOS[texto_norm_cmd], decir)
        return respuestas

    # Si no es comando directo, interpretar con NLU (OpenAI)
    interpretacion = interpretar_mensaje(texto_limpio)

    if interpretacion["confianza"] == "baja":
        if interpretacion["intencion"] != "desconocido":
            estado.esperando = "confirmacion"
            estado.borrador["intencion_propuesta"] = interpretacion["intencion"]
            decir(f"No estoy seguro de haber entendido. ¿Quisiste decir '{interpretacion['intencion'].replace('_', ' ')}'? Responde sí o no.")
        else:
            decir("No entendí tu mensaje. Puedes escribir: 'nueva actividad', 'pausar', 'reanudar', 'finalizar' o 'mis actividades'.")
        return respuestas

    ticket_solicitado = interpretacion.get("ticket")
    _ejecutar_intencion(estado, interpretacion["intencion"], decir, ticket=ticket_solicitado)
    return respuestas


def _ejecutar_intencion(estado, intencion: str, decir, ticket: str | None = None):
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
        decir(f"Actividad {estado.folio_activo} pausada.")
        estado.folio_activo = None

    elif intencion == "reanudar":
        try:
            pendientes = sheets.list_open_activities(estado.nombre)
        except Exception as e:
            print(f"[bot_logic] error listando actividades: {e}")
            decir("No pude consultar tus actividades pendientes en Google Sheets.")
            return

        otras = [a for a in pendientes if a.get("Folio") != estado.folio_activo]
        if not otras:
            decir("No tienes actividades pausadas para reanudar.")
            return

        # Si el usuario solicitó un ticket específico (ej. "reanudar FOLIO-0002")
        folio_elegido = None
        if ticket:
            for a in otras:
                if a.get("Folio", "").lower() == ticket.lower():
                    folio_elegido = a.get("Folio")
                    break

        if not folio_elegido:
            folio_elegido = otras[0]["Folio"]

        estado.folio_activo = folio_elegido
        decir(f"Actividad {folio_elegido} reanudada.")

    elif intencion == "finalizar":
        if not estado.folio_activo:
            decir("No tienes ninguna actividad activa para finalizar.")
            return
        estado.esperando = "evidencias"
        decir("Manda tus fotos de evidencia (una o varias). Cuando termines, escribe 'listo'. Si no tienes fotos, escribe 'no'.")

    elif intencion == "consultar":
        try:
            pendientes = sheets.list_open_activities(estado.nombre)
        except Exception as e:
            print(f"[bot_logic] error consultando actividades: {e}")
            decir("No pude consultar tus actividades en Google Sheets.")
            return

        if not pendientes:
            decir("No tienes actividades abiertas ni pausadas.")
        else:
            lineas = [
                f"- {a['Folio']} ({'Activa' if a['Folio'] == estado.folio_activo else 'Pausada'}): {a['Tipo de Falla']}"
                for a in pendientes
            ]
            decir("Tus actividades pendientes:\n" + "\n".join(lineas))

    else:
        decir("No entendí. Puedes decir: nueva actividad, pausar, reanudar, finalizar o mis actividades.")


def _procesar_ticket_si_no(estado, texto: str, decir):
    respuesta = _remover_acentos(texto)
    if respuesta in ("si", "s", "yes", "y", "afirmativo", "claro"):
        estado.esperando = "numero_ticket"
        decir("Dame el número de ticket.")
    elif respuesta in ("no", "n", "nop", "negativo"):
        estado.borrador["ticket"] = None
        estado.esperando = "area"
        decir("Ok, se generará un folio interno. " + _prompt_area())
    else:
        decir("Responde solo 'sí' o 'no': ¿tiene ticket esta actividad?")


def _procesar_confirmacion(estado, texto: str, decir):
    respuesta = _remover_acentos(texto)
    estado.esperando = None
    if respuesta in ("si", "s", "yes", "y", "afirmativo", "claro"):
        intencion = estado.borrador.pop("intencion_propuesta", None)
        if intencion:
            _ejecutar_intencion(estado, intencion, decir)
        else:
            decir("Dime qué necesitas hacer.")
    else:
        estado.borrador = {}
        decir("Ok, cancelado. Dime de nuevo qué necesitas hacer.")
