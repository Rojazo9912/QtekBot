"""
Escritura a Google Sheets — reemplaza al Excel manual.

Requiere:
- Una cuenta de servicio de Google Cloud con la API de Sheets habilitada.
- El Google Sheet compartido como Editor con el email de esa cuenta de servicio.
- Las credenciales de esa cuenta de servicio, en UNA de estas dos formas:
    a) GOOGLE_CREDENTIALS_JSON: el contenido completo del archivo JSON, pegado tal
       cual como valor de una variable de entorno. Úsalo en Railway — así el JSON
       nunca toca el repo de GitHub.
    b) GOOGLE_CREDENTIALS_PATH: ruta a un archivo credentials.json en disco. Útil
       solo para correr el bot en tu máquina durante desarrollo local.

El libro tiene 3 hojas, calcadas del formato de reporte que ya usa Qtek con
First Majestic (ver Reporte_Diario_Tickets_2.xlsx):

1. "Reporte Diario" (fila 1 = encabezados) — una fila por actividad:
   Ticket | Fecha | Hora de Apertura | Hora de Finalizado | Duración |
   Técnico | Estatus | Prioridad | Tipo de Falla | Observaciones de Falla |
   Soluciones | Recomendaciones | Evidencias | Área/Ubicación |
   Orden Semana (no editar)
   ...seguido de columnas de uso interno del bot (no forman parte del
   reporte visible al cliente, por eso van después de "Orden Semana"):
   Foto 1 | Foto 2 | Foto 3 | Hora Pausa | Hora Reanudación | Receptor |
   Materiales

2. "Resumen Semanal" — tabla compacta (No. Ticket, Actividad, Ubicación/Área,
   Personal Asignado, Fecha de Ejecución, Estatus) que generar_reporte_semanal()
   reconstruye a partir de "Reporte Diario" para un rango de fechas.

3. "Reporte Semanal" — el documento formal que se entrega al cliente.
   generar_reporte_semanal() llena lo que se puede derivar de los datos del
   bot (info del contrato, tabla de actividades, personal asignado,
   materiales usados). Las secciones que requieren criterio humano —KPIs de
   cumplimiento contra metas, checklist de seguridad (EHS), variaciones e
   incidencias, firmas— se dejan en blanco a propósito: inventar esos datos
   sería falsear un reporte contractual. Un admin de Qtek debe revisarlas y
   llenarlas antes de enviar el reporte al cliente.

Estatus usa el mismo vocabulario que el reporte del cliente: "Pendiente"
(actividad abierta o pausada) y "Resuelto" (finalizada). La distinción
interna pausada/activa para el flujo del bot se deriva comparando las
columnas "Hora Pausa" y "Hora Reanudación" (ver list_open_activities), sin
inventar un estatus que el cliente no reconocería en su reporte.
"""
import os
import json
import datetime as dt
from typing import Optional
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

from app.config import CONTRATO_INFO, TECNICOS_INFO

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
CREDENTIALS_PATH = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
WORKSHEET_NAME = os.environ.get("GOOGLE_WORKSHEET_NAME", "Reporte Diario")
# Nombre que tenía la pestaña antes de este cambio de schema. Si WORKSHEET_NAME
# no se encuentra, se busca aquí como respaldo para no perder datos de hojas
# creadas con versiones anteriores del bot.
NOMBRE_LEGADO = "Actividades"
RESUMEN_WORKSHEET_NAME = "Resumen Semanal"
REPORTE_SEMANAL_WORKSHEET_NAME = "Reporte Semanal"

# El servidor (Railway) corre en UTC. Sin esto, las horas guardadas quedan
# desfasadas respecto a la hora real del técnico en campo (ej. 17:46 en vez
# de 11:46). Cambia ZONA_HORARIA en Railway si tus técnicos no están en
# horario de Ciudad de México/Durango (ambos son la misma zona: America/Mexico_City).
ZONA_HORARIA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Mexico_City"))


def _ahora() -> dt.datetime:
    return dt.datetime.now(ZONA_HORARIA)


def _load_credentials() -> Credentials:
    if CREDENTIALS_JSON:
        try:
            info = json.loads(CREDENTIALS_JSON)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                "GOOGLE_CREDENTIALS_JSON no es un JSON válido. Asegúrate de haber "
                "pegado el contenido completo del archivo, sin recortar ni escapar nada."
            ) from e
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    if os.path.exists(CREDENTIALS_PATH):
        return Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    raise RuntimeError(
        "No hay credenciales de Google configuradas. Define GOOGLE_CREDENTIALS_JSON "
        "(recomendado en Railway) o GOOGLE_CREDENTIALS_PATH (solo desarrollo local)."
    )


HEADERS = [
    "Ticket", "Fecha", "Hora de Apertura", "Hora de Finalizado", "Duración",
    "Técnico", "Estatus", "Prioridad", "Tipo de Falla", "Observaciones de Falla",
    "Soluciones", "Recomendaciones", "Evidencias", "Área/Ubicación",
    "Orden Semana (no editar)",
    "Foto 1", "Foto 2", "Foto 3",
    "Hora Pausa", "Hora Reanudación", "Receptor", "Materiales",
]

COL_TICKET = 1
COL_FECHA = 2
COL_HORA_APERTURA = 3
COL_HORA_FINALIZADO = 4
COL_DURACION = 5
COL_TECNICO = 6
COL_ESTATUS = 7
COL_PRIORIDAD = 8
COL_TIPO_FALLA = 9
COL_OBSERVACIONES = 10
COL_SOLUCIONES = 11
COL_RECOMENDACIONES = 12
COL_EVIDENCIAS = 13
COL_AREA = 14
COL_ORDEN_SEMANA = 15
COL_FOTOS = [16, 17, 18]  # columnas con miniatura =IMAGE(), una por evidencia (máx. 3)
COL_HORA_PAUSA = 19
COL_HORA_REANUDACION = 20
COL_RECEPTOR = 21
COL_MATERIALES = 22

TAMANO_FOTO_PX = 260  # alto y ancho de la miniatura =IMAGE() en las columnas Foto N

ESTATUS_PENDIENTE = "Pendiente"
ESTATUS_RESUELTO = "Resuelto"

# --- Migración desde el schema anterior (previo a "Reporte Diario") -------
HEADERS_LEGADO = [
    "Folio", "Ticket", "Técnico", "Fecha", "Hora Apertura", "Hora Pausa",
    "Hora Reanudación", "Hora Finalizado", "Estado", "Área", "Problema",
    "Solución", "Receptor", "Evidencias", "Foto 1", "Foto 2", "Foto 3",
]
_MAPA_ESTATUS_LEGADO = {
    "En proceso": ESTATUS_PENDIENTE,
    "Pausada": ESTATUS_PENDIENTE,
    "Finalizada": ESTATUS_RESUELTO,
}

_client = None
_worksheet = None


def _get_worksheet():
    global _client, _worksheet
    if _worksheet is not None:
        return _worksheet
    creds = _load_credentials()
    _client = gspread.authorize(creds)
    sh = _client.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        try:
            ws = sh.worksheet(NOMBRE_LEGADO)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=len(HEADERS))
            ws.append_row(HEADERS)
            _worksheet = ws
            return ws

    fue_legado = ws.row_values(1)[:1] == ["Folio"]
    _migrar_schema_legado(ws)
    if fue_legado and ws.title != WORKSHEET_NAME:
        ws.update_title(WORKSHEET_NAME)
    _worksheet = ws
    return ws


def _migrar_schema_legado(ws) -> None:
    """Convierte una hoja creada con el schema anterior (columna 'Folio' en
    primer lugar, 'Estado' con valores En proceso/Pausada/Finalizada) al
    schema actual tipo "Reporte Diario". Reescribe las filas existentes; no
    se pierde ningún dato, pero los campos nuevos (Prioridad, Tipo de Falla,
    Recomendaciones, Materiales) quedan vacíos para las filas viejas porque
    esa información nunca se le pidió al técnico en su momento.

    Solo corre para hojas de un piloto pequeño (decenas de filas) — para un
    volumen grande convendría hacer esto en lotes en vez de update_cell por
    fila.
    """
    encabezados = ws.row_values(1)
    if encabezados[:1] != ["Folio"]:
        return  # ya está en el schema nuevo, o la hoja está vacía

    filas_legado = ws.get_all_records()
    if ws.col_count < len(HEADERS):
        ws.add_cols(len(HEADERS) - ws.col_count)

    filas_nuevas = []
    for f in filas_legado:
        filas_nuevas.append([
            f.get("Folio", ""),
            f.get("Fecha", ""),
            f.get("Hora Apertura", ""),
            f.get("Hora Finalizado", ""),
            "",  # Duración: se vuelve a calcular con fórmula abajo
            f.get("Técnico", ""),
            _MAPA_ESTATUS_LEGADO.get(f.get("Estado", ""), f.get("Estado", "")),
            "",  # Prioridad (dato nuevo, sin captura previa)
            "",  # Tipo de Falla (dato nuevo)
            f.get("Problema", ""),
            f.get("Solución", ""),
            "",  # Recomendaciones (dato nuevo)
            f.get("Evidencias", ""),
            f.get("Área", ""),
            "",  # Orden Semana: se vuelve a calcular abajo
            f.get("Foto 1", ""), f.get("Foto 2", ""), f.get("Foto 3", ""),
            f.get("Hora Pausa", ""), f.get("Hora Reanudación", ""),
            f.get("Receptor", ""),
            "",  # Materiales (dato nuevo)
        ])

    ws.update([HEADERS] + filas_nuevas, "A1")  # raw=True: igual que append_row, fechas quedan como texto ISO

    por_semana: dict[tuple, int] = {}
    for i, fila in enumerate(filas_nuevas, start=2):
        if fila[COL_HORA_FINALIZADO - 1]:
            ws.update_cell(i, COL_DURACION, _formula_duracion(i))
        try:
            fecha = dt.datetime.strptime(fila[COL_FECHA - 1], "%Y-%m-%d").date()
        except ValueError:
            continue
        clave = fecha.isocalendar()[:2]
        por_semana[clave] = por_semana.get(clave, 0) + 1
        ws.update_cell(i, COL_ORDEN_SEMANA, por_semana[clave])


def _formula_duracion(row: int) -> str:
    col_apertura = rowcol_to_a1(row, COL_HORA_APERTURA).rstrip("0123456789")
    col_fin = rowcol_to_a1(row, COL_HORA_FINALIZADO).rstrip("0123456789")
    return f'=IF({col_fin}{row}="","",TEXT({col_fin}{row}-{col_apertura}{row},"[h]:mm"))'


def _next_folio() -> str:
    """Folio/ticket interno correlativo: FOLIO-0001, FOLIO-0002, ... (se usa
    cuando la actividad no trae un número de ticket real)."""
    ws = _get_worksheet()
    col = ws.col_values(COL_TICKET)
    count = max(0, len(col) - 1)  # menos encabezado
    return f"FOLIO-{count + 1:04d}"


def _orden_semana(fecha: dt.date) -> int:
    """Posición de la actividad dentro de su semana ISO (para la columna
    'Orden Semana (no editar)', igual que en la plantilla del cliente)."""
    ws = _get_worksheet()
    fechas = ws.col_values(COL_FECHA)[1:]  # sin encabezado
    year, week, _ = fecha.isocalendar()
    count = 0
    for f in fechas:
        try:
            d = dt.datetime.strptime(f, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d.isocalendar()[:2] == (year, week):
            count += 1
    return count + 1


def _find_row_by_folio(folio: str) -> Optional[int]:
    ws = _get_worksheet()
    cell = ws.find(folio, in_column=COL_TICKET)
    return cell.row if cell else None


def start_activity(
    tecnico: str, ticket: Optional[str], area: str, problema: str,
    tipo_falla: str, prioridad: str,
) -> str:
    """Crea una fila nueva. Devuelve el folio (o el ticket si existía)."""
    ws = _get_worksheet()
    folio = ticket if ticket else _next_folio()
    now = _ahora()
    orden = _orden_semana(now.date())
    row = [
        folio, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), "", "",
        tecnico, ESTATUS_PENDIENTE, prioridad, tipo_falla, problema,
        "", "", "", area, orden,
        "", "", "",
        "", "", "", "",
    ]
    ws.append_row(row)
    row_idx = _find_row_by_folio(folio)
    if row_idx:
        ws.update_cell(row_idx, COL_DURACION, _formula_duracion(row_idx))
    return folio


def pause_activity(folio: str) -> bool:
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return False
    ws = _get_worksheet()
    now = _ahora().strftime("%H:%M:%S")
    ws.update_cell(row_idx, COL_HORA_PAUSA, now)
    return True


def resume_activity(folio: str) -> bool:
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return False
    ws = _get_worksheet()
    now = _ahora().strftime("%H:%M:%S")
    ws.update_cell(row_idx, COL_HORA_REANUDACION, now)
    return True


def finish_activity(
    folio: str, solucion: str, recomendaciones: str, receptor: str,
    materiales: str = "",
) -> bool:
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return False
    ws = _get_worksheet()
    now = _ahora().strftime("%H:%M:%S")
    ws.update_cell(row_idx, COL_HORA_FINALIZADO, now)
    ws.update_cell(row_idx, COL_ESTATUS, ESTATUS_RESUELTO)
    ws.update_cell(row_idx, COL_SOLUCIONES, solucion)
    ws.update_cell(row_idx, COL_RECOMENDACIONES, recomendaciones)
    ws.update_cell(row_idx, COL_RECEPTOR, receptor)
    if materiales:
        ws.update_cell(row_idx, COL_MATERIALES, materiales)
    return True


def add_evidence(
    folio: str, link: str, mime_type: str = "image/jpeg",
    link_miniatura: Optional[str] = None,
) -> bool:
    """Anexa un link de evidencia a la fila del folio (columna Evidencias, texto
    completo como respaldo — siempre `link`, la URL directa de Supabase, para
    que el registro sobreviva aunque cambie cómo servimos las miniaturas).

    Si además es una imagen y hay un hueco libre entre las columnas Foto 1-3,
    escribe ahí una miniatura con =IMAGE(). Para esa fórmula usa
    `link_miniatura` si se lo pasan (pensado para una URL propia, sin el
    header X-Robots-Tag que trae Supabase Storage y que hace que =IMAGE() no
    renderice) y si no, cae en `link`. A partir de la 4a foto (o si no es
    imagen), solo queda el link en texto."""
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return False
    ws = _get_worksheet()

    actual = ws.cell(row_idx, COL_EVIDENCIAS).value or ""
    nuevo = f"{actual}\n{link}".strip() if actual else link
    ws.update_cell(row_idx, COL_EVIDENCIAS, nuevo)

    if mime_type.startswith("image/"):
        url_formula = link_miniatura or link
        for col in COL_FOTOS:
            if not ws.cell(row_idx, col).value:
                ws.update_cell(row_idx, col, f'=IMAGE("{url_formula}", 4, {TAMANO_FOTO_PX}, {TAMANO_FOTO_PX})')
                _ajustar_dimensiones_foto(ws, row_idx)
                break

    return True


def _ajustar_dimensiones_foto(ws, row_idx: int) -> None:
    """=IMAGE(url, 4, alto, ancho) dibuja la miniatura a tamaño fijo, pero
    Sheets NO ensancha solo la columna/fila — si la celda está en su tamaño
    default (angosto y bajo), la miniatura se ve recortada/diminuta aunque
    la fórmula pida 260x260. Forzamos aquí el ancho de las columnas Foto 1-3
    y el alto de la fila con la foto nueva para que se vea completa."""
    tamano = TAMANO_FOTO_PX + 20
    sheet_id = ws.id
    requests = [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": min(COL_FOTOS) - 1,
                    "endIndex": max(COL_FOTOS),
                },
                "properties": {"pixelSize": tamano},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": row_idx - 1,
                    "endIndex": row_idx,
                },
                "properties": {"pixelSize": tamano},
                "fields": "pixelSize",
            }
        },
    ]
    ws.spreadsheet.batch_update({"requests": requests})

    return True


def list_open_activities(tecnico: str) -> list[dict]:
    """Actividades 'Pendiente' (abiertas o pausadas) del técnico. Cada
    registro trae además "_en_pausa": bool, calculado comparando Hora Pausa
    vs Hora Reanudación — el Estatus del Sheet solo distingue
    Pendiente/Resuelto (vocabulario del reporte al cliente), así que la
    distinción pausada/activa para el flujo del bot vive aquí, no en el
    Sheet."""
    ws = _get_worksheet()
    records = ws.get_all_records()
    abiertas = []
    for r in records:
        if r.get("Técnico") != tecnico or r.get("Estatus") != ESTATUS_PENDIENTE:
            continue
        pausa = str(r.get("Hora Pausa") or "")
        reanudacion = str(r.get("Hora Reanudación") or "")
        r["_en_pausa"] = bool(pausa) and (not reanudacion or reanudacion < pausa)
        abiertas.append(r)
    return abiertas


# --- Reporte Semanal --------------------------------------------------

def _get_or_create_worksheet(sh, title: str, rows: int, cols: int):
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=rows, cols=cols)


def _actividades_de_la_semana(fecha_inicio: dt.date, fecha_fin: dt.date) -> list[dict]:
    ws = _get_worksheet()
    records = ws.get_all_records()
    resultado = []
    for r in records:
        try:
            fecha = dt.datetime.strptime(str(r.get("Fecha", "")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if fecha_inicio <= fecha <= fecha_fin:
            resultado.append(r)
    return resultado


def generar_reporte_semanal(fecha_inicio: dt.date, fecha_fin: dt.date) -> dict:
    """Reconstruye 'Resumen Semanal' y 'Reporte Semanal' para el rango dado,
    a partir de lo que ya está en 'Reporte Diario'.

    Llena automáticamente lo que SÍ se puede derivar de los datos del bot:
    tabla de actividades, personal asignado (con días trabajados calculados;
    cargo/IMSS vienen de app/config.TECNICOS_INFO), materiales usados y un
    avance físico calculado como % de tickets resueltos.

    A propósito deja en blanco (para que un admin de Qtek los revise y
    llene a mano antes de mandar el reporte al cliente): KPIs de
    cumplimiento contra metas contractuales, checklist de seguridad (EHS),
    variaciones/incidencias y firmas — no hay ninguna fuente de datos en el
    bot para esos campos, y llenarlos con valores inventados falsearía un
    reporte contractual.

    Devuelve un resumen de lo que se generó, para mostrarlo en la respuesta
    del endpoint que dispara esta función.
    """
    ws_diario = _get_worksheet()  # asegura que exista y esté migrado
    sh = ws_diario.spreadsheet

    actividades = _actividades_de_la_semana(fecha_inicio, fecha_fin)

    _llenar_resumen_semanal(sh, fecha_inicio, fecha_fin, actividades)
    _llenar_reporte_semanal(sh, fecha_inicio, fecha_fin, actividades)

    return {
        "periodo": f"{fecha_inicio.isoformat()} a {fecha_fin.isoformat()}",
        "actividades": len(actividades),
        "resueltas": sum(1 for a in actividades if a.get("Estatus") == ESTATUS_RESUELTO),
    }


def _llenar_resumen_semanal(sh, fecha_inicio: dt.date, fecha_fin: dt.date, actividades: list[dict]) -> None:
    ws = _get_or_create_worksheet(sh, RESUMEN_WORKSHEET_NAME, rows=200, cols=6)
    ws.clear()
    encabezado_tabla = ["No. Ticket", "Actividad", "Ubicación / Área", "Personal Asignado", "Fecha de Ejecución", "Estatus"]
    filas = [
        ["Resumen Semanal de Actividades (para Reporte de Avance Semanal)"],
        ["Fecha Inicio:", fecha_inicio.strftime("%Y-%m-%d"), "Fecha Fin:", fecha_fin.strftime("%Y-%m-%d")],
        [],
        encabezado_tabla,
    ]
    for a in actividades:
        filas.append([
            a.get("Ticket", ""),
            a.get("Tipo de Falla", ""),
            a.get("Área/Ubicación", ""),
            a.get("Técnico", ""),
            a.get("Fecha", ""),
            a.get("Estatus", ""),
        ])
    ws.update(filas, "A1")


def _llenar_reporte_semanal(sh, fecha_inicio: dt.date, fecha_fin: dt.date, actividades: list[dict]) -> None:
    ws = _get_or_create_worksheet(sh, REPORTE_SEMANAL_WORKSHEET_NAME, rows=130, cols=8)
    ws.clear()

    c = CONTRATO_INFO
    total = len(actividades)
    resueltas = sum(1 for a in actividades if a.get("Estatus") == ESTATUS_RESUELTO)
    avance_real = f"{round(100 * resueltas / total)}%" if total else "N/A"

    personal: dict[str, set] = {}
    for a in actividades:
        tecnico = a.get("Técnico", "")
        if not tecnico:
            continue
        personal.setdefault(tecnico, set()).add(a.get("Fecha", ""))

    materiales: list[tuple[str, str]] = []
    for a in actividades:
        for item in str(a.get("Materiales", "")).split(","):
            item = item.strip()
            if item:
                materiales.append((a.get("Ticket", ""), item))

    filas = [
        ["REPORTE DE AVANCE SEMANAL DE SERVICIOS — Área de TI"],
        [],
        ["1. INFORMACIÓN GENERAL"],
        ["Contrato Marco No:", None, c["contrato_marco_no"], None, "Orden de Compra No:", None, c["orden_compra_no"]],
        ["Contratista:", None, c["contratista"], None, "Fecha de Reporte:", None, _ahora().strftime("%Y-%m-%d")],
        ["Periodo del Reporte:", None, f"Del {fecha_inicio.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}"],
        ["Ubicación de los Servicios:", None, c["ubicacion_servicios"], None, "Responsable del Reporte (Qtek):", None, c["responsable_reporte_qtek"]],
        ["Representante First Majestic:", None, c["representante_first_majestic"]],
        [],
        ["2. RESUMEN DE EJECUCIÓN (Cláusula 4.1)"],
        ["Estatus del Sub-Plazo Actual"],
        ["Sub-Plazo Correspondiente:", None, c["sub_plazo_correspondiente"]],
        ["Descripción del Sub-Plazo:", None, c["descripcion_sub_plazo"]],
        [],
        ["Avance Físico"],
        ["Concepto", None, None, None, "Valor"],
        ["Porcentaje de Avance Real (calculado: resueltos / total tickets)", None, None, None, avance_real],
        ["Porcentaje de Avance Programado", None, None, None, "(pendiente de revisión manual)"],
        ["Desviación", None, None, None, "(pendiente de revisión manual)"],
        ["Justificación de Desviación (si aplica)", None, None, None, "(pendiente de revisión manual)"],
        [],
        ["Descripción de Actividades Realizadas (se llena automáticamente desde 'Resumen Semanal')"],
        ["No. Ticket", "Actividad", "Ubicación / Área", "Personal Asignado", "Fecha de Ejecución", "Estatus"],
    ]
    for a in actividades:
        filas.append([
            a.get("Ticket", ""), a.get("Tipo de Falla", ""), a.get("Área/Ubicación", ""),
            a.get("Técnico", ""), a.get("Fecha", ""), a.get("Estatus", ""),
        ])

    filas += [
        [],
        [". Cumplimiento de Niveles de Servicio (KPIs) — pendiente de revisión manual (sin metas contractuales definidas en el bot)"],
        ["Indicador", "Meta Contractual", "Valor Alcanzado", "Cumplimiento Sí/No", "Observaciones"],
        ["Disponibilidad del Servicio"],
        ["Tiempo de Respuesta"],
        ["Calidad del Servicio (satisfacción)"],
        ["Otros (especificar)"],
        [],
        ["3. DOCUMENTACIÓN DE SOPORTE (Cláusula 3.2 y 60)"],
        ["Personal Asignado en el Periodo"],
        ["Nombre", "Cargo / Especialidad", "No. IMSS / ID", "Días Trabajados", "Área de Servicio"],
    ]
    for tecnico, fechas in personal.items():
        info = TECNICOS_INFO.get(tecnico, {})
        filas.append([
            tecnico, info.get("cargo", "Pendiente de definir"),
            info.get("imss", "Pendiente de definir"), len(fechas), c["area_servicio"],
        ])

    filas += [
        [],
        ["Materiales y Equipos Utilizados"],
        ["No.", "Descripción", "Unidad", "Cantidad", "No. Serie/ID", "Observaciones"],
    ]
    for i, (ticket, item) in enumerate(materiales, start=1):
        filas.append([i, item, "pza", 1, "N/A", f"Usado en {ticket}"])
    if not materiales:
        filas.append(["Sin materiales reportados en el periodo."])

    filas += [
        [],
        ["Registros de Seguridad (EHS) — pendiente de revisión manual"],
        ["Ítem", None, None, "Sí / No / N/A", "Detalle / Referencia"],
        ["Inspección de seguridad preoperativa realizada"],
        ["Uso de EPP durante el periodo"],
        ["Capacitación de seguridad impartida"],
        ["Permisos de trabajo requeridos"],
        ["Reporte de condiciones inseguras"],
        ["Cumplimiento de políticas ambientales"],
        [],
        ["Observaciones de Seguridad"],
        ["(pendiente de revisión manual)"],
        [],
        ["4. GESTIÓN DE VARIACIONES E INCIDENCIAS (Cláusula 1.3 y 10) — pendiente de revisión manual"],
        ["Variaciones Instruidas / Incidentes Ambientales-Seguridad / Eventos de Fuerza Mayor"],
        ["(pendiente de revisión manual)"],
        [],
        ["5. OBSERVACIONES Y COMENTARIOS ADICIONALES"],
        ["(pendiente de revisión manual)"],
        [],
        ["6. FIRMAS DE APROBACIÓN"],
        ["Por el Contratista (Qtek Computación)", None, None, None, "Por First Majestic (Representante Autorizado)"],
        [f"Nombre: {c['director_general_qtek']}", None, None, None, f"Nombre: {c['representante_first_majestic']}"],
        ["Cargo: Director General", None, None, None, "Cargo: Representante First Majestic"],
        ["Firma: ______________________", None, None, None, "Firma: ______________________"],
        [f"Fecha: {_ahora().strftime('%d/%m/%Y')}", None, None, None, "Fecha: ______________________"],
    ]

    ws.update(filas, "A1")
