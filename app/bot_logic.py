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
        nombre_nuevo, proy_det = db.separar_nombre_y_proyecto(texto_limpio)
        proyecto_nuevo = proy_det if proy_det != "Ambos" else ""
        try:
            if proyecto_nuevo:
                codigo = db.agregar_tecnico(nombre_nuevo, proyecto=proyecto_nuevo)
            else:
                codigo = db.agregar_tecnico(nombre_nuevo)
            estado.esperando = None
            if not codigo:
                decir(f"El técnico {nombre_nuevo} ya estaba registrado en la lista de técnicos.")
            else:
                proy_txt = f" (Sede/Proyecto: *{proyecto_nuevo}*)" if proyecto_nuevo and proyecto_nuevo != "Ambos" else " (Acceso a todos los proyectos)"
                decir(
                    f"✅ Técnico agregado: *{nombre_nuevo}*{proy_txt}.\n\n"
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

    # Flujo de Admin: Alta de nuevo proyecto
    if estado.esperando == "admin_nombre_proyecto":
        partes = [p.strip() for p in texto_limpio.split("|")]
        nombre_p = partes[0]
        tipo_p = partes[1] if len(partes) > 1 else "Durango"
        cli_p = partes[2] if len(partes) > 2 else ""
        try:
            creado = db.agregar_proyecto(nombre_p, tipo=tipo_p, cliente=cli_p)
            estado.esperando = None
            if creado:
                decir(f"✅ Proyecto creado exitosamente: *{nombre_p}* ({tipo_p}) para cliente *{cli_p or 'N/A'}*.")
            else:
                decir(f"El proyecto *{nombre_p}* ya existe o es inválido.")
        except Exception as e:
            print(f"[admin] error registrando proyecto: {e}")
            decir("❌ No pude registrar el proyecto por un error con la base de datos.")
            estado.esperando = None
        persistir_estado(tecnico)
        return respuestas

    # Flujo de Admin: Seleccionar técnico para asignarle proyecto
    if estado.esperando == "admin_sel_tecnico_asignar":
        try:
            tecnicos_disponibles = db.listar_tecnicos()
        except Exception:
            tecnicos_disponibles = []
        tec_encontrado = None
        for t in tecnicos_disponibles:
            if _remover_acentos(t).lower() == t_norm or t_norm in _remover_acentos(t).lower():
                tec_encontrado = t
                break
        if not tec_encontrado:
            tec_encontrado = texto_limpio

        estado.borrador["tecnico_seleccionado"] = tec_encontrado
        estado.esperando = "admin_sel_proyecto_asignar"
        try:
            proyectos = db.listar_nombres_proyectos() + ["Ambos"]
        except Exception:
            proyectos = ["Mina San Dimas", "Proyectos Durango", "Ambos"]
        decir(
            f"👤 Técnico seleccionado: *{tec_encontrado}*\n\n"
            f"🏗️ *Selecciona a qué proyecto(s) tendrá acceso:*\n"
            + "\n".join(f"• {p}" for p in proyectos)
            + "\n\n(Pulsa una opción o escribe Cancelar):"
        )
        persistir_estado(tecnico)
        return respuestas

    # Flujo de Admin: Seleccionar proyecto para el técnico elegido
    if estado.esperando == "admin_sel_proyecto_asignar":
        tec_nom = estado.borrador.get("tecnico_seleccionado", "")
        try:
            proyectos_disponibles = db.listar_nombres_proyectos() + ["Ambos"]
        except Exception:
            proyectos_disponibles = ["Mina San Dimas", "Proyectos Durango", "Ambos"]
        proy_encontrado = None
        for p in proyectos_disponibles:
            if _remover_acentos(p).lower() == t_norm or t_norm in _remover_acentos(p).lower():
                proy_encontrado = p
                break
        if not proy_encontrado:
            proy_encontrado = texto_limpio

        try:
            ok = db.asignar_proyecto_tecnico(tec_nom, proy_encontrado)
            if ok:
                decir(f"✅ Se asignó el proyecto *{proy_encontrado}* al técnico *{tec_nom}* correctamente.")
            else:
                decir(f"❌ No se pudo actualizar el técnico *{tec_nom}*. Verifica que el nombre esté registrado.")
        except Exception as e:
            print(f"[admin] error asignando proyecto: {e}")
            decir("❌ Error de base de datos al asignar proyecto.")
        estado.esperando = None
        estado.borrador = {}
        persistir_estado(tecnico)
        return respuestas

    # --- COMANDO DE REGISTRO RÁPIDO (ONE-SHOT) ---
    if t_norm.startswith("/registro") or t_norm.startswith("/reporte_rapido"):
        partes_str = texto_limpio.removeprefix("/registro").removeprefix("/reporte_rapido").strip()
        if not partes_str:
            decir(
                "⚡ *Registro Rápido en 1 solo mensaje (One-Shot):*\n\n"
                "Formato completo (Mina o Durango):\n"
                "`/registro <Proyecto> | <Ticket> | <Departamento> | <Zona> | <Actividad> | <Estado>`\n\n"
                "*Ejemplo Mina:*\n"
                "`/registro Mina San Dimas | TK-102 | Infraestructura | Nivel 10 | Ajuste de Leaky Feeder | Terminado`\n\n"
                "*Ejemplo Durango:*\n"
                "`/registro Proyectos Durango | TK-501 | Soporte TI | Oficinas Qtek | Configuración Switch | Terminado`\n\n"
                "O formato estándar (asume Mina):\n"
                "`/registro Sin ticket | Mantenimiento | Nivel 11 | Revisión general | Pendiente`"
            )
            return respuestas

        campos = [c.strip() for c in partes_str.split("|")]
        if len(campos) < 4:
            decir("❌ Formato incompleto. Usa:\n`/registro [Proyecto |] <Ticket> | <Departamento> | <Zona> | <Actividad> | <Estado>`")
            return respuestas

        proyectos_disponibles = db.listar_nombres_proyectos()
        if len(campos) >= 6:
            raw_proy, raw_tkt, raw_dep, raw_zona, raw_act, raw_est = campos[:6]
        elif len(campos) == 5:
            # Si el primer campo coincide con un proyecto registrado
            if any(_remover_acentos(p) == _remover_acentos(campos[0]) for p in proyectos_disponibles):
                raw_proy, raw_tkt, raw_zona, raw_act, raw_est = campos
                raw_dep = "Infraestructura"
            else:
                raw_proy = "Mina San Dimas"
                raw_tkt, raw_dep, raw_zona, raw_act, raw_est = campos
        else:  # len == 4
            raw_proy = "Mina San Dimas"
            raw_tkt, raw_zona, raw_act, raw_est = campos
            raw_dep = "Infraestructura"

        proy_val = next((p for p in proyectos_disponibles if _remover_acentos(p) == _remover_acentos(raw_proy)), raw_proy or "Mina San Dimas")

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
            zona_val = db.asegurar_zona(raw_zona, proyecto=proy_val)
        except Exception:
            zona_val = raw_zona

        # Estado
        estado_val = _normalizar_estado(raw_est)
        if estado_val not in CATALOGO_ESTADO_REPORTE:
            estado_val = "Terminado"

        estado.borrador = {
            "proyecto": proy_val,
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
                f"  🏗️ {r.get('proyecto', 'Mina San Dimas')} | 🏢 {r['departamento']}\n"
                f"  📍 {r['ubicacion']} | 📝 {r['actividad']}\n"
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
            decir("📍 Usa: `/zona <nombre>` (ej. `/zona Nivel 10` o `/zona Oficinas Qtek`).")
            return respuestas
        encontrados = db.listar_reportes_por_zona(zona_b)
        if not encontrados:
            decir(f"📍 No se encontraron reportes registrados en la zona: *{zona_b}*")
            return respuestas
        lineas = [f"📍 *Reportes recientes en {zona_b}:*"]
        for r in encontrados:
            lineas.append(f"• *{r['numero']}* [{r['estado']}] | Ticket: {r['ticket']} — {r.get('proyecto', 'Mina')} — {r['actividad']} ({r['fecha']})")
        decir("\n".join(lineas))
        return respuestas

    if t_norm.startswith("/proyecto") or t_norm in ("proyectos", "/proyectos", "ver proyectos"):
        termino = ""
        if t_norm.startswith("/proyecto ") and len(texto_limpio.split(maxsplit=1)) > 1:
            termino = texto_limpio.split(maxsplit=1)[1].strip()
        if termino:
            try:
                encontrados = db.reportes_en_periodo(dt.date(2020, 1, 1), dt.date(2030, 1, 1), proyecto=termino)
            except Exception:
                encontrados = []
            if not encontrados:
                decir(f"🏗️ No se encontraron reportes registrados para el proyecto: *{termino}*")
                return respuestas
            lineas = [f"🏗️ *Reportes recientes en {termino}:*"]
            for r in encontrados[-10:]:
                lineas.append(f"• *{r['numero']}* [{r['estado']}] | Ticket: {r['ticket']} — {r['ubicacion']}: {r['actividad']} ({r['fecha']})")
            decir("\n".join(lineas))
            return respuestas

        proyectos = db.listar_proyectos()
        lineas = ["🏗️ *Proyectos y Sedes registradas:*"]
        for p in proyectos:
            tipo = p.get("tipo", "General")
            cli = f" (Cliente: {p['cliente']})" if p.get("cliente") else ""
            lineas.append(f"• *{p['nombre']}* — Tipo: {tipo}{cli}")
        if es_admin:
            lineas.append("\nPara agregar otro proyecto usa:\n`/nuevo_proyecto <Nombre> | <Tipo: Mina o Durango> | <Cliente>`")
        decir("\n".join(lineas))
        return respuestas
    # --- NAVEGACIÓN DEL MENÚ PRINCIPAL ---
    if t_norm in ("nuevo reporte", "+ nuevo reporte", "/nuevo_reporte", "nueva actividad", "+ nueva actividad", "/start"):
        estado.borrador = {"evidencias": []}
        proyectos = db.obtener_proyectos_de_tecnico(tecnico)
        if len(proyectos) == 1:
            estado.borrador["proyecto"] = proyectos[0]
            estado.esperando = "ticket"
            decir(
                f"🏗️ *Proyecto:* {proyectos[0]}\n\n"
                f"🎫 *Paso 2 de 8 — Ticket*\n\n"
                f"Ingresa el número de ticket u orden de trabajo (ej. TK-001254).\n"
                f"Si no cuentas con ticket, pulsa *'Sin ticket'* o escribe *'Sin ticket'*:"
            )
        else:
            estado.esperando = "proyecto"
            decir(
                "🏗️ *Paso 1 de 8 — Proyecto o Sede*\n\n"
                "Selecciona el proyecto o centro de trabajo:\n" + "\n".join(f"• {p}" for p in proyectos)
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
            lineas.append(f"• *{p['numero']}* (Ticket: {p['ticket']}) — {p.get('proyecto', 'Mina')} / {p['ubicacion']}: {p['actividad']}")
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
            lineas.append(f"{icono} *{r['numero']}* | {r.get('proyecto', 'Mina')} | Ticket: {r['ticket']} | {r['ubicacion']} ({r['fecha']})")
        decir("\n".join(lineas))
        return respuestas

    if t_norm.startswith("/nuevo_tecnico") or t_norm in ("nuevo tecnico", "+ nuevo tecnico", "dar de alta"):
        if not es_admin:
            decir("No tienes permisos de administrador para agregar técnicos.")
            return respuestas
        args = texto_limpio.removeprefix("/nuevo_tecnico").strip() if t_norm.startswith("/nuevo_tecnico") else ""
        if args:
            nombre_nuevo, proy_det = db.separar_nombre_y_proyecto(args)
            proyecto_nuevo = proy_det
            try:
                codigo = db.agregar_tecnico(nombre_nuevo, proyecto=proyecto_nuevo)
                if not codigo:
                    decir(f"El técnico *{nombre_nuevo}* ya estaba registrado en la lista de técnicos.")
                else:
                    proy_txt = f" (Sede/Proyecto: *{proyecto_nuevo}*)" if proyecto_nuevo != "Ambos" else " (Acceso a todos los proyectos)"
                    decir(
                        f"✅ Técnico agregado: *{nombre_nuevo}*{proy_txt}.\n\n"
                        f"Mándale este código para que active su cuenta:\n"
                        f"`/start {codigo}`"
                    )
            except Exception as e:
                print(f"[admin] error registrando técnico: {e}")
                decir("❌ No pude registrar al técnico por un error con la base de datos.")
            return respuestas
        estado.esperando = "admin_nombre_tecnico"
        decir("👤 Escribe el Nombre del técnico y opcionalmente su sede:\n`Nombre Completo | Proyecto` (ej. `Juan Pérez | Mina San Dimas` o escribe Cancelar):")
        persistir_estado(tecnico)
        return respuestas

    if t_norm.startswith("/asignar_proyecto") or t_norm.startswith("/asignar_tecnico") or t_norm in ("asignar proyecto", "asignar proyectos", "/asignar_proyecto", "/asignar_tecnico"):
        if not es_admin:
            decir("No tienes permisos de administrador para asignar proyectos a técnicos.")
            return respuestas
        args = texto_limpio.removeprefix("/asignar_proyecto").removeprefix("/asignar_tecnico").strip() if t_norm.startswith("/asignar") else ""
        if args and "|" in args:
            tec_nom, proy_nom = [p.strip() for p in args.split("|", 1)]
            if db.asignar_proyecto_tecnico(tec_nom, proy_nom):
                decir(f"✅ Se asignó el proyecto *{proy_nom}* al técnico *{tec_nom}* correctamente.")
            else:
                decir(f"❌ No se pudo actualizar el técnico *{tec_nom}*. Verifica que el nombre esté registrado.")
            return respuestas

        try:
            tecnicos = db.listar_tecnicos()
        except Exception:
            tecnicos = []
        if not tecnicos:
            decir("No hay técnicos registrados aún.")
            return respuestas
        estado.esperando = "admin_sel_tecnico_asignar"
        estado.borrador = {}
        decir(
            "👥 *Asignar Proyecto a Técnico*\n\n"
            "Selecciona el técnico al que deseas asignarle o cambiarle de proyecto:\n"
            + "\n".join(f"• {t}" for t in tecnicos)
            + "\n\n(Pulsa el botón de un técnico o escribe Cancelar):"
        )
        persistir_estado(tecnico)
        return respuestas

    if t_norm in ("tecnicos", "/tecnicos", "ver tecnicos", "listar tecnicos"):
        if not es_admin:
            decir("No tienes permisos de administrador para consultar la lista de técnicos.")
            return respuestas
        lista = db.listar_tecnicos_con_info()
        lineas = ["👥 *Técnicos y Proyectos Asignados:*"]
        for t in lista:
            rol = "👑 Admin" if t.get("es_admin") else "👷 Técnico"
            estado_cuenta = "✅ Activo" if t.get("activo") else "⏳ Pendiente código"
            lineas.append(f"• *{t['nombre']}* ({rol})\n  🏗️ Proyecto: *{t.get('proyecto', 'Ambos')}* | {estado_cuenta}")
        lineas.append("\nPara reasignar proyecto usa:\n`/asignar_proyecto <Técnico> | <Proyecto>`")
        decir("\n".join(lineas))
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

    if t_norm.startswith("/nuevo_proyecto") or t_norm in ("nuevo proyecto", "+ nuevo proyecto"):
        if not es_admin:
            decir("No tienes permisos de administrador para agregar proyectos.")
            return respuestas
        args = texto_limpio.removeprefix("/nuevo_proyecto").strip() if t_norm.startswith("/nuevo_proyecto") else ""
        if args:
            partes = [p.strip() for p in args.split("|")]
            nombre_p = partes[0]
            tipo_p = partes[1] if len(partes) > 1 else "Durango"
            cli_p = partes[2] if len(partes) > 2 else ""
            if db.agregar_proyecto(nombre=nombre_p, tipo=tipo_p, cliente=cli_p):
                decir(f"✅ Proyecto *{nombre_p}* guardado correctamente (Tipo: {tipo_p}).")
            else:
                decir(f"❌ No se pudo guardar el proyecto *{nombre_p}* (quizás ya existe o es inválido).")
            return respuestas
        estado.esperando = "admin_nombre_proyecto"
        decir("🏗️ Escribe los datos del nuevo proyecto en formato:\n`Nombre | Tipo (Mina/Durango) | Cliente`\n(o escribe Cancelar):")
        persistir_estado(tecnico)
        return respuestas

    if t_norm in ("ayuda", "comandos", "/help"):
        lineas = [
            "🤖 *Comandos de Reporte de Campo:*",
            "• *➕ Nuevo reporte*: Inicia el registro de un reporte paso a paso (8 pasos).",
            "• `/registro ...`: Registro rápido en un solo mensaje (One-Shot para Mina o Durango).",
            "• *⏸️ Mis pendientes*: Muestra y permite continuar reportes pendientes.",
            "• *📋 Mis reportes*: Muestra tu historial de reportes.",
            "• `/proyectos`: Consulta los proyectos y sedes disponibles (o `/proyecto <nombre>`).",
            "• `/buscar <ticket>`: Busca el estado y detalle de un ticket.",
            "• `/zona <nombre>`: Consulta los reportes en una zona.",
            "• *Cancelar*: Cancela el proceso actual.",
        ]
        if es_admin:
            lineas.append("• *👤 + Nuevo técnico*: Genera código de activación para un técnico nuevo.")
            lineas.append("• `/tecnicos`: Lista los técnicos y sus proyectos asignados.")
            lineas.append("• `/asignar_proyecto Técnico | Proyecto`: Cambia la sede asignada a un técnico.")
            lineas.append("• `/nuevo_proyecto Nombre | Tipo | Cliente`: Registra un proyecto nuevo.")
            lineas.append("• `/nuevo_departamento Nombre`: Registra un departamento nuevo.")
            lineas.append("• `/departamentos`: Consulta los departamentos disponibles.")
            lineas.append("• *📊 Exportar Excel*: Descarga reporte semanal en Excel.")
            lineas.append("• `/reporte [desde] [hasta] [proyecto]`: Reporte Excel filtrado o consolidado.")
            lineas.append("• `/fotos [desde] [hasta]`: Descarga ZIP con fotos de evidencias.")
        decir("\n".join(lineas))
        return respuestas

    # --- MÁQUINA DE ESTADOS (FLUJO DE 8 PASOS) ---

    # Paso 1: Proyecto / Sede
    if estado.esperando == "proyecto":
        proyectos_autorizados = db.obtener_proyectos_de_tecnico(tecnico)
        proy_sel = None
        for p in proyectos_autorizados:
            if t_norm and (_remover_acentos(p).lower() == t_norm or t_norm in _remover_acentos(p).lower()):
                proy_sel = p
                break
        if not proy_sel:
            todos_proyectos = db.listar_nombres_proyectos()
            es_proyecto_existente = any(_remover_acentos(p).lower() == t_norm or t_norm in _remover_acentos(p).lower() for p in todos_proyectos)
            if es_proyecto_existente and len(proyectos_autorizados) < len(todos_proyectos):
                decir(
                    f"⚠️ No tienes asignado ese proyecto. Tus proyectos autorizados son:\n"
                    + "\n".join(f"• {p}" for p in proyectos_autorizados)
                    + "\n\nSolicita a un administrador si requieres acceso a otro proyecto."
                )
                return respuestas
            proy_sel = proyectos_autorizados[0] if len(proyectos_autorizados) == 1 else texto_limpio

        estado.borrador["proyecto"] = proy_sel
        estado.esperando = "ticket"
        decir(
            f"🏗️ Proyecto: *{proy_sel}*\n\n"
            "🎫 *Paso 2 de 8 — Ticket*\n\n"
            "Ingresa el número de ticket u orden de trabajo (ej. TK-001254).\n"
            "Si no cuentas con ticket, pulsa *'Sin ticket'* o escribe *'Sin ticket'*:"
        )
        persistir_estado(tecnico)
        return respuestas

    # Paso 2: Ticket
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
        decir("🏢 *Paso 3 de 8 — Departamento*\n\nSelecciona el departamento:\n" + "\n".join(f"• {d}" for d in departamentos))
        persistir_estado(tecnico)
        return respuestas

    # Paso 3: Departamento
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

        proy_actual = estado.borrador.get("proyecto", "Mina San Dimas")
        try:
            zonas = db.listar_zonas(proyecto=proy_actual)
        except Exception:
            zonas = CATALOGO_UBICACION
        decir(f"📍 *Paso 4 de 8 — Zona / Ubicación ({proy_actual})*\n\nSelecciona la zona o escribe Otra:\n" + "\n".join(f"• {z}" for z in zonas))
        persistir_estado(tecnico)
        return respuestas

    # Paso 4: Ubicación / Zona
    if estado.esperando == "ubicacion":
        proy_actual = estado.borrador.get("proyecto")
        if t_norm in ("otra", "otra ubicacion"):
            estado.esperando = "ubicacion_otra"
            decir("📍 Escribe la ubicación personalizada:")
            persistir_estado(tecnico)
            return respuestas

        try:
            zonas = db.listar_zonas(proyecto=proy_actual)
        except Exception:
            zonas = CATALOGO_UBICACION

        ubicacion_sel = None
        for z in zonas:
            if t_norm and (_remover_acentos(z) == t_norm or t_norm in _remover_acentos(z)):
                ubicacion_sel = z
                break
        if not ubicacion_sel:
            try:
                if proy_actual:
                    ubicacion_sel = db.asegurar_zona(texto_limpio, proyecto=proy_actual)
                else:
                    ubicacion_sel = db.asegurar_zona(texto_limpio)
            except Exception:
                ubicacion_sel = texto_limpio

        estado.borrador["ubicacion"] = ubicacion_sel
        estado.esperando = "actividad"
        decir("📝 *Paso 5 de 8 — Actividad*\n\nDescribe brevemente la actividad realizada:")
        persistir_estado(tecnico)
        return respuestas

    if estado.esperando == "ubicacion_otra":
        proy_actual = estado.borrador.get("proyecto")
        if proy_actual:
            estado.borrador["ubicacion"] = db.asegurar_zona(texto_limpio, proyecto=proy_actual)
        else:
            estado.borrador["ubicacion"] = db.asegurar_zona(texto_limpio)
        estado.esperando = "actividad"
        decir("📝 *Paso 5 de 8 — Actividad*\n\nDescribe brevemente la actividad realizada:")
        persistir_estado(tecnico)
        return respuestas

    # Paso 5: Actividad
    if estado.esperando == "actividad":
        estado.borrador["actividad"] = texto_limpio
        estado.esperando = "estado"
        opciones_estado = "\n".join([f"• {e}" for e in CATALOGO_ESTADO_REPORTE])
        decir(f"📊 *Paso 6 de 8 — Estado*\n\nSelecciona el estado final del reporte:\n{opciones_estado}")
        persistir_estado(tecnico)
        return respuestas

    # Paso 6: Estado
    if estado.esperando == "estado":
        estado_norm = _normalizar_estado(texto_limpio)
        if estado_norm not in CATALOGO_ESTADO_REPORTE:
            decir(f"Elige uno de estos estados: {', '.join(CATALOGO_ESTADO_REPORTE)}.")
            return respuestas
        estado.borrador["estado"] = estado_norm
        estado.esperando = "evidencia"
        decir(
            "📷 *Paso 7 de 8 — Evidencia Fotográfica*\n\n"
            "Manda una o varias fotos de evidencia por el chat, o responde *'Omitir'* para continuar sin fotos."
        )
        persistir_estado(tecnico)
        return respuestas

    # Paso 7: Evidencia fotográfica
    if estado.esperando == "evidencia":
        if t_norm in ("omitir", "continuar", "listo", "sin fotos", "no"):
            _mostrar_confirmacion(estado, decir)
            persistir_estado(tecnico)
            return respuestas
        else:
            decir("Manda una foto por el chat o responde *'Omitir'* / *'Continuar'* para pasar a la confirmación.")
            return respuestas

    # Paso 8: Confirmación previa a guardado
    if estado.esperando == "confirmacion":
        if t_norm in ("guardar", "si", "confirmar", "ok"):
            try:
                b = estado.borrador
                depto = b.get("departamento", "Infraestructura")
                proy = b.get("proyecto", "Mina San Dimas")
                numero_creado = db.crear_reporte(
                    ticket=b.get("ticket", "N/A"),
                    tecnico=tecnico,
                    ubicacion=b.get("ubicacion", "Nivel 10"),
                    actividad=b.get("actividad", ""),
                    estado=b.get("estado", "Terminado"),
                    departamento=depto,
                    evidencias=b.get("evidencias", []),
                    proyecto=proy,
                )
                now = _ahora()
                decir(
                    f"✅ *Reporte guardado exitosamente*\n\n"
                    f"• *Número:* {numero_creado}\n"
                    f"• *Proyecto:* {proy}\n"
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
                "• 🏗️ Proyecto\n"
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
            estado.esperando = "proyecto"
            proyectos = db.listar_nombres_proyectos()
            decir(
                "🔄 *Reiniciando el reporte.*\n\n"
                "🏗️ *Paso 1 de 8 — Proyecto o Sede*\n\n"
                "Selecciona el proyecto o centro de trabajo:\n" + "\n".join(f"• {p}" for p in proyectos)
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
        if "proyecto" in t_norm:
            estado.esperando = "editar_proyecto"
            proyectos = db.listar_nombres_proyectos()
            decir("🏗️ Selecciona el nuevo proyecto o centro de trabajo:\n" + "\n".join(f"• {p}" for p in proyectos))
        elif "ticket" in t_norm:
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
            proy_act = estado.borrador.get("proyecto", "Mina San Dimas")
            try:
                zonas = db.listar_zonas(proyecto=proy_act)
            except Exception:
                zonas = CATALOGO_UBICACION
            decir(f"📍 Selecciona la nueva zona ({proy_act}) o escribe Otra:\n" + "\n".join(f"• {z}" for z in zonas))
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
            estado.esperando = "proyecto"
            proyectos = db.listar_nombres_proyectos()
            decir("🔄 Reiniciando reporte desde el Paso 1 (Proyecto):\n" + "\n".join(f"• {p}" for p in proyectos))
        elif "volver" in t_norm or "cancelar" in t_norm:
            _mostrar_confirmacion(estado, decir)
        else:
            decir("Selecciona uno de los campos a editar (Proyecto, Ticket, Departamento, Zona, Actividad, Estado, Fotos) o 'Volver'.")
        persistir_estado(tecnico)
        return respuestas

    if estado.esperando == "editar_proyecto":
        proyectos = db.listar_nombres_proyectos()
        proy_sel = None
        for p in proyectos:
            if t_norm and (_remover_acentos(p) == t_norm or t_norm in _remover_acentos(p)):
                proy_sel = p
                break
        if not proy_sel:
            proy_sel = texto_limpio
        estado.borrador["proyecto"] = proy_sel
        decir(f"🏗️ Proyecto actualizado a: *{proy_sel}*")
        _mostrar_confirmacion(estado, decir)
        persistir_estado(tecnico)
        return respuestas
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
        f"📋 *Confirmación del Reporte (Paso 8 de 8)*\n\n"
        f"• *Proyecto:* {b.get('proyecto', 'Mina San Dimas')}\n"
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
