"""
Máquina de estados desacoplada del canal (Telegram y Web App).
Implementa el flujo de conversación de 5 pasos definido en el PRD v1.1:
1) Ticket
2) Ubicación
3) Actividad
4) Estado
5) Evidencia (fotos opcionales a Google Drive)
Confirmación: ✅ Guardar / ✏️ Editar / ❌ Cancelar
Navegación: ➕ Nuevo reporte · ⏸️ Mis pendientes · 📋 Mis reportes
"""
import datetime as dt
import re
import unicodedata
from zoneinfo import ZoneInfo
from typing import Optional

from app import sheets
from app.config import (
    ADMIN_TECNICOS,
    CATALOGO_UBICACION,
    CATALOGO_ESTADO_REPORTE,
)
from app.state import get_estado

_SIN_DATO = ("no", "ninguna", "ninguno", "n/a", "na", "-", "omitir", "sin fotos")
_CANCELAR_COMANDOS = ("cancelar", "cancel", "abortar", "/cancel", "salir")


def _ahora() -> dt.datetime:
    return dt.datetime.now(sheets.ZONA_HORARIA)


def _remover_acentos(texto: str) -> str:
    """Elimina acentos y pasa a minúsculas para comparaciones flexibles."""
    if not texto:
        return ""
    nfd = unicodedata.normalize("NFD", texto)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower().strip()


def _normalizar_estado(texto: str) -> str:
    t = _remover_acentos(texto)
    if "terminado" in t or "finalizar" in t or "concluido" in t or "listo" in t:
        return "Terminado"
    if "pendiente" in t or "pausar" in t:
        return "Pendiente"
    if "no solucionado" in t or "fallo" in t or "sin solucion" in t or "no resuelto" in t:
        return "No solucionado"
    return texto.strip()


def procesar_mensaje_web(tecnico: str, texto: str) -> list[str]:
    """Procesa una entrada de texto del usuario y devuelve la lista de respuestas."""
    respuestas: list[str] = []

    def decir(msg: str):
        respuestas.append(msg)

    texto_limpio = texto.strip()
    if not texto_limpio:
        return respuestas

    estado = get_estado(tecnico)
    es_admin = tecnico in ADMIN_TECNICOS
    t_norm = _remover_acentos(texto_limpio)

    # Permitir cancelar en cualquier momento
    if t_norm in _CANCELAR_COMANDOS:
        estado.esperando = None
        estado.borrador = {}
        estado.folio_activo = None
        decir("❌ Operación cancelada. Selecciona una opción del menú principal cuando desees reiniciar.")
        return respuestas

    # Flujo de Admin: Alta de nuevo técnico
    if estado.esperando == "admin_nombre_tecnico":
        nombre_nuevo = texto_limpio
        try:
            codigo = sheets.agregar_tecnico(nombre_nuevo)
            estado.esperando = None
            if not codigo:
                decir(f"El técnico {nombre_nuevo} ya estaba registrado en la lista de técnicos.")
            else:
                decir(
                    f"✅ Técnico agregado: *{nombre_nuevo}*.\n\n"
                    f"Mándale este código para que active su cuenta:\n"
                    f"`/start {codigo}`"
                )
        except Exception as e:
            decir(f"Error al registrar técnico: {e}")
            estado.esperando = None
        return respuestas

    # --- NAVEGACIÓN DEL MENÚ PRINCIPAL ---
    if t_norm in ("nuevo reporte", "+ nuevo reporte", "➕ nuevo reporte", "/nuevo_reporte", "nueva actividad", "+ nueva actividad", "/start"):
        # Reiniciar borrador y comenzar Paso 1 (Ticket)
        estado.borrador = {"evidencias": []}
        estado.esperando = "ticket"
        decir("🎫 *Paso 1 de 5 — Ticket*\n\nIngresa el número de ticket u orden de trabajo (obligatorio, ej. TK-001254):")
        return respuestas

    if t_norm in ("mis pendientes", "⏸️ mis pendientes", "mis actividades", "/pendientes"):
        pendientes = sheets.listar_reportes_pendientes(tecnico)
        if not pendientes:
            decir("⏸️ No tienes reportes en estado Pendiente.")
            return respuestas

        lineas = ["⏸️ *Tus reportes pendientes:*"]
        for p in pendientes:
            lineas.append(f"• *{p['Numero']}* (Ticket: {p['Ticket']}) — {p['Ubicacion']}: {p['Actividad']}")
        lineas.append("\nResponde con el número de reporte (ej. `#001` o `001`) que deseas continuar o actualizar:")
        estado.esperando = "seleccion_pendiente"
        decir("\n".join(lineas))
        return respuestas

    if t_norm in ("mis reportes", "📋 mis reportes", "historial", "/reportes"):
        reportes = sheets.listar_mis_reportes(tecnico)
        if not reportes:
            decir("📋 No tienes reportes registrados aún.")
            return respuestas

        lineas = ["📋 *Tus últimos reportes:*"]
        for r in reportes[-10:]:  # Mostrar los últimos 10
            icono = "✅" if "terminado" in _remover_acentos(r["Estado"]) else ("⏸️" if "pendiente" in _remover_acentos(r["Estado"]) else "❌")
            lineas.append(f"{icono} *{r['Numero']}* | Ticket: {r['Ticket']} | {r['Ubicacion']} ({r['Fecha']})")
        decir("\n".join(lineas))
        return respuestas

    if t_norm in ("nuevo tecnico", "+ nuevo tecnico", "👤 + nuevo técnico", "/nuevo_tecnico", "dar de alta"):
        if not es_admin:
            decir("No tienes permisos de administrador para agregar técnicos.")
            return respuestas
        estado.esperando = "admin_nombre_tecnico"
        decir("👤 Escribe el Nombre Completo del nuevo técnico que deseas registrar:")
        return respuestas

    if t_norm in ("ayuda", "comandos", "/help"):
        lineas = [
            "🤖 *Comandos de Reporte de Campo:*",
            "• *➕ Nuevo reporte*: Inicia el registro de un nuevo reporte (5 pasos).",
            "• *⏸️ Mis pendientes*: Muestra y permite continuar reportes pendientes.",
            "• *📋 Mis reportes*: Muestra tu historial de reportes.",
            "• *Cancelar*: Cancela el proceso actual.",
        ]
        if es_admin:
            lineas.append("\n👑 *Administrador:*")
            lineas.append("• *👤 + Nuevo técnico*: Genera código de activación para un técnico nuevo.")
        decir("\n".join(lineas))
        return respuestas

    # --- MÁQUINA DE ESTADOS (FLUJO DE 5 PASOS PRD V1.1) ---

    # Paso 1: Ticket
    if estado.esperando == "ticket":
        estado.borrador["ticket"] = texto_limpio
        estado.esperando = "ubicacion"
        opciones_ubicacion = "\n".join([f"• {u}" for u in CATALOGO_UBICACION])
        decir(f"📍 *Paso 2 de 5 — Ubicación*\n\nSelecciona la ubicación de la lista o escribe una:\n{opciones_ubicacion}")
        return respuestas

    # Paso 2: Ubicación
    if estado.esperando == "ubicacion":
        if t_norm in ("otra", "otra ubicacion"):
            estado.esperando = "ubicacion_otra"
            decir("📍 Escribe la ubicación personalizada:")
            return respuestas

        # Buscar coincidencia en catálogo
        ubicacion_sel = None
        for u in CATALOGO_UBICACION:
            if _remover_acentos(u) == t_norm or t_norm in _remover_acentos(u):
                ubicacion_sel = u
                break
        if not ubicacion_sel:
            ubicacion_sel = texto_limpio

        estado.borrador["ubicacion"] = ubicacion_sel
        estado.esperando = "actividad"
        decir("📝 *Paso 3 de 5 — Actividad*\n\nDescribe brevemente la actividad realizada:")
        return respuestas

    if estado.esperando == "ubicacion_otra":
        estado.borrador["ubicacion"] = texto_limpio
        estado.esperando = "actividad"
        decir("📝 *Paso 3 de 5 — Actividad*\n\nDescribe brevemente la actividad realizada:")
        return respuestas

    # Paso 3: Actividad
    if estado.esperando == "actividad":
        estado.borrador["actividad"] = texto_limpio
        estado.esperando = "estado"
        opciones_estado = "\n".join([f"• {e}" for e in CATALOGO_ESTADO_REPORTE])
        decir(f"📊 *Paso 4 de 5 — Estado*\n\nSelecciona el estado final del reporte:\n{opciones_estado}")
        return respuestas

    # Paso 4: Estado
    if estado.esperando == "estado":
        estado_norm = _normalizar_estado(texto_limpio)
        estado.borrador["estado"] = estado_norm
        estado.esperando = "evidencia"
        decir(
            "📷 *Paso 5 de 5 — Evidencia Fotográfica*\n\n"
            "Manda una o varias fotos de evidencia por el chat, o responde *'Omitir'* para continuar sin fotos."
        )
        return respuestas

    # Paso 5: Evidencia fotográfica
    if estado.esperando == "evidencia":
        if t_norm in ("omitir", "continuar", "listo", "sin fotos", "no"):
            _mostrar_confirmacion(estado, decir)
            return respuestas
        else:
            # Si el usuario mandó texto en vez de foto en este paso
            decir("Manda una foto por el chat o responde *'Omitir'* / *'Continuar'* para pasar a la confirmación.")
            return respuestas

    # Paso 6: Confirmación previa a guardado
    if estado.esperando == "confirmacion":
        if t_norm in ("guardar", "✅ guardar", "si", "sí", "confirmar", "ok"):
            # Guardar reporte en Google Sheets
            try:
                b = estado.borrador
                evidencias_str = "\n".join(b.get("evidencias", []))
                numero_creado = sheets.crear_reporte(
                    ticket=b.get("ticket", "N/A"),
                    tecnico=tecnico,
                    ubicacion=b.get("ubicacion", "Nivel 10"),
                    actividad=b.get("actividad", ""),
                    estado=b.get("estado", "Terminado"),
                    evidencias=evidencias_str,
                )
                now = _ahora()
                decir(
                    f"✅ *Reporte guardado exitosamente*\n\n"
                    f"• *Número:* {numero_creado}\n"
                    f"• *Ticket:* {b.get('ticket')}\n"
                    f"• *Ubicación:* {b.get('ubicacion')}\n"
                    f"• *Actividad:* {b.get('actividad')}\n"
                    f"• *Estado:* {b.get('estado')}\n"
                    f"• *Técnico:* {tecnico}\n"
                    f"• *Fecha:* {now.strftime('%Y-%m-%d')}\n"
                    f"• *Hora:* {now.strftime('%H:%M:%S')}"
                )
                estado.borrador = {}
                estado.esperando = None
            except Exception as e:
                decir(f"❌ Error al guardar en Google Sheets: {e}")
            return respuestas

        elif t_norm in ("editar", "✏️ editar", "corregir", "reiniciar"):
            estado.borrador = {"evidencias": []}
            estado.esperando = "ticket"
            decir("✏️ Reiniciando el reporte.\n\n🎫 *Paso 1 de 5 — Ticket*\n\nIngresa el número de ticket (obligatorio):")
            return respuestas

        elif t_norm in ("cancelar", "❌ cancelar", "no"):
            estado.borrador = {}
            estado.esperando = None
            decir("❌ Reporte cancelado.")
            return respuestas
        else:
            decir("Responde *Guardar*, *Editar* o *Cancelar* para continuar.")
            return respuestas

    # Flujo de Continuar / Actualizar Pendiente
    if estado.esperando == "seleccion_pendiente":
        num_clean = texto_limpio.replace("#", "").strip()
        if not num_clean.isdigit():
            decir("Por favor ingresa el número de reporte (ej. `#001` o `001`).")
            return respuestas
        num_formateado = f"#{int(num_clean):03d}"
        estado.folio_activo = num_formateado
        estado.esperando = "continuar_pendiente_actividad"
        decir(f"📝 *Actualizando reporte {num_formateado}*\n\nDescribe el avance o actualización realizada:")
        return respuestas

    if estado.esperando == "continuar_pendiente_actividad":
        estado.borrador["nueva_actividad"] = texto_limpio
        estado.esperando = "continuar_pendiente_estado"
        opciones_estado = "\n".join([f"• {e}" for e in CATALOGO_ESTADO_REPORTE])
        decir(f"📊 Selecciona el nuevo estado del reporte:\n{opciones_estado}")
        return respuestas

    if estado.esperando == "continuar_pendiente_estado":
        nuevo_est = _normalizar_estado(texto_limpio)
        num_target = estado.folio_activo
        nueva_act = estado.borrador.get("nueva_actividad", "")
        try:
            exito = sheets.actualizar_reporte_pendiente(num_target, nueva_actividad=nueva_act, nuevo_estado=nuevo_est)
            if exito:
                decir(f"✅ Reporte *{num_target}* actualizado a estado *{nuevo_est}*.")
            else:
                decir(f"❌ No se encontró el reporte {num_target} en Google Sheets.")
        except Exception as e:
            decir(f"Error al actualizar reporte: {e}")
        estado.esperando = None
        estado.folio_activo = None
        estado.borrador = {}
        return respuestas

    # Mensaje no reconocido
    decir("No entendí tu mensaje. Usa *➕ Nuevo reporte*, *⏸️ Mis pendientes* o escribe *Ayuda*.")
    return respuestas


def registrar_evidencia_foto(tecnico: str, url_foto: str) -> str:
    """Anexa una foto enviada por el usuario al borrador de evidencias."""
    estado = get_estado(tecnico)
    if estado.esperando == "evidencia":
        if "evidencias" not in estado.borrador:
            estado.borrador["evidencias"] = []
        estado.borrador["evidencias"].append(url_foto)
        cant = len(estado.borrador["evidencias"])
        return f"📷 Foto {cant} agregada al borrador. Manda otra foto o responde *'Continuar'* para finalizar."
    return "Manda '➕ Nuevo reporte' para iniciar un registro antes de enviar evidencias."


def _mostrar_confirmacion(estado, decir):
    b = estado.borrador
    cant_fotos = len(b.get("evidencias", []))
    txt_evidencia = f"{cant_fotos} foto(s) agregada(s)" if cant_fotos > 0 else "Sin fotos"

    estado.esperando = "confirmacion"
    resumen = (
        f"📋 *Confirmación del Reporte*\n\n"
        f"• *Ticket:* {b.get('ticket', 'N/A')}\n"
        f"• *Ubicación:* {b.get('ubicacion', 'N/A')}\n"
        f"• *Actividad:* {b.get('actividad', 'N/A')}\n"
        f"• *Estado:* {b.get('estado', 'Terminado')}\n"
        f"• *Evidencias:* {txt_evidencia}\n\n"
        f"¿Deseas guardar este reporte?\n"
        f"✅ *Guardar*  |  ✏️ *Editar*  |  ❌ *Cancelar*"
    )
    decir(resumen)
