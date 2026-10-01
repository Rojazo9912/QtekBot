"""
Máquina de estados desacoplada del canal (Telegram y Web App).
Implementa el flujo de conversación de 5 pasos definido en el PRD v1.1:
1) Ticket
2) Ubicación
3) Actividad
4) Estado
5) Evidencia (fotos opcionales a Supabase Storage)
Confirmación: ✅ Guardar / ✏️ Editar / ❌ Cancelar
Navegación: ➕ Nuevo reporte · ⏸️ Mis pendientes · 📋 Mis reportes
"""
import datetime as dt
import unicodedata

from app import db
from app.config import (
    ADMIN_TECNICOS,
    CATALOGO_UBICACION,
    CATALOGO_ESTADO_REPORTE,
    ZONA_HORARIA,
)
from app.state import get_estado

_CANCELAR_COMANDOS = ("cancelar", "cancel", "abortar", "/cancel", "salir")


def _ahora() -> dt.datetime:
    return dt.datetime.now(ZONA_HORARIA)


def _remover_acentos(texto: str) -> str:
    """Elimina acentos y emoji y pasa a minúsculas para comparaciones flexibles.
    Quitar los emoji (categoría "So") hace que "✏️ Editar", "✏ Editar" y
    "Editar" coincidan igual: al quitar acentos también se va el selector de
    variación U+FE0F, así que comparar contra literales con emoji no sirve."""
    if not texto:
        return ""
    nfd = unicodedata.normalize("NFD", texto)
    limpio = "".join(c for c in nfd if unicodedata.category(c) not in ("Mn", "So"))
    return " ".join(limpio.lower().split())


_SIN_TICKET_KEYWORDS = (
    "sin ticket",
    "sin tickets",
    "no tengo ticket",
    "no tengo tickets",
    "no tengo",
    "no hay ticket",
    "no hay",
    "omitir",
    "s/t",
    "st",
    "n/a",
    "na",
    "ninguno",
    "ninguna",
    "sin folio",
    "sin orden",
)


def generar_ticket_temporal() -> str:
    """Genera un identificador temporal para reportes sin ticket oficial,
    ej. 'S/T-260924-092530'."""
    ahora = _ahora()
    return f"S/T-{ahora.strftime('%y%m%d-%H%M%S')}"


def _es_sin_ticket(texto: str) -> bool:
    t = _remover_acentos(texto)
    if t in _SIN_TICKET_KEYWORDS:
        return True
    if t.startswith("sin ticket") or t.startswith("no tengo"):
        return True
    return False


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
            codigo = db.agregar_tecnico(nombre_nuevo)
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
            print(f"[admin] error registrando técnico: {e}")
            decir("❌ No pude registrar al técnico por un error con la base de datos. Intenta más tarde.")
            estado.esperando = None
        return respuestas

    # --- NAVEGACIÓN DEL MENÚ PRINCIPAL ---
    if t_norm in ("nuevo reporte", "+ nuevo reporte", "/nuevo_reporte", "nueva actividad", "+ nueva actividad", "/start"):
        # Reiniciar borrador y comenzar Paso 1 (Ticket)
        estado.borrador = {"evidencias": []}
        estado.esperando = "ticket"
        decir(
            "🎫 *Paso 1 de 5 — Ticket*\n\n"
            "Ingresa el número de ticket u orden de trabajo (ej. TK-001254).\n"
            "Si no cuentas con ticket, pulsa *'Sin ticket'* o escribe *'Sin ticket'*:"
        )
        return respuestas

    if t_norm in ("mis pendientes", "mis actividades", "/pendientes"):
        pendientes = db.listar_reportes_pendientes(tecnico)
        if not pendientes:
            decir("⏸️ No tienes reportes en estado Pendiente.")
            return respuestas

        lineas = ["⏸️ *Tus reportes pendientes:*"]
        for p in pendientes:
            lineas.append(f"• *{p['numero']}* (Ticket: {p['ticket']}) — {p['ubicacion']}: {p['actividad']}")
        lineas.append("\nResponde con el número de reporte (ej. `#001` o `001`) que deseas continuar o actualizar:")
        estado.esperando = "seleccion_pendiente"
        estado.borrador = {"pendientes": [p["numero"] for p in pendientes]}
        decir("\n".join(lineas))
        return respuestas

    if t_norm in ("mis reportes", "historial", "/reportes"):
        reportes = db.listar_mis_reportes(tecnico, limite=10)
        if not reportes:
            decir("📋 No tienes reportes registrados aún.")
            return respuestas

        iconos = {"Terminado": "✅", "Pendiente": "⏸️", "No solucionado": "❌"}
        lineas = ["📋 *Tus últimos reportes:*"]
        for r in reportes:
            icono = iconos.get(r["estado"], "•")
            lineas.append(f"{icono} *{r['numero']}* | Ticket: {r['ticket']} | {r['ubicacion']} ({r['fecha']})")
        decir("\n".join(lineas))
        return respuestas

    if t_norm in ("nuevo tecnico", "+ nuevo tecnico", "/nuevo_tecnico", "dar de alta"):
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
            lineas.append("• *📊 Exportar Excel*: Reporte de la semana actual.")
            lineas.append("• `/reporte AAAA-MM-DD AAAA-MM-DD`: Reporte en Excel de otro periodo.")
        decir("\n".join(lineas))
        return respuestas

    # --- MÁQUINA DE ESTADOS (FLUJO DE 5 PASOS PRD V1.1) ---

    # Paso 1: Ticket
    if estado.esperando == "ticket":
        if _es_sin_ticket(texto_limpio):
            ticket_asignado = generar_ticket_temporal()
            estado.borrador["ticket"] = ticket_asignado
            decir(f"🎫 Se asignó el ticket temporal: *{ticket_asignado}*")
        else:
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
            if t_norm and (_remover_acentos(u) == t_norm or t_norm in _remover_acentos(u)):
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
        if estado_norm not in CATALOGO_ESTADO_REPORTE:
            decir(f"Elige uno de estos estados: {', '.join(CATALOGO_ESTADO_REPORTE)}.")
            return respuestas
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
        if t_norm in ("guardar", "si", "confirmar", "ok"):
            try:
                b = estado.borrador
                numero_creado = db.crear_reporte(
                    ticket=b.get("ticket", "N/A"),
                    tecnico=tecnico,
                    ubicacion=b.get("ubicacion", "Nivel 10"),
                    actividad=b.get("actividad", ""),
                    estado=b.get("estado", "Terminado"),
                    evidencias=b.get("evidencias", []),
                )
                now = _ahora()
                decir(
                    f"✅ *Reporte guardado exitosamente*\n\n"
                    f"• *Número:* {numero_creado}\n"
                    f"• *Ticket:* {b.get('ticket')}\n"
                    f"• *Ubicación:* {b.get('ubicacion')}\n"
                    f"• *Actividad:* {b.get('actividad')}\n"
                    f"• *Estado:* {b.get('estado')}\n"
                    f"• *Departamento:* Infraestructura\n"
                    f"• *Fecha:* {now.strftime('%Y-%m-%d')}\n"
                    f"• *Hora:* {now.strftime('%H:%M:%S')}"
                )
                estado.borrador = {}
                estado.esperando = None
            except Exception as e:
                print(f"[reporte] error guardando en la base de datos: {e}")
                decir("❌ No pude guardar el reporte. Tu borrador sigue aquí: responde *Guardar* para reintentar.")
            return respuestas

        elif t_norm in ("editar", "corregir", "reiniciar"):
            estado.borrador = {"evidencias": []}
            estado.esperando = "ticket"
            decir(
                "✏️ Reiniciando el reporte.\n\n"
                "🎫 *Paso 1 de 5 — Ticket*\n\n"
                "Ingresa el número de ticket (o pulsa *'Sin ticket'* si no tienes):"
            )
            return respuestas

        elif t_norm in ("cancelar", "no"):
            estado.borrador = {}
            estado.esperando = None
            decir("❌ Reporte cancelado.")
            return respuestas
        else:
            decir("Responde *Guardar*, *Editar* o *Cancelar* para continuar.")
            return respuestas

    # Flujo de Continuar / Actualizar Pendiente
    if estado.esperando == "seleccion_pendiente":
        id_reporte = db.parsear_numero(texto_limpio)
        if id_reporte is None:
            decir("Por favor ingresa el número de reporte (ej. `#001` o `001`).")
            return respuestas
        num_formateado = db.formatear_numero(id_reporte)
        if num_formateado not in estado.borrador.get("pendientes", []):
            decir(f"El reporte {num_formateado} no está en tu lista de pendientes. Escribe uno de la lista o *Cancelar*.")
            return respuestas
        estado.folio_activo = num_formateado
        estado.borrador = {}
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
        if nuevo_est not in CATALOGO_ESTADO_REPORTE:
            decir(f"Elige uno de estos estados: {', '.join(CATALOGO_ESTADO_REPORTE)}.")
            return respuestas
        num_target = estado.folio_activo
        nueva_act = estado.borrador.get("nueva_actividad", "")
        try:
            exito = db.actualizar_reporte_pendiente(
                num_target, tecnico=tecnico, nueva_actividad=nueva_act, nuevo_estado=nuevo_est,
            )
            if exito:
                decir(f"✅ Reporte *{num_target}* actualizado a estado *{nuevo_est}*.")
            else:
                decir(f"❌ El reporte {num_target} ya no está pendiente o no es tuyo.")
        except Exception as e:
            print(f"[pendiente] error actualizando reporte: {e}")
            decir("❌ No pude actualizar el reporte. Intenta más tarde.")
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
