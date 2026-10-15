"""
Máquina de estados desacoplada del canal (Telegram y Web App).
Implementa el flujo de conversación de 7 pasos definido en el PRD v1.1:
1) Ticket
2) Departamento
3) Ubicación / Zona
4) Actividad
5) Estado
6) Evidencia (fotos opcionales a Supabase Storage con marca de agua)
7) Confirmación interactiva: ✅ Guardar / ✏️ Editar (granular) / ❌ Cancelar

Soporta además:
- Registro Rápido One-Shot (/registro Ticket | Depto | Zona | Actividad | Estado)
- Búsqueda por Ticket y Folio (/buscar, /ticket)
- Consulta por Zona (/zona)
- Navegación: ➕ Nuevo reporte · ⏸️ Mis pendientes · 📋 Mis reportes
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
from app.state import get_estado, persistir_estado, resetear_estado

_CANCELAR_COMANDOS = ("cancelar", "cancel", "abortar", "/cancel", "salir")


def _ahora() -> dt.datetime:
    return dt.datetime.now(ZONA_HORARIA)


def _remover_acentos(texto: str) -> str:
    """Elimina acentos y emoji y pasa a minúsculas para comparaciones flexibles."""
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
    es_admin = db.es_admin(tecnico)
    t_norm = _remover_acentos(texto_limpio)

    # Permitir cancelar en cualquier momento
    if t_norm in _CANCELAR_COMANDOS:
        resetear_estado(tecnico)
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
        persistir_estado(tecnico)
        return respuestas

    # Flujo de Admin: Alta de nuevo departamento
    if estado.esperando == "admin_nombre_departamento":
        nombre_nuevo = texto_limpio
        try:
            creado = db.agregar_departamento(nombre_nuevo)
            estado.esperando = None
            if creado:
                decir(f"✅ Departamento creado: *{nombre_nuevo}*.")
            else:
                decir(f"El departamento *{nombre_nuevo}* ya existe o es inválido.")
        except Exception as e:
            print(f"[admin] error registrando departamento: {e}")
            decir("❌ No pude registrar el departamento por un error con la base de datos.")
            estado.esperando = None
        persistir_estado(tecnico)
        return respuestas

    # --- COMANDO DE REGISTRO RÁPIDO (ONE-SHOT) ---
    if t_norm.startswith("/registro") or t_norm.startswith("/reporte_rapido"):
        partes_str = texto_limpio.removeprefix("/registro").removeprefix("/reporte_rapido").strip()
        if not partes_str:
            decir(
                "⚡ *Registro Rápido en 1 solo mensaje (One-Shot):*\n\n"
                "Formato:\n`/registro <Ticket> | <Departamento> | <Zona> | <Actividad> | <Estado>`\n\n"
                "*Ejemplo:*\n"
                "`/registro TK-102 | Infraestructura | Nivel 10 | Ajuste de Leaky Feeder | Terminado`\n\n"
                "O sin ticket:\n"
                "`/registro Sin ticket | Mantenimiento | Nivel 11 | Revisión general | Pendiente`"
            )
            return respuestas

        campos = [c.strip() for c in partes_str.split("|")]
        if len(campos) < 4:
            decir("❌ Formato incompleto. Usa:\n`/registro <Ticket> | <Departamento> | <Zona> | <Actividad> | <Estado>`")
            return respuestas

        if len(campos) == 4:
            raw_tkt, raw_zona, raw_act, raw_est = campos
            raw_dep = "Infraestructura"
        else:
            raw_tkt, raw_dep, raw_zona, raw_act, raw_est = campos[:5]

        # Ticket
        ticket_val = generar_ticket_temporal() if _es_sin_ticket(raw_tkt) else raw_tkt

        # Departamento
        try:
            deptos = db.listar_departamentos()
        except Exception:
            deptos = ["Infraestructura"]
        depto_val = next((d for d in deptos if _remover_acentos(d) == _remover_acentos(raw_dep)), raw_dep or "Infraestructura")

        # Zona
        try:
            zona_val = db.asegurar_zona(raw_zona)
        except Exception:
            zona_val = raw_zona

        # Estado
        estado_val = _normalizar_estado(raw_est)
        if estado_val not in CATALOGO_ESTADO_REPORTE:
            estado_val = "Terminado"

        estado.borrador = {
            "ticket": ticket_val,
            "departamento": depto_val,
            "ubicacion": zona_val,
            "actividad": raw_act,
            "estado": estado_val,
            "evidencias": [],
        }
        _mostrar_confirmacion(estado, decir)
        persistir_estado(tecnico)
        return respuestas

    # --- COMANDOS DE BÚSQUEDA Y CONSULTA ---
    if t_norm.startswith("/buscar") or t_norm.startswith("/ticket"):
        partes = texto_limpio.split(maxsplit=1)
        termino = partes[1].strip() if len(partes) > 1 else ""
        if not termino:
            decir("🔍 Usa: `/buscar <ticket o folio>` (ej. `/buscar TK-001` o `/buscar #002`).")
            return respuestas
        encontrados = db.buscar_reporte(termino)
        if not encontrados:
            decir(f"🔍 No se encontraron reportes coincidentes con: *{termino}*")
            return respuestas
        lineas = [f"🔍 *Resultados de búsqueda para '{termino}':*"]
        for r in encontrados:
            lineas.append(
                f"\n• *{r['numero']}* | Ticket: `{r['ticket']}`\n"
                f"  🏢 {r['departamento']} | 📍 {r['ubicacion']}\n"
                f"  📝 {r['actividad']}\n"
                f"  📊 Estado: *{r['estado']}* | 👤 {r['tecnico']} ({r['fecha']})"
            )
            if r.get("evidencias"):
                lineas.append(f"  📷 {len(r['evidencias'])} foto(s) de evidencia")
        decir("\n".join(lineas))
        return respuestas

    if t_norm.startswith("/zona"):
        partes = texto_limpio.split(maxsplit=1)
        zona_b = partes[1].strip() if len(partes) > 1 else ""
        if not zona_b:
            decir("📍 Usa: `/zona <nombre>` (ej. `/zona Nivel 10`).")
            return respuestas
        encontrados = db.listar_reportes_por_zona(zona_b)
        if not encontrados:
            decir(f"📍 No se encontraron reportes registrados en la zona: *{zona_b}*")
            return respuestas
        lineas = [f"📍 *Reportes recientes en {zona_b}:*"]
        for r in encontrados:
            lineas.append(f"• *{r['numero']}* [{r['estado']}] | Ticket: {r['ticket']} — {r['actividad']} ({r['fecha']})")
        decir("\n".join(lineas))
        return respuestas

    # --- NAVEGACIÓN DEL MENÚ PRINCIPAL ---
    if t_norm in ("nuevo reporte", "+ nuevo reporte", "/nuevo_reporte", "nueva actividad", "+ nueva actividad", "/start"):
        # Reiniciar borrador y comenzar Paso 1 (Ticket)
        estado.borrador = {"evidencias": []}
        estado.esperando = "ticket"
        decir(
            "🎫 *Paso 1 de 7 — Ticket*\n\n"
            "Ingresa el número de ticket u orden de trabajo (ej. TK-001254).\n"
            "Si no cuentas con ticket, pulsa *'Sin ticket'* o escribe *'Sin ticket'*:"
        )
        persistir_estado(tecnico)
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
        persistir_estado(tecnico)
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
        persistir_estado(tecnico)
        return respuestas

    if t_norm in ("departamentos", "departamento", "/departamentos", "/departamento", "ver departamentos"):
        if not es_admin:
            decir("No tienes permisos de administrador para consultar departamentos.")
            return respuestas
        try:
            nombres = db.listar_departamentos()
            lista = "\n".join(f"{i}. {n}" for i, n in enumerate(nombres, 1)) or "No hay departamentos registrados."
            decir(f"🏢 *Departamentos disponibles:*\n\n{lista}")
        except Exception as e:
            print(f"[departamentos] error: {e}")
            decir("❌ No pude consultar los departamentos.")
        return respuestas

    if t_norm in ("nuevo departamento", "+ nuevo departamento", "/nuevo_departamento"):
        if not es_admin:
            decir("No tienes permisos de administrador para agregar departamentos.")
            return respuestas
        estado.esperando = "admin_nombre_departamento"
        decir("🏢 Escribe el nombre del nuevo departamento que deseas registrar (o Cancelar):")
        persistir_estado(tecnico)
        return respuestas

    if t_norm in ("ayuda", "comandos", "/help"):
        lineas = [
            "🤖 *Comandos de Reporte de Campo:*",
            "• *➕ Nuevo reporte*: Inicia el registro de un reporte paso a paso (7 pasos).",
            "• `/registro ...`: Registro rápido en un solo mensaje (One-Shot).",
            "• *⏸️ Mis pendientes*: Muestra y permite continuar reportes pendientes.",
            "• *📋 Mis reportes*: Muestra tu historial de reportes.",
            "• `/buscar <ticket>`: Busca el estado y detalle de un ticket.",
            "• `/zona <nombre>`: Consulta los reportes en una zona.",
            "• *Cancelar*: Cancela el proceso actual.",
        ]
        if es_admin:
            lineas.append("\n👑 *Comandos de Administrador:*")
            lineas.append("• *👤 + Nuevo técnico*: Genera código de activación para un técnico nuevo.")
            lineas.append("• `/nuevo_departamento Nombre`: Registra un departamento nuevo.")
            lineas.append("• `/departamentos`: Consulta los departamentos disponibles.")
            lineas.append("• *📊 Exportar Excel*: Descarga reporte semanal en Excel.")
            lineas.append("• `/reporte AAAA-MM-DD AAAA-MM-DD`: Reporte Excel de otro periodo.")
            lineas.append("• `/fotos [desde] [hasta]`: Descarga ZIP con fotos de evidencias.")
        decir("\n".join(lineas))
        return respuestas

    # --- MÁQUINA DE ESTADOS (FLUJO DE 7 PASOS) ---

    # Paso 1: Ticket
    if estado.esperando == "ticket":
        if _es_sin_ticket(texto_limpio):
            ticket_asignado = generar_ticket_temporal()
            estado.borrador["ticket"] = ticket_asignado
            decir(f"🎫 Se asignó el ticket temporal: *{ticket_asignado}*")
        else:
            estado.borrador["ticket"] = texto_limpio

        estado.esperando = "departamento"
        try:
            departamentos = db.listar_departamentos()
        except Exception:
            departamentos = ["Infraestructura"]
        decir("🏢 *Paso 2 de 7 — Departamento*\n\nSelecciona el departamento:\n" + "\n".join(f"• {d}" for d in departamentos))
        persistir_estado(tecnico)
        return respuestas

    # Paso 2: Departamento
    if estado.esperando == "departamento":
        try:
            departamentos = db.listar_departamentos()
        except Exception:
            departamentos = ["Infraestructura"]
        departamento = next((d for d in departamentos if _remover_acentos(d) == t_norm), None)
        if not departamento:
            decir("Selecciona un departamento válido de la lista.")
            return respuestas
        estado.borrador["departamento"] = departamento
        estado.esperando = "ubicacion"
        try:
            zonas = db.listar_zonas()
        except Exception:
            zonas = CATALOGO_UBICACION
        decir("📍 *Paso 3 de 7 — Zona*\n\nSelecciona la zona o escribe Otra:\n" + "\n".join(f"• {z}" for z in zonas))
        persistir_estado(tecnico)
        return respuestas

    # Paso 3: Ubicación / Zona
    if estado.esperando == "ubicacion":
        if t_norm in ("otra", "otra ubicacion"):
            estado.esperando = "ubicacion_otra"
            decir("📍 Escribe la ubicación personalizada:")
            persistir_estado(tecnico)
            return respuestas

        try:
            zonas = db.listar_zonas()
        except Exception:
            zonas = CATALOGO_UBICACION

        ubicacion_sel = None
        for z in zonas:
            if t_norm and (_remover_acentos(z) == t_norm or t_norm in _remover_acentos(z)):
                ubicacion_sel = z
                break
        if not ubicacion_sel:
            try:
                ubicacion_sel = db.asegurar_zona(texto_limpio)
            except Exception:
                ubicacion_sel = texto_limpio

        estado.borrador["ubicacion"] = ubicacion_sel
        estado.esperando = "actividad"
        decir("📝 *Paso 4 de 7 — Actividad*\n\nDescribe brevemente la actividad realizada:")
        persistir_estado(tecnico)
        return respuestas

    if estado.esperando == "ubicacion_otra":
        estado.borrador["ubicacion"] = db.asegurar_zona(texto_limpio)
        estado.esperando = "actividad"
        decir("📝 *Paso 4 de 7 — Actividad*\n\nDescribe brevemente la actividad realizada:")
        persistir_estado(tecnico)
        return respuestas

    # Paso 4: Actividad
    if estado.esperando == "actividad":
        estado.borrador["actividad"] = texto_limpio
        estado.esperando = "estado"
        opciones_estado = "\n".join([f"• {e}" for e in CATALOGO_ESTADO_REPORTE])
        decir(f"📊 *Paso 5 de 7 — Estado*\n\nSelecciona el estado final del reporte:\n{opciones_estado}")
        persistir_estado(tecnico)
        return respuestas

    # Paso 5: Estado
    if estado.esperando == "estado":
        estado_norm = _normalizar_estado(texto_limpio)
        if estado_norm not in CATALOGO_ESTADO_REPORTE:
            decir(f"Elige uno de estos estados: {', '.join(CATALOGO_ESTADO_REPORTE)}.")
            return respuestas
        estado.borrador["estado"] = estado_norm
        estado.esperando = "evidencia"
        decir(
            "📷 *Paso 6 de 7 — Evidencia Fotográfica*\n\n"
            "Manda una o varias fotos de evidencia por el chat, o responde *'Omitir'* para continuar sin fotos."
        )
        persistir_estado(tecnico)
        return respuestas

    # Paso 6: Evidencia fotográfica
    if estado.esperando == "evidencia":
        if t_norm in ("omitir", "continuar", "listo", "sin fotos", "no"):
            _mostrar_confirmacion(estado, decir)
            persistir_estado(tecnico)
            return respuestas
        else:
            decir("Manda una foto por el chat o responde *'Omitir'* / *'Continuar'* para pasar a la confirmación.")
            return respuestas

    # Paso 7: Confirmación previa a guardado
    if estado.esperando == "confirmacion":
        if t_norm in ("guardar", "si", "confirmar", "ok"):
            try:
                b = estado.borrador
                depto = b.get("departamento", "Infraestructura")
                numero_creado = db.crear_reporte(
                    ticket=b.get("ticket", "N/A"),
                    tecnico=tecnico,
                    ubicacion=b.get("ubicacion", "Nivel 10"),
                    actividad=b.get("actividad", ""),
                    estado=b.get("estado", "Terminado"),
                    departamento=depto,
                    evidencias=b.get("evidencias", []),
                )
                now = _ahora()
                decir(
                    f"✅ *Reporte guardado exitosamente*\n\n"
                    f"• *Número:* {numero_creado}\n"
                    f"• *Ticket:* {b.get('ticket')}\n"
                    f"• *Departamento:* {depto}\n"
                    f"• *Ubicación:* {b.get('ubicacion')}\n"
                    f"• *Actividad:* {b.get('actividad')}\n"
                    f"• *Estado:* {b.get('estado')}\n"
                    f"• *Fecha:* {now.strftime('%Y-%m-%d')}\n"
                    f"• *Hora:* {now.strftime('%H:%M:%S')}"
                )
                resetear_estado(tecnico)
            except Exception as e:
                print(f"[reporte] error guardando en la base de datos: {e}")
                decir("❌ No pude guardar el reporte. Tu borrador sigue aquí: responde *Guardar* para reintentar.")
            return respuestas

        elif t_norm in ("editar", "corregir", "cambiar"):
            estado.esperando = "editar_campo_seleccion"
            decir(
                "✏️ *¿Qué dato deseas corregir?*\n\n"
                "Selecciona el campo que deseas modificar:\n"
                "• 🎫 Ticket\n"
                "• 🏢 Departamento\n"
                "• 📍 Zona\n"
                "• 📝 Actividad\n"
                "• 📊 Estado\n"
                "• 📷 Fotos\n"
                "• 🔄 Reiniciar todo\n"
                "• ↩️ Volver"
            )
            persistir_estado(tecnico)
            return respuestas

        elif t_norm in ("reiniciar", "reiniciar todo"):
            estado.borrador = {"evidencias": []}
            estado.esperando = "ticket"
            decir(
                "🔄 *Reiniciando el reporte.*\n\n"
                "🎫 *Paso 1 de 7 — Ticket*\n\n"
                "Ingresa el número de ticket (o pulsa *'Sin ticket'* si no tienes):"
            )
            persistir_estado(tecnico)
            return respuestas

        elif t_norm in ("cancelar", "no"):
            resetear_estado(tecnico)
            decir("❌ Reporte cancelado.")
            return respuestas
        else:
            decir("Responde *Guardar*, *Editar* o *Cancelar* para continuar.")
            return respuestas

    # --- SUBFLUJO DE EDICIÓN GRANULAR ---
    if estado.esperando == "editar_campo_seleccion":
        if "ticket" in t_norm:
            estado.esperando = "editar_ticket"
            decir("🎫 Ingresa el nuevo número de ticket (o 'Sin ticket'):")
        elif "departamento" in t_norm or "depto" in t_norm:
            estado.esperando = "editar_departamento"
            try:
                deptos = db.listar_departamentos()
            except Exception:
                deptos = ["Infraestructura"]
            decir("🏢 Selecciona el departamento:\n" + "\n".join(f"• {d}" for d in deptos))
        elif "zona" in t_norm or "ubicacion" in t_norm:
            estado.esperando = "editar_zona"
            try:
                zonas = db.listar_zonas()
            except Exception:
                zonas = CATALOGO_UBICACION
            decir("📍 Selecciona la nueva zona o escribe Otra:\n" + "\n".join(f"• {z}" for z in zonas))
        elif "actividad" in t_norm:
            estado.esperando = "editar_actividad"
            decir("📝 Describe la nueva actividad realizada:")
        elif "estado" in t_norm:
            estado.esperando = "editar_estado"
            decir("📊 Selecciona el nuevo estado:\n" + "\n".join(f"• {e}" for e in CATALOGO_ESTADO_REPORTE))
        elif "foto" in t_norm or "evidencia" in t_norm:
            estado.esperando = "editar_fotos"
            cant = len(estado.borrador.get("evidencias", []))
            decir(f"📷 El borrador tiene actualmente {cant} foto(s).\n\nOpciones:\n• 🗑️ Borrar fotos\n• ➕ Agregar fotos\n• ↩️ Volver")
        elif "reiniciar" in t_norm:
            estado.borrador = {"evidencias": []}
            estado.esperando = "ticket"
            decir("🔄 Reiniciando reporte desde el Paso 1 (Ticket):")
        elif "volver" in t_norm or "cancelar" in t_norm:
            _mostrar_confirmacion(estado, decir)
        else:
            decir("Selecciona uno de los campos a editar (Ticket, Departamento, Zona, Actividad, Estado, Fotos) o 'Volver'.")
        persistir_estado(tecnico)
        return respuestas

    if estado.esperando == "editar_ticket":
        if _es_sin_ticket(texto_limpio):
            nuevo_tkt = generar_ticket_temporal()
            estado.borrador["ticket"] = nuevo_tkt
            decir(f"🎫 Ticket actualizado a temporal: *{nuevo_tkt}*")
        else:
            estado.borrador["ticket"] = texto_limpio
            decir(f"🎫 Ticket actualizado a: *{texto_limpio}*")
        _mostrar_confirmacion(estado, decir)
        persistir_estado(tecnico)
        return respuestas

    if estado.esperando == "editar_departamento":
        try:
            deptos = db.listar_departamentos()
        except Exception:
            deptos = ["Infraestructura"]
        dep = next((d for d in deptos if _remover_acentos(d) == t_norm), None)
        if not dep:
            decir("Selecciona un departamento válido de la lista.")
            return respuestas
        estado.borrador["departamento"] = dep
        decir(f"🏢 Departamento actualizado a: *{dep}*")
        _mostrar_confirmacion(estado, decir)
        persistir_estado(tecnico)
        return respuestas

    if estado.esperando == "editar_zona":
        if t_norm in ("otra", "otra ubicacion"):
            estado.esperando = "editar_zona_otra"
            decir("📍 Escribe la ubicación personalizada:")
            persistir_estado(tecnico)
            return respuestas
        try:
            zonas = db.listar_zonas()
        except Exception:
            zonas = CATALOGO_UBICACION
        ubic_sel = None
        for z in zonas:
            if t_norm and (_remover_acentos(z) == t_norm or t_norm in _remover_acentos(z)):
                ubic_sel = z
                break
        if not ubic_sel:
            try:
                ubic_sel = db.asegurar_zona(texto_limpio)
            except Exception:
                ubic_sel = texto_limpio
        estado.borrador["ubicacion"] = ubic_sel
        decir(f"📍 Zona actualizada a: *{ubic_sel}*")
        _mostrar_confirmacion(estado, decir)
        persistir_estado(tecnico)
        return respuestas

    if estado.esperando == "editar_zona_otra":
        nueva_zona = db.asegurar_zona(texto_limpio)
        estado.borrador["ubicacion"] = nueva_zona
        decir(f"📍 Zona actualizada a: *{nueva_zona}*")
        _mostrar_confirmacion(estado, decir)
        persistir_estado(tecnico)
        return respuestas

    if estado.esperando == "editar_actividad":
        estado.borrador["actividad"] = texto_limpio
        decir("📝 Actividad actualizada.")
        _mostrar_confirmacion(estado, decir)
        persistir_estado(tecnico)
        return respuestas

    if estado.esperando == "editar_estado":
        nuevo_est = _normalizar_estado(texto_limpio)
        if nuevo_est not in CATALOGO_ESTADO_REPORTE:
            decir(f"Elige uno de estos estados: {', '.join(CATALOGO_ESTADO_REPORTE)}.")
            return respuestas
        estado.borrador["estado"] = nuevo_est
        decir(f"📊 Estado actualizado a: *{nuevo_est}*")
        _mostrar_confirmacion(estado, decir)
        persistir_estado(tecnico)
        return respuestas

    if estado.esperando == "editar_fotos":
        if "borrar" in t_norm:
            estado.borrador["evidencias"] = []
            decir("🗑️ Fotos de evidencia eliminadas.")
            _mostrar_confirmacion(estado, decir)
        elif "agregar" in t_norm:
            estado.esperando = "evidencia"
            decir("📷 Envía la(s) foto(s) por el chat. Cuando termines, responde *'Continuar'*.")
        else:
            _mostrar_confirmacion(estado, decir)
        persistir_estado(tecnico)
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
        persistir_estado(tecnico)
        return respuestas

    if estado.esperando == "continuar_pendiente_actividad":
        estado.borrador["nueva_actividad"] = texto_limpio
        estado.esperando = "continuar_pendiente_estado"
        opciones_estado = "\n".join([f"• {e}" for e in CATALOGO_ESTADO_REPORTE])
        decir(f"📊 Selecciona el nuevo estado del reporte:\n{opciones_estado}")
        persistir_estado(tecnico)
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
        resetear_estado(tecnico)
        return respuestas

    # Mensaje no reconocido
    decir("No entendí tu mensaje. Usa *➕ Nuevo reporte*, `/registro ...` (One-Shot), *⏸️ Mis pendientes* o escribe *Ayuda*.")
    return respuestas


def registrar_evidencia_foto(tecnico: str, url_foto: str) -> str:
    """Anexa una foto enviada por el usuario al borrador de evidencias."""
    estado = get_estado(tecnico)
    if estado.esperando == "evidencia":
        if "evidencias" not in estado.borrador:
            estado.borrador["evidencias"] = []
        estado.borrador["evidencias"].append(url_foto)
        cant = len(estado.borrador["evidencias"])
        persistir_estado(tecnico)
        return f"📷 Foto {cant} agregada al borrador (con marca de agua). Manda otra foto o responde *'Continuar'* para finalizar."
    return "Manda '➕ Nuevo reporte' para iniciar un registro antes de enviar evidencias."


def _mostrar_confirmacion(estado, decir):
    b = estado.borrador
    cant_fotos = len(b.get("evidencias", []))
    txt_evidencia = f"{cant_fotos} foto(s) agregada(s)" if cant_fotos > 0 else "Sin fotos"

    estado.esperando = "confirmacion"
    resumen = (
        f"📋 *Confirmación del Reporte (Paso 7 de 7)*\n\n"
        f"• *Ticket:* {b.get('ticket', 'N/A')}\n"
        f"• *Departamento:* {b.get('departamento', 'Infraestructura')}\n"
        f"• *Ubicación:* {b.get('ubicacion', 'N/A')}\n"
        f"• *Actividad:* {b.get('actividad', 'N/A')}\n"
        f"• *Estado:* {b.get('estado', 'Terminado')}\n"
        f"• *Evidencias:* {txt_evidencia}\n\n"
        f"¿Deseas guardar este reporte?\n"
        f"✅ *Guardar*  |  ✏️ *Editar*  |  ❌ *Cancelar*"
    )
    decir(resumen)
