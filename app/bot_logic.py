"""
Máquina de estados desacoplada del canal (Telegram y Web App).
Gestiona el flujo de creación, pausa, reanudación y finalización de tickets,
incluyendo soporte para zonas sin cobertura (hora de inicio y duración offline)
y flujos guiados para administradores (alta de técnicos y actualización de reportes).
"""
import datetime as dt
import re
import unicodedata
from zoneinfo import ZoneInfo
from app import sheets
from app.ai_extract import interpretar_mensaje
from app.config import (
    ADMIN_TECNICOS,
    CATALOGO_AREA,
    CATALOGO_PRIORIDAD,
    CATALOGO_TIPO_FALLA,
    DEFAULT_PRIORIDAD,
    DEFAULT_RECEPTOR,
    DEFAULT_RECOMENDACIONES,
    DEFAULT_MATERIALES,
)
from app.state import get_estado

_SIN_DATO = ("no", "ninguna", "ninguno", "n/a", "na", "-", "ningun", "ninguno.")
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
    "nuevo tecnico": "admin_nuevo_tecnico",
    "nuevo técnico": "admin_nuevo_tecnico",
    "+ nuevo tecnico": "admin_nuevo_tecnico",
    "+ nuevo técnico": "admin_nuevo_tecnico",
    "👤 + nuevo técnico": "admin_nuevo_tecnico",
    "👤 + nuevo tecnico": "admin_nuevo_tecnico",
    "/nuevo_tecnico": "admin_nuevo_tecnico",
    "dar de alta a un usuario": "admin_nuevo_tecnico",
    "dar de alta usuario": "admin_nuevo_tecnico",
    "dar de alta": "admin_nuevo_tecnico",
    "agregar tecnico": "admin_nuevo_tecnico",
    "agregar técnico": "admin_nuevo_tecnico",
    "reporte pdf": "admin_reporte",
    "📄 reporte pdf": "admin_reporte",
    "generar reporte": "admin_reporte",
    "reporte": "admin_reporte",
    "/reporte": "admin_reporte",
    "ayuda": "ayuda",
    "comandos": "ayuda",
    "/help": "ayuda",
}


def _ahora() -> dt.datetime:
    return dt.datetime.now(sheets.ZONA_HORARIA)


def _remover_acentos(texto: str) -> str:
    """Elimina acentos/diacríticos y pasa a minúsculas para comparaciones robustas."""
    if not texto:
        return ""
    nfd = unicodedata.normalize("NFD", texto)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower().strip()


def parsear_hora(texto: str) -> str | None:
    """Parsea una hora ingresada por el usuario (ej. '7:50', '07:50 am', '14:30',
    'hace 1 hora', 'ahora') y regresa formato 'HH:MM:SS' o None si no es válida."""
    t_norm = _remover_acentos(texto)
    now = _ahora()

    if t_norm in ("ahora", "ya", "actual", "tiempo real", "hoy", ""):
        return now.strftime("%H:%M:%S")

    # "hace X horas" o "hace X min"
    m_hace = re.match(r"hace\s+(\d+)\s*(h|hr|hrs|hora|horas|m|min|mins|minuto|minutos)", t_norm)
    if m_hace:
        cant = int(m_hace.group(1))
        unidad = m_hace.group(2)
        delta = dt.timedelta(hours=cant) if unidad.startswith("h") else dt.timedelta(minutes=cant)
        hora_calc = now - delta
        return hora_calc.strftime("%H:%M:%S")

    # Formatos estándar: 7:50, 07:50, 7:50 am, 7:50 pm, 19:50, 07:50:00
    m_hora = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?$", t_norm)
    if m_hora:
        horas = int(m_hora.group(1))
        minutos = int(m_hora.group(2))
        segundos = int(m_hora.group(3)) if m_hora.group(3) else 0
        ampm = m_hora.group(4)

        if ampm and ("pm" in ampm or "p.m." in ampm) and horas < 12:
            horas += 12
        elif ampm and ("am" in ampm or "a.m." in ampm) and horas == 12:
            horas = 0

        if 0 <= horas <= 23 and 0 <= minutos <= 59 and 0 <= segundos <= 59:
            return f"{horas:02d}:{minutos:02d}:{segundos:02d}"

    # Formato simple solo hora: '7 am', '8 pm', '14'
    m_simple = re.match(r"^(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)?$", t_norm)
    if m_simple:
        horas = int(m_simple.group(1))
        ampm = m_simple.group(2)
        if ampm and ("pm" in ampm or "p.m." in ampm) and horas < 12:
            horas += 12
        elif ampm and ("am" in ampm or "a.m." in ampm) and horas == 12:
            horas = 0
        if 0 <= horas <= 23:
            return f"{horas:02d}:00:00"

    return None


_MESES = {
    "enero": 1, "ene": 1,
    "febrero": 2, "feb": 2,
    "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6,
    "julio": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "septiembre": 9, "sep": 9, "sept": 9,
    "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}


def parsear_fecha(texto: str) -> str | None:
    """Parsea una fecha ingresada por el usuario (ej. 'ayer', 'antier', 'hace 3 días',
    '25 de agosto', '25/08', '2026-08-25') en cualquier parte del texto."""
    if not texto:
        return None
    t_norm = _remover_acentos(texto)
    now = _ahora().date()

    if re.search(r"\bayer\b", t_norm):
        return (now - dt.timedelta(days=1)).isoformat()

    if re.search(r"\b(antier|anteayer)\b", t_norm):
        return (now - dt.timedelta(days=2)).isoformat()

    m_hace_dias = re.search(r"\bhace\s+(\d+)\s*d(?:ia|ias)?\b", t_norm)
    if m_hace_dias:
        dias = int(m_hace_dias.group(1))
        return (now - dt.timedelta(days=dias)).isoformat()

    # Formato textual: '25 de agosto' o '25 de ago'
    m_texto_mes = re.search(
        r"\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)(?:\s+de\s+(\d{4}))?\b",
        t_norm,
    )
    if m_texto_mes:
        dia = int(m_texto_mes.group(1))
        mes_str = m_texto_mes.group(2)
        anio = int(m_texto_mes.group(3)) if m_texto_mes.group(3) else now.year
        mes = _MESES.get(mes_str)
        if mes:
            try:
                return dt.date(anio, mes, dia).isoformat()
            except ValueError:
                pass

    # Formato ISO: YYYY-MM-DD
    m_iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", texto)
    if m_iso:
        try:
            val = dt.date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
            return val.isoformat()
        except ValueError:
            pass

    # Formato latino: DD/MM/YYYY o DD/MM (ej: 25/08/2026 o 25/08)
    m_latino = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", texto)
    if m_latino:
        try:
            dia = int(m_latino.group(1))
            mes = int(m_latino.group(2))
            if m_latino.group(3):
                anio = int(m_latino.group(3))
                if anio < 100:
                    anio += 2000
            else:
                anio = now.year
            val = dt.date(anio, mes, dia)
            return val.isoformat()
        except ValueError:
            pass

    return None


def calcular_hora_fin(hora_inicio_str: str | None, duracion_texto: str) -> str:
    """Calcula la hora de finalización sumando la duración a la hora de inicio.
    Si la duración es 'ahora' o no se puede parsear, regresa la hora actual."""
    now = _ahora()
    t_norm = _remover_acentos(duracion_texto)

    if t_norm in ("ahora", "ya", "actual", "tiempo real", "no", "-"):
        return now.strftime("%H:%M:%S")

    total_minutos = 0

    m_colon = re.match(r"^(\d{1,2}):(\d{2})$", t_norm)
    if m_colon:
        total_minutos = int(m_colon.group(1)) * 60 + int(m_colon.group(2))

    if not total_minutos:
        m_hrs = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hora|horas)", t_norm)
        if m_hrs:
            total_minutos += int(float(m_hrs.group(1)) * 60)

        m_mins = re.search(r"(\d+)\s*(?:m|min|mins|minuto|minutos)", t_norm)
        if m_mins:
            total_minutos += int(m_mins.group(1))

        if "y media" in t_norm or "media hora" in t_norm:
            total_minutos += 30

    if not total_minutos and t_norm.isdigit():
        num = int(t_norm)
        total_minutos = num * 60 if num <= 12 else num

    if not total_minutos:
        return now.strftime("%H:%M:%S")

    hora_ini_obj = None
    if hora_inicio_str:
        try:
            partes = [int(p) for p in hora_inicio_str.split(":")]
            hora_ini_obj = dt.time(partes[0], partes[1], partes[2] if len(partes) > 2 else 0)
        except Exception:
            pass

    if not hora_ini_obj:
        hora_ini_obj = now.time()

    base_dt = dt.datetime.combine(now.date(), hora_ini_obj)
    fin_dt = base_dt + dt.timedelta(minutes=total_minutos)
    return fin_dt.strftime("%H:%M:%S")


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
    texto_limpio = texto.strip()
    if not texto_limpio:
        return None

    if texto_limpio.isdigit():
        idx = int(texto_limpio) - 1
        if 0 <= idx < len(catalogo):
            return catalogo[idx]

    texto_norm = _remover_acentos(texto_limpio)
    for opcion in catalogo:
        if _remover_acentos(opcion) == texto_norm:
            return opcion

    coincidencias = [
        opcion for opcion in catalogo
        if texto_norm in _remover_acentos(opcion) or _remover_acentos(opcion) in texto_norm
    ]
    if len(coincidencias) == 1:
        return coincidencias[0]

    return None


def procesar_mensaje_web(tecnico: str, texto: str) -> list[str]:
    """Devuelve la lista de mensajes que el bot contesta para este turno."""
    respuestas: list[str] = []

    def decir(msg: str):
        respuestas.append(msg)

    texto_limpio = texto.strip()
    if not texto_limpio:
        return respuestas

    estado = get_estado(tecnico)
    es_admin = tecnico in ADMIN_TECNICOS

    # Permitir cancelar en cualquier paso
    if _remover_acentos(texto_limpio) in _CANCELAR_COMANDOS:
        estado.esperando = None
        estado.borrador = {}
        decir("Operación cancelada. Puedes escribir 'nueva actividad' o usar los botones cuando estés listo.")
        return respuestas

    # Flujo de Administrador: Pidiendo Nombre de Técnico
    if estado.esperando == "admin_nombre_tecnico":
        nombre_nuevo = texto_limpio
        try:
            codigo = sheets.agregar_tecnico(nombre_nuevo)
            estado.esperando = None
            estado.borrador = {}
            if not codigo:
                decir(f"{nombre_nuevo} ya estaba registrado en la lista de técnicos.")
            else:
                decir(
                    f"✅ Técnico agregado: {nombre_nuevo}.\n\n"
                    f"Mándale este código para que active su cuenta (funciona una sola vez):\n"
                    f"/start {codigo}"
                )
        except Exception as e:
            print(f"[bot_logic] error agregando técnico: {e}")
            decir(f"Hubo un error al registrar el técnico en Google Sheets: {e}")
            estado.esperando = None
        return respuestas

    # Flujo de Administrador: Pidiendo Tipo / Departamento de Reporte
    if estado.esperando == "admin_tipo_reporte":
        t_norm = _remover_acentos(texto_limpio)
        if t_norm in ("general (todos)", "general", "todos", "1", "ambos"):
            estado.borrador["reporte_area"] = "Todos"
        elif t_norm in ("infraestructura", "2"):
            estado.borrador["reporte_area"] = "Infraestructura"
        elif t_norm in ("soporte", "3"):
            estado.borrador["reporte_area"] = "Soporte"
        elif t_norm in ("generar los 3 pdfs", "los 3 pdfs", "los 3", "3 pdfs", "4", "todos los reportes"):
            estado.borrador["reporte_area"] = "3_PDFS"
        else:
            decir("Elige una opción: 'General (Todos)', 'Infraestructura', 'Soporte' o 'Generar los 3 PDFs'.")
            return respuestas

        area_sel = estado.borrador["reporte_area"]
        nombre_area = "los 3 PDFs" if area_sel == "3_PDFS" else f"Área: {area_sel}"
        estado.esperando = "admin_periodo_reporte"
        decir(f"Periodo para el reporte ({nombre_area}):\n¿Para qué periodo deseas generarlo?")
        return respuestas

    # Flujo de Administrador: Pidiendo Periodo de Reporte
    if estado.esperando == "admin_periodo_reporte":
        t_norm = _remover_acentos(texto_limpio)
        hoy = _ahora().date()
        fecha_inicio = None
        fecha_fin = None

        if t_norm in ("semana actual", "1", "actual"):
            fecha_inicio = hoy - dt.timedelta(days=hoy.weekday())
            fecha_fin = fecha_inicio + dt.timedelta(days=6)
        elif t_norm in ("semana pasada", "2", "anterior", "pasada"):
            lunes_actual = hoy - dt.timedelta(days=hoy.weekday())
            fecha_inicio = lunes_actual - dt.timedelta(days=7)
            fecha_fin = fecha_inicio + dt.timedelta(days=6)
        elif t_norm in ("personalizado", "3", "fechas"):
            estado.esperando = "admin_fechas_reporte"
            decir("Escribe las fechas del periodo en formato: AAAA-MM-DD AAAA-MM-DD\n(Ejemplo: '2026-08-01 2026-08-15')")
            return respuestas
        else:
            # Intentar parsear dos fechas directas
            partes = texto_limpio.split()
            if len(partes) == 2:
                try:
                    fecha_inicio = dt.date.fromisoformat(partes[0])
                    fecha_fin = dt.date.fromisoformat(partes[1])
                except ValueError:
                    pass

        if not fecha_inicio or not fecha_fin:
            decir("No entendí la opción. Elige 'Semana actual', 'Semana pasada' o escribe 'AAAA-MM-DD AAAA-MM-DD'.")
            return respuestas

        area_sel = estado.borrador.get("reporte_area", "Todos")
        estado.esperando = None
        estado.borrador = {}
        try:
            if area_sel == "3_PDFS":
                decir(
                    f"📊 Reporte actualizado para el periodo {fecha_inicio.isoformat()} al {fecha_fin.isoformat()} "
                    "(Generando los 3 PDFs: General, Infraestructura y Soporte)..."
                )
            else:
                sheets.set_periodo_reporte(fecha_inicio, fecha_fin, area=area_sel)
                decir(
                    f"📊 Reporte actualizado para el periodo {fecha_inicio.isoformat()} al {fecha_fin.isoformat()} (Área: {area_sel}).\n\n"
                    "Ya puedes descargarlo desde Google Sheets en la hoja 'Reporte PDF' (Archivo > Descargar > Documento PDF)."
                )
        except Exception as e:
            print(f"[bot_logic] error fijando periodo: {e}")
            decir(f"Hubo un error al actualizar el periodo en Google Sheets: {e}")
        return respuestas

    # Flujo de Administrador: Pidiendo Fechas Personalizadas
    if estado.esperando == "admin_fechas_reporte":
        partes = texto_limpio.split()
        if len(partes) == 2:
            try:
                fecha_inicio = dt.date.fromisoformat(partes[0])
                fecha_fin = dt.date.fromisoformat(partes[1])
                area_sel = estado.borrador.get("reporte_area", "Todos")
                estado.esperando = None
                estado.borrador = {}
                if area_sel == "3_PDFS":
                    decir(
                        f"📊 Reporte actualizado para el periodo {fecha_inicio.isoformat()} al {fecha_fin.isoformat()} "
                        "(Generando los 3 PDFs: General, Infraestructura y Soporte)..."
                    )
                else:
                    sheets.set_periodo_reporte(fecha_inicio, fecha_fin, area=area_sel)
                    decir(
                        f"📊 Reporte actualizado para el periodo {fecha_inicio.isoformat()} al {fecha_fin.isoformat()} (Área: {area_sel}).\n\n"
                        "Ya puedes descargarlo desde Google Sheets en la hoja 'Reporte PDF' (Archivo > Descargar > Documento PDF)."
                    )
                return respuestas
            except ValueError:
                pass
            except Exception as e:
                print(f"[bot_logic] error: {e}")
                decir(f"Error al actualizar Google Sheets: {e}")
                estado.esperando = None
                return respuestas

        decir("Formato incorrecto. Usa: AAAA-MM-DD AAAA-MM-DD\n(Ejemplo: '2026-08-01 2026-08-15') o escribe 'cancelar'.")
        return respuestas

    if estado.esperando == "problema_y_ubicacion":
        fecha_extraida = parsear_fecha(texto_limpio)
        if fecha_extraida:
            estado.borrador["fecha_inicio"] = fecha_extraida

        m_ticket = re.search(r"(?:ticket|folio|#)\s*#?([A-Za-z0-9-]+)", texto_limpio, re.IGNORECASE)
        ticket_extraido = m_ticket.group(1) if m_ticket else None

        partes = re.split(r"\s+en\s+|\s*:\s*", texto_limpio, maxsplit=1, flags=re.IGNORECASE)
        if len(partes) == 2 and partes[0].strip() and partes[1].strip():
            problema_val = partes[0].strip()
            ubicacion_val = partes[1].strip()
        else:
            problema_val = texto_limpio
            ubicacion_val = "Planta / Campo"

        estado.borrador["problema"] = problema_val
        estado.borrador["ubicacion"] = ubicacion_val
        if ticket_extraido:
            estado.borrador["ticket"] = ticket_extraido

        estado.esperando = "tipo_falla"
        decir(_prompt_tipo_falla())
        return respuestas

    if estado.esperando == "tipo_falla":
        valor = _match_catalogo(texto_limpio, CATALOGO_TIPO_FALLA)
        if not valor:
            decir("No reconozco esa opción.\n" + _prompt_tipo_falla())
            return respuestas

        if valor in ("Falla de red", "Revision de Leaky Feeder", "Hardware / Equipo dañado"):
            area_val = "Infraestructura"
        else:
            area_val = "Soporte"

        hora_ini = _ahora().strftime("%H:%M:%S")
        fecha_ini = estado.borrador.get("fecha_inicio")
        try:
            folio = sheets.start_activity(
                tecnico=tecnico,
                ticket=estado.borrador.get("ticket"),
                area=area_val,
                ubicacion=estado.borrador.get("ubicacion", "Planta / Campo"),
                problema=estado.borrador.get("problema", ""),
                tipo_falla=valor,
                prioridad=DEFAULT_PRIORIDAD,
                hora_inicio=hora_ini,
                fecha_inicio=fecha_ini,
            )
            estado.folio_activo = folio
            estado.esperando = None
            estado.borrador = {"hora_inicio": hora_ini, "fecha_inicio": fecha_ini}
            msg_fecha = f" [Fecha: {fecha_ini}]" if fecha_ini else ""
            decir(f"✅ Actividad iniciada{msg_fecha} (Hora Inicio: {hora_ini[:5]}). Folio: {folio}.\nEscribe 'finalizar' cuando concluyas el trabajo.")
        except Exception as e:
            print(f"[bot_logic] error iniciando actividad en sheets: {e}")
            decir(f"Hubo un error registrando la actividad en Google Sheets: {e}")
        return respuestas

    if estado.esperando == "solucion_y_evidencia":
        respuesta_norm = _remover_acentos(texto_limpio)

        if respuesta_norm in ("listo", "no", "omitir", "ninguna", "ya", "listo.", "sin fotos"):
            if "solucion" not in estado.borrador:
                decir("Por favor escribe brevemente cuál fue la solución aplicada para cerrar la actividad.")
                return respuestas
        else:
            estado.borrador["solucion"] = texto_limpio

        hora_fin_calc = _ahora().strftime("%H:%M:%S")
        try:
            sheets.finish_activity(
                estado.folio_activo,
                solucion=estado.borrador.get("solucion", "Trabajo concluido correctamente"),
                recomendaciones=DEFAULT_RECOMENDACIONES,
                receptor=DEFAULT_RECEPTOR,
                materiales=DEFAULT_MATERIALES,
                hora_fin=hora_fin_calc,
            )
            decir(f"✅ Actividad {estado.folio_activo} finalizada correctamente. ¡Buen trabajo!")
            estado.folio_activo = None
            estado.esperando = None
            estado.borrador = {}
        except Exception as e:
            print(f"[bot_logic] error finalizando actividad en sheets: {e}")
            decir(f"Hubo un error guardando el cierre de la actividad en Google Sheets: {e}")
        return respuestas

    # Compatibilidad con cualquier estado previo
    if estado.esperando in ("ticket_si_no", "numero_ticket", "area", "prioridad", "problema", "ubicacion", "hora_inicio"):
        estado.esperando = "problema_y_ubicacion"
        decir("Hemos simplificado el reporte. ¿Qué problema vas a atender y en qué ubicación?\n(Ej. 'Switch en Oficina Central')")
        return respuestas

    if estado.esperando in ("evidencias", "solucion", "duracion", "recomendaciones", "materiales", "receptor"):
        estado.esperando = "solucion_y_evidencia"
        decir("¿Cuál fue la solución aplicada? (Manda tus fotos si tienes o escribe 'listo')")
        return respuestas

    if estado.esperando == "confirmacion":
        _procesar_confirmacion(estado, texto_limpio, decir, es_admin=es_admin)
        return respuestas

    # Chequeo si el usuario escribió un comando de nuevo técnico con argumento directo:
    # ej. "/nuevo_tecnico Juan Perez" o "nuevo tecnico Juan Perez"
    if texto_limpio.startswith("/nuevo_tecnico ") or _remover_acentos(texto_limpio).startswith("nuevo tecnico ") or _remover_acentos(texto_limpio).startswith("agregar tecnico "):
        if not es_admin:
            decir("No tienes permiso de administrador para agregar técnicos.")
            return respuestas
        nombre_extraido = re.sub(r"^(/nuevo_tecnico|nuevo\s+t[eé]cnico|agregar\s+t[eé]cnico)\s+", "", texto_limpio, flags=re.IGNORECASE).strip()
        if nombre_extraido:
            try:
                codigo = sheets.agregar_tecnico(nombre_extraido)
                if not codigo:
                    decir(f"{nombre_extraido} ya estaba registrado en la lista de técnicos.")
                else:
                    decir(
                        f"✅ Técnico agregado: {nombre_extraido}.\n\n"
                        f"Mándale este código para que active su cuenta (funciona una sola vez):\n"
                        f"/start {codigo}"
                    )
            except Exception as e:
                decir(f"Error al registrar técnico: {e}")
            return respuestas

    # Reconocimiento rápido de comandos directos sin invocar OpenAI
    texto_norm_cmd = _remover_acentos(texto_limpio)
    if texto_norm_cmd in _COMANDOS_DIRECTOS:
        _ejecutar_intencion(estado, _COMANDOS_DIRECTOS[texto_norm_cmd], decir, es_admin=es_admin)
        return respuestas

    # Si no es comando directo, interpretar con NLU (OpenAI)
    interpretacion = interpretar_mensaje(texto_limpio)

    if interpretacion["confianza"] == "baja":
        if interpretacion["intencion"] != "desconocido":
            estado.esperando = "confirmacion"
            estado.borrador["intencion_propuesta"] = interpretacion["intencion"]
            decir(f"No estoy seguro de haber entendido. ¿Quisiste decir '{interpretacion['intencion'].replace('_', ' ')}'? Responde sí o no.")
        else:
            opciones_texto = "nueva actividad, pausar, reanudar, finalizar o mis actividades"
            if es_admin:
                opciones_texto += ", nuevo técnico o reporte PDF"
            decir(f"No entendí tu mensaje. Puedes elegir: {opciones_texto}.")
        return respuestas

    ticket_solicitado = interpretacion.get("ticket")
    _ejecutar_intencion(estado, interpretacion["intencion"], decir, ticket=ticket_solicitado, es_admin=es_admin)
    return respuestas


def _ejecutar_intencion(estado, intencion: str, decir, ticket: str | None = None, es_admin: bool = False):
    if intencion == "nueva_actividad":
        if estado.folio_activo:
            decir(f"Ya tienes la actividad {estado.folio_activo} activa. Escribe 'pausar' o 'finalizar' antes de iniciar otra.")
            return
        estado.esperando = "problema_y_ubicacion"
        decir("¿Qué problema o actividad vas a atender y en qué ubicación?\n(Ejemplo: 'Falla de red en Oficina Central'. Si es de fecha pasada, incluye 'ayer', 'antier' o la fecha ej. '25/08'):")

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
        estado.esperando = "solucion_y_evidencia"
        decir("¿Cuál fue la solución aplicada? (Puedes enviar fotos de evidencia o escribir 'listo' si ya las enviaste/no hay fotos).")


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

    elif intencion == "admin_nuevo_tecnico":
        if not es_admin:
            decir("No tienes permisos de administrador para dar de alta técnicos.")
            return
        estado.esperando = "admin_nombre_tecnico"
        decir("👤 Escribe el Nombre Completo del nuevo técnico que deseas registrar:")

    elif intencion == "admin_reporte":
        if not es_admin:
            decir("No tienes permisos de administrador para generar el reporte contractual.")
            return
        estado.esperando = "admin_tipo_reporte"
        decir("📄 ¿Qué tipo de reporte deseas generar?\nElige una opción:")

    elif intencion == "ayuda":
        lineas = [
            "🤖 *Comandos disponibles:*",
            "- *+ Nueva actividad*: Inicia el registro de un ticket/folio.",
            "- *⏸ Pausar*: Pausa la actividad activa actual.",
            "- *▶ Reanudar*: Reanuda una actividad pausada.",
            "- *✓ Finalizar*: Cierra la actividad (fotos, duración, solución, materiales, etc.).",
            "- *☰ Mis actividades*: Consulta tus actividades en curso.",
            "- *Cancelar*: Cancela cualquier registro en proceso.",
        ]
        if es_admin:
            lineas.extend([
                "",
                "👑 *Opciones de Administrador:*",
                "- *👤 + Nuevo técnico*: Da de alta a un técnico y genera su código de acceso.",
                "- *📄 Reporte PDF*: Actualiza las fechas del reporte contractual en Google Sheets.",
            ])
        decir("\n".join(lineas))

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


def _procesar_confirmacion(estado, texto: str, decir, es_admin: bool = False):
    respuesta = _remover_acentos(texto)
    estado.esperando = None
    if respuesta in ("si", "s", "yes", "y", "afirmativo", "claro"):
        intencion = estado.borrador.pop("intencion_propuesta", None)
        if intencion:
            _ejecutar_intencion(estado, intencion, decir, es_admin=es_admin)
        else:
            decir("Dime qué necesitas hacer.")
    else:
        estado.borrador = {}
        decir("Ok, cancelado. Dime de nuevo qué necesitas hacer.")
