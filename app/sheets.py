"""
Escritura a Google Sheets — esquema "Registro de Tickets TI" (PRD de
Estandarización del Reporte de Tickets TI, San Dimas, contrato FMS-FM-C1665).

Requiere:
- Una cuenta de servicio de Google Cloud con la API de Sheets habilitada.
- El Google Sheet compartido como Editor con el email de esa cuenta de servicio.
- Las credenciales de esa cuenta de servicio, en UNA de estas dos formas:
    a) GOOGLE_CREDENTIALS_JSON: el contenido completo del archivo JSON, pegado tal
       cual como valor de una variable de entorno. Úsalo en Railway — así el JSON
       nunca toca el repo de GitHub.
    b) GOOGLE_CREDENTIALS_PATH: ruta a un archivo credentials.json en disco. Útil
       solo para correr el bot en tu máquina durante desarrollo local.

El libro tiene 4 hojas (se crean solas la primera vez que el bot escribe, si
no existen ya):

1. "Instrucciones" — reglas de llenado y catálogos permitidos. Solo lectura,
   el bot nunca escribe aquí después de crearla.

2. "Registro de Tickets" — fuente única de verdad. Fila 1 = título, fila 2 =
   encabezados, fila 3 = ejemplo ilustrativo (no es un ticket real, queda
   fuera del rango de las fórmulas de KPI/reporte que arrancan en fila 4),
   fila 4 en adelante = tickets reales que escribe el bot. Columnas A-U tal
   como las define el PRD; V-X son extensión propia de este bot para las
   miniaturas de evidencia (=IMAGE()), sin equivalente en el PRD.

   La columna H (Fecha Inicio) es la que usan TODOS los filtros de periodo
   del "Reporte PDF". La columna U (Rank Periodo) es un helper oculto que
   numera los tickets dentro del periodo activo para que la tabla de
   Actividades de "Reporte PDF" se autofiltre con INDEX/MATCH simple (sin
   fórmulas matriciales CSE) — no se edita a mano ni se expone al bot.

3. "Resumen KPI" — fórmulas COUNTA/COUNTIF de solo lectura sobre todo el
   histórico de "Registro de Tickets" (no depende de ningún periodo).

4. "Reporte PDF" — replica el formato de reporte contractual. Usa
   SUMPRODUCT en vez de COUNTIFS con criterios de fecha concatenados: se
   comprobó que COUNTIFS falla silenciosamente (da 0) si las fechas llegan
   como texto en vez de fecha nativa de Sheets, y SUMPRODUCT con
   comparación directa funciona igual con texto ISO (AAAA-MM-DD) o fecha
   real. El periodo del reporte (celdas C13/E13) es la única entrada manual
   que controla todos los cálculos de abajo.

Catálogos (Área, Prioridad, Estatus) los define app/config.py y se aplican
como validación de datos en la hoja — el bot nunca escribe texto libre del
usuario en esas columnas.

Estatus interno del bot: "En Proceso" al crear el ticket, "Cerrado" al
finalizarlo. Pausar/reanudar es un estado que vive solo en app/state.py — el
esquema del PRD no tiene columnas de Hora Pausa/Reanudación, así que pausar
no escribe nada en el Sheet (el ticket sigue "En Proceso").

Identidad de los técnicos en Telegram: la hoja "Técnicos" no solo lista
nombres — también guarda, por técnico, el chat_id de Telegram ya vinculado
(columna D) y, mientras no se haya activado, un código de un solo uso
(columna E). Un admin (ver ADMIN_TECNICOS en config.py) da de alta al
técnico con /nuevo_tecnico y le pasa ese código por fuera del bot (WhatsApp,
en persona); el técnico lo consume una sola vez con "/start CÓDIGO" y ese
chat_id queda ligado a su nombre para siempre — nadie más puede volver a
elegir ese nombre, ni siquiera si el bot se reinicia (a diferencia de
app/state.py, esto SÍ vive en el Sheet, no en memoria).
"""
import os
import json
import secrets
import string
import datetime as dt
from typing import Optional
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1, ValueRenderOption

from app.config import (
    CATALOGO_AREA, CATALOGO_ESTATUS, CATALOGO_PRIORIDAD,
    CONTRATO_INFO, TECNICOS, TECNICOS_INFO,
)

import httpx
import google.auth.transport.requests

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

def _get_sheet_id() -> str:
    return os.environ.get("GOOGLE_SHEET_ID", "").strip()

def _get_credentials_json() -> Optional[str]:
    return os.environ.get("GOOGLE_CREDENTIALS_JSON")

def _get_worksheet_name() -> str:
    val = os.environ.get("GOOGLE_WORKSHEET_NAME", "Registro de Tickets")
    return val.strip() if val else "Registro de Tickets"

INSTRUCCIONES_WORKSHEET_NAME = "Instrucciones"
RESUMEN_KPI_WORKSHEET_NAME = "Resumen KPI"
REPORTE_PDF_WORKSHEET_NAME = "Reporte PDF"
TECNICOS_WORKSHEET_NAME = "Técnicos"

# El servidor (Railway) corre en UTC. Sin esto, las horas guardadas quedan
# desfasadas respecto a la hora real del técnico en campo (ej. 17:46 en vez
# de 11:46). Cambia ZONA_HORARIA en Railway si tus técnicos no están en
# horario de Ciudad de México/Durango (ambos son la misma zona: America/Mexico_City).
ZONA_HORARIA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Mexico_City"))


def _ahora() -> dt.datetime:
    return dt.datetime.now(ZONA_HORARIA)


def _load_credentials() -> Credentials:
    creds_json = _get_credentials_json()
    creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    if creds_json:
        try:
            info = json.loads(creds_json)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                "GOOGLE_CREDENTIALS_JSON no es un JSON válido. Asegúrate de haber "
                "pegado el contenido completo del archivo, sin recortar ni escapar nada."
            ) from e
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    if os.path.exists(creds_path):
        return Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    raise RuntimeError(
        "No hay credenciales de Google configuradas. Define GOOGLE_CREDENTIALS_JSON "
        "(recomendado en Railway) o GOOGLE_CREDENTIALS_PATH (solo desarrollo local)."
    )


# --- Columnas de "Registro de Tickets" (A-U según el PRD, V-X extensión propia) ---
COL_NO = 1
COL_AREA = 2
COL_FOLIO = 3
COL_FECHA_RECEPCION = 4
COL_PRIORIDAD = 5
COL_UBICACION = 6
COL_TECNICO = 7
COL_FECHA_INICIO = 8
COL_HORA_INICIO = 9
COL_HORA_FIN = 10
COL_DURACION = 11
COL_TIPO_FALLA = 12
COL_DESCRIPCION_FALLA = 13
COL_SOLUCION = 14
COL_ENTREGADO_A = 15
COL_RECOMENDACIONES = 16
COL_EVIDENCIAS = 17
COL_ESTATUS = 18
COL_ULTIMA_FECHA_MISMA_FALLA = 19
COL_FRECUENCIA_FALLA = 20
COL_RANK_PERIODO = 21
COL_FOTOS = [22, 23, 24]  # Foto 1-3, miniatura =IMAGE(), extensión propia (no está en el PRD)

TAMANO_FOTO_PX = 260  # alto y ancho de la miniatura =IMAGE() en las columnas Foto N

ESTATUS_EN_PROCESO = "En Proceso"
ESTATUS_CERRADO = "Cerrado"

# Tope de filas con formato/fórmula/validación pre-aplicado en "Registro de
# Tickets" y usado como rango fijo en las fórmulas de "Resumen KPI" y
# "Reporte PDF". Muy por encima de las 200 filas del Excel original (ver
# riesgo "Se supera la fila 203" del PRD §7) porque aquí las fórmulas de
# cada fila se escriben dinámicamente al crear el ticket (igual que ya hacía
# este archivo con la columna Duración), no de una vez al preformatear todo
# el rango — así que no hay un límite real de filas, solo este techo para
# las fórmulas de agregación.
RANGO_MAX_FILA = 2000

TITULO_REGISTRO = (
    "Registro de Tickets TI — Infraestructura y Soporte "
    "(Unidad San Dimas, Contrato FMS-FM-C1665)"
)

HEADERS_REGISTRO = [
    "No.", "Área", "Folio", "Fecha Recepción", "Prioridad", "Ubicación",
    "Técnico", "Fecha Inicio", "Hora Inicio", "Hora Fin", "Duración",
    "Tipo de Falla", "Descripción de Falla", "Solución", "Entregado a",
    "Recomendaciones", "Evidencias", "Estatus", "Última fecha misma falla",
    "Frecuencia de falla", "Rank Periodo (no editar)",
    "Foto 1", "Foto 2", "Foto 3",
]

FILA_EJEMPLO = [
    "", "Infraestructura", "EJEMPLO-0001", "2000-01-01", "Media",
    "Oficina Central", "Técnico de Ejemplo", "2000-01-01", "09:00:00",
    "10:30:00", "", "Falla de red", "Switch principal sin enlace a internet",
    "Se reinició el switch y se revisó el cableado", "Juan Pérez",
    "Revisar cableado de red periódicamente", "", "Cerrado", "", "",
    "", "", "", "",
]

# Cupo de técnicos pre-formateado en las fórmulas de "Resumen KPI" (sección
# Por Técnico) y "Reporte PDF" (Personal Asignado): esas dos secciones se
# escriben UNA sola vez al crear cada hoja (para no pisar ediciones manuales
# de un admin en cada reinicio del bot), así que en vez de una fila por
# técnico conocido en ese momento, se dejan TECNICOS_CUPO filas con fórmulas
# INDEX que leen de la hoja "Técnicos" — cuando se agrega un técnico nuevo
# (vía /nuevo_tecnico) esas filas lo recogen solas, sin tocar el Sheet.
TECNICOS_CUPO = 30

TITULO_TECNICOS = "Técnicos — Registro de Tickets TI (Unidad San Dimas)"
HEADERS_TECNICOS = [
    "Nombre", "Cargo / Especialidad", "No. IMSS / ID",
    "Chat ID (Telegram)", "Código de Activación",
]
COL_TEC_NOMBRE = 1
COL_TEC_CARGO = 2
COL_TEC_IMSS = 3
COL_TEC_CHAT_ID = 4
COL_TEC_CODIGO = 5

_ALFABETO_CODIGO = string.ascii_uppercase + string.digits


def _generar_codigo_activacion() -> str:
    return "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(6))


_client = None
_worksheet = None
_tecnicos_ws = None


def _letra(col: int) -> str:
    return rowcol_to_a1(1, col).rstrip("0123456789")


def _valor(fila: list, col: int) -> str:
    """Valor de una columna (1-indexada) dentro de una fila obtenida con
    get_all_values(). Por posición, no por nombre de encabezado — a
    diferencia de get_all_records(), no truena si la fila 2 real del Sheet
    tiene encabezados repetidos o vacíos de más (ver aviso en
    list_open_activities). get_all_values() recorta cada fila hasta su
    última celda no vacía, así que puede venir más corta que COL_*; de ahí
    el chequeo de rango."""
    idx = col - 1
    return fila[idx] if idx < len(fila) else ""


def _rango_registro(col_letra: str) -> str:
    return f"'{_get_worksheet_name()}'!${col_letra}$4:${col_letra}${RANGO_MAX_FILA}"


def _formula_no(row: int) -> str:
    c = _letra(COL_FOLIO)
    return f'=IF({c}{row}="","",ROW()-2)'


def _formula_duracion(row: int) -> str:
    c_inicio = _letra(COL_HORA_INICIO)
    c_fin = _letra(COL_HORA_FIN)
    return f'=IF(OR({c_fin}{row}="",{c_inicio}{row}=""),"",IF({c_fin}{row}>={c_inicio}{row},{c_fin}{row}-{c_inicio}{row},1+{c_fin}{row}-{c_inicio}{row}))'


def _formula_rank_periodo(row: int) -> str:
    c_fecha = _letra(COL_FECHA_INICIO)
    c_area = _letra(COL_AREA)
    periodo_ini = f"'{REPORTE_PDF_WORKSHEET_NAME}'!$C$13"
    periodo_fin = f"'{REPORTE_PDF_WORKSHEET_NAME}'!$E$13"
    area_reporte = f"'{REPORTE_PDF_WORKSHEET_NAME}'!$G$13"
    rango_fecha = _rango_registro(c_fecha)
    rango_folio = _rango_registro(_letra(COL_FOLIO))
    rango_area = _rango_registro(c_area)

    cond_area_fila = f"OR({area_reporte}=\"Todos\",{area_reporte}=\"\",{c_area}{row}={area_reporte})"
    cond_area_rango = f"(({area_reporte}=\"Todos\")+({area_reporte}=\"\")+({rango_area}={area_reporte})>0)"

    return (
        f'=IF({_rango_registro(_letra(COL_FOLIO))}="","", '
        f'IF(AND({c_fecha}{row}<>"",{c_fecha}{row}>={periodo_ini},{c_fecha}{row}<={periodo_fin},{cond_area_fila}),'
        f'SUMPRODUCT(({rango_fecha}<>"")*({rango_fecha}>={periodo_ini})*({rango_fecha}<={periodo_fin})*({rango_folio}<>"")*{cond_area_rango}),'
        f'""))'
    )


def _validacion_lista(sheet_id: int, col: int, valores: list[str]) -> dict:
    return {
        "setDataValidation": {
            "range": {
                "sheetId": sheet_id, "startRowIndex": 2, "endRowIndex": RANGO_MAX_FILA,
                "startColumnIndex": col - 1, "endColumnIndex": col,
            },
            "rule": {
                "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in valores]},
                "strict": True,
                "showCustomUi": True,
            },
        }
    }


def _configurar_formato_registro(ws) -> None:
    sheet_id = ws.id
    requests = [
        _validacion_lista(sheet_id, COL_AREA, CATALOGO_AREA),
        _validacion_lista(sheet_id, COL_PRIORIDAD, CATALOGO_PRIORIDAD),
        _validacion_lista(sheet_id, COL_ESTATUS, CATALOGO_ESTATUS),
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id, "startRowIndex": 2, "endRowIndex": RANGO_MAX_FILA,
                    "startColumnIndex": COL_DURACION - 1, "endColumnIndex": COL_DURACION,
                },
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "TIME", "pattern": "[h]:mm"}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id, "dimension": "COLUMNS",
                    "startIndex": COL_RANK_PERIODO - 1, "endIndex": COL_RANK_PERIODO,
                },
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser",
            }
        },
    ]
    ws.spreadsheet.batch_update({"requests": requests})


def _ensure_registro_tickets(sh):
    ws_name = _get_worksheet_name()
    try:
        return sh.worksheet(ws_name)
    except gspread.WorksheetNotFound:
        pass
    ws = sh.add_worksheet(title=ws_name, rows=RANGO_MAX_FILA, cols=len(HEADERS_REGISTRO))
    ws.update([[TITULO_REGISTRO]], "A1")
    ws.update([HEADERS_REGISTRO], "A2", value_input_option="USER_ENTERED")
    ws.update([FILA_EJEMPLO], "A3", value_input_option="USER_ENTERED")
    ws.update_cell(3, COL_NO, _formula_no(3))
    ws.update_cell(3, COL_DURACION, _formula_duracion(3))
    _configurar_formato_registro(ws)
    return ws


def _ensure_tecnicos(sh):
    try:
        return sh.worksheet(TECNICOS_WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        pass
    ws = sh.add_worksheet(title=TECNICOS_WORKSHEET_NAME, rows=max(TECNICOS_CUPO + 5, 40), cols=len(HEADERS_TECNICOS))
    ws.update([[TITULO_TECNICOS]], "A1")
    ws.update([HEADERS_TECNICOS], "A2")
    # Cada técnico semilla (los de config.TECNICOS) arranca sin chat_id y con
    # un código de activación de un solo uso — igual que los que se agregan
    # después con /nuevo_tecnico. Como todavía no hay ningún chat vinculado
    # (nadie le ha escrito al bot aún), ese código hay que recuperarlo con
    # GET /api/codigo-activacion en vez de que el bot se lo mande por chat.
    filas_seed = [
        [
            t,
            TECNICOS_INFO.get(t, {}).get("cargo", "Pendiente de definir"),
            TECNICOS_INFO.get(t, {}).get("imss", "Pendiente de definir"),
            "",
            _generar_codigo_activacion(),
        ]
        for t in TECNICOS
    ]
    if filas_seed:
        ws.update(filas_seed, "A3", value_input_option="USER_ENTERED")
    _ocultar_columnas_activacion(ws)
    return ws


def _ocultar_columnas_activacion(ws) -> None:
    """Oculta Chat ID / Código de Activación: son datos de identidad, no
    algo que un técnico deba ver u ocupar a mano en el Sheet."""
    requests = [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id, "dimension": "COLUMNS",
                    "startIndex": COL_TEC_CHAT_ID - 1, "endIndex": COL_TEC_CODIGO,
                },
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser",
            }
        },
    ]
    ws.spreadsheet.batch_update({"requests": requests})


def _ensure_instrucciones(sh) -> None:
    try:
        sh.worksheet(INSTRUCCIONES_WORKSHEET_NAME)
        return
    except gspread.WorksheetNotFound:
        pass
    ws = sh.add_worksheet(title=INSTRUCCIONES_WORKSHEET_NAME, rows=30, cols=4)
    filas = [
        ["Instrucciones — Registro de Tickets TI (solo lectura)"],
        [],
        ["Esta hoja es de referencia. No se edita a mano; el bot de Telegram escribe directamente en 'Registro de Tickets'."],
        [],
        ["Catálogos permitidos (el bot solo puede escribir estos valores):"],
        ["Área:", ", ".join(CATALOGO_AREA)],
        ["Prioridad:", ", ".join(CATALOGO_PRIORIDAD)],
        ["Estatus:", ", ".join(CATALOGO_ESTATUS)],
        [],
        ["Columnas con fórmula — no editar manualmente:"],
        ["No. (A)", "Duración (K)", "Rank Periodo (U, columna oculta)"],
        [],
        ["'Fecha Inicio' (H) es la columna clave: todos los filtros de periodo de 'Reporte PDF' usan esta fecha."],
        ["La fila 3 de 'Registro de Tickets' es un ejemplo ilustrativo, no es un ticket real."],
        ["La hoja 'Técnicos' es la lista de técnicos autorizados a usar el bot. Se administra con /nuevo_tecnico (solo el admin del bot)."],
        ["El periodo de 'Reporte PDF' (celdas C13/E13) controla todos los cálculos de esa hoja."],
    ]
    ws.update(filas, "A1")


def _ensure_resumen_kpi(sh) -> None:
    try:
        sh.worksheet(RESUMEN_KPI_WORKSHEET_NAME)
        return
    except gspread.WorksheetNotFound:
        pass
    ws = sh.add_worksheet(title=RESUMEN_KPI_WORKSHEET_NAME, rows=40 + TECNICOS_CUPO, cols=4)

    c_folio = _letra(COL_FOLIO)
    c_estatus = _letra(COL_ESTATUS)
    c_area = _letra(COL_AREA)
    c_prioridad = _letra(COL_PRIORIDAD)
    c_tecnico = _letra(COL_TECNICO)
    rango_tec_nombre = f"'{TECNICOS_WORKSHEET_NAME}'!$A$3:$A${TECNICOS_CUPO + 2}"

    filas = [
        ["Resumen KPI — acumulado histórico (todas las fechas)"],
        [],
        ["Total de tickets", f"=COUNTA({_rango_registro(c_folio)})"],
        [],
        ["Por Estatus"],
        *[[estatus, f'=COUNTIF({_rango_registro(c_estatus)},"{estatus}")'] for estatus in CATALOGO_ESTATUS],
        [],
        ["Por Área"],
        *[[area, f'=COUNTIF({_rango_registro(c_area)},"{area}")'] for area in CATALOGO_AREA],
        [],
        ["Por Prioridad"],
        *[[p, f'=COUNTIF({_rango_registro(c_prioridad)},"{p}")'] for p in CATALOGO_PRIORIDAD],
        [],
        ["Por Técnico (se actualiza solo al agregar técnicos con /nuevo_tecnico)"],
    ]
    fila_inicio_tecnicos = len(filas) + 1
    n_expr_tecnicos = f"ROW()-{fila_inicio_tecnicos - 1}"
    for _ in range(TECNICOS_CUPO):
        r = len(filas) + 1
        filas.append([
            f'=IFERROR(INDEX({rango_tec_nombre}, {n_expr_tecnicos}), "")',
            f'=IF(A{r}="","",COUNTIF({_rango_registro(c_tecnico)},A{r}))',
        ])
    ws.update(filas, "A1", value_input_option="USER_ENTERED")


def _formatear_reporte_pdf(ws) -> None:
    sheet_id = ws.id
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id, "startRowIndex": 16, "endRowIndex": 19,
                    "startColumnIndex": 4, "endColumnIndex": 5,
                },
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id, "startRowIndex": 12, "endRowIndex": 13,
                    "startColumnIndex": 2, "endColumnIndex": 3,
                },
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id, "startRowIndex": 12, "endRowIndex": 13,
                    "startColumnIndex": 4, "endColumnIndex": 5,
                },
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        },
    ]
    ws.spreadsheet.batch_update({"requests": requests})


def _ensure_reporte_pdf(sh) -> None:
    try:
        sh.worksheet(REPORTE_PDF_WORKSHEET_NAME)
        return
    except gspread.WorksheetNotFound:
        pass

    c = CONTRATO_INFO
    c_folio = _letra(COL_FOLIO)
    c_area = _letra(COL_AREA)
    c_tipo_falla = _letra(COL_TIPO_FALLA)
    c_ubicacion = _letra(COL_UBICACION)
    c_tecnico = _letra(COL_TECNICO)
    c_fecha_inicio = _letra(COL_FECHA_INICIO)
    c_estatus = _letra(COL_ESTATUS)

    def _index(col_letra: str, n_expr: str) -> str:
        return f'=IFERROR(INDEX({_rango_registro(col_letra)}, MATCH({n_expr}, {_rango_registro(_letra(COL_RANK_PERIODO))}, 0)), "")'

    filas = [
        ['=IF(OR($G$13="Todos",$G$13=""), "REPORTE DE AVANCE DE SERVICIOS — Área de TI (Infraestructura y Soporte)", "REPORTE DE AVANCE DE SERVICIOS — Área de TI (" & $G$13 & ")")'],
        [],
        ["1. INFORMACIÓN GENERAL"],
        [],
        ["Contrato Marco No:", c["contrato_marco_no"], "Contratista:", c["contratista"]],
        ["Fecha de Reporte:", _ahora().strftime("%Y-%m-%d")],
        ["Ubicación de los Servicios:", c["ubicacion_servicios"]],
        ["Responsable del Reporte (Qtek):", c["responsable_reporte_qtek"]],
        ["Representante First Majestic:", c["representante_first_majestic"]],
        [],
        ["2. RESUMEN DE EJECUCIÓN (Cláusula 4.1)"],
        [],
        ["Periodo del Reporte:", "Del:", "", "Al:", "", "Área:", "Todos"],
        [],
        ["Avance Físico"],
        ["Concepto", "", "", "", "Valor"],
        [
            "% de Avance Real (calculado: Cerrados / total del periodo)", "", "", "",
            f'=IFERROR(SUMPRODUCT(({_rango_registro(c_fecha_inicio)}>=$C$13)*({_rango_registro(c_fecha_inicio)}<=$E$13)*({_rango_registro(c_estatus)}="Cerrado")*(($G$13="Todos")+($G$13="")+({_rango_registro(c_area)}=$G$13)>0))'
            f'/SUMPRODUCT(({_rango_registro(c_fecha_inicio)}>=$C$13)*({_rango_registro(c_fecha_inicio)}<=$E$13)*({_rango_registro(c_folio)}<>"")*(($G$13="Todos")+($G$13="")+({_rango_registro(c_area)}=$G$13)>0)),"N/A")',
        ],
        ["% de Avance Programado (manual)", "", "", "", ""],
        ["Desviación", "", "", "", '=IFERROR(E17-E18,"")'],
        ["Justificación de Desviación (si aplica)", "", "", "", ""],
        [],
        ["3. Descripción de Actividades Realizadas (automático, según 'Registro de Tickets')"],
        ["No. Ticket", "Área", "Actividad", "Ubicación", "Técnico", "Fecha Inicio", "Estatus"],
    ]

    fila_inicio_actividades = len(filas) + 1
    n_expr = f"ROW()-{fila_inicio_actividades - 1}"
    for _ in range(45):
        filas.append([
            _index(c_folio, n_expr), _index(c_area, n_expr), _index(c_tipo_falla, n_expr),
            _index(c_ubicacion, n_expr), _index(c_tecnico, n_expr), _index(c_fecha_inicio, n_expr),
            _index(c_estatus, n_expr),
        ])

    filas += [
        [],
        ["4. Cumplimiento de Niveles de Servicio (KPIs) — pendiente de revisión manual"],
        ["Indicador", "Meta Contractual", "Valor Alcanzado", "Cumplimiento Sí/No", "Observaciones"],
    ]
    for indicador in [
        "Disponibilidad del Servicio", "Tiempo de Respuesta",
        "Calidad del Servicio (satisfacción)", "Otros (especificar)",
    ]:
        r = len(filas) + 1
        filas.append([indicador, "", "", f'=IF(OR(B{r}="",C{r}=""),"",IFERROR(IF(C{r}>=B{r},"Sí","No"),""))', ""])

    filas += [
        [],
        ["5. Personal Asignado en el Periodo (se actualiza solo al agregar técnicos con /nuevo_tecnico)"],
        ["Nombre", "Cargo / Especialidad", "No. IMSS / ID", "Tickets Atendidos", "Área de Servicio"],
    ]
    rango_tec_nombre = f"'{TECNICOS_WORKSHEET_NAME}'!$A$3:$A${TECNICOS_CUPO + 2}"
    rango_tec_cargo = f"'{TECNICOS_WORKSHEET_NAME}'!$B$3:$B${TECNICOS_CUPO + 2}"
    rango_tec_imss = f"'{TECNICOS_WORKSHEET_NAME}'!$C$3:$C${TECNICOS_CUPO + 2}"
    fila_inicio_personal = len(filas) + 1
    n_expr_personal = f"ROW()-{fila_inicio_personal - 1}"
    for _ in range(TECNICOS_CUPO):
        r = len(filas) + 1
        filas.append([
            f'=IFERROR(INDEX({rango_tec_nombre}, {n_expr_personal}), "")',
            f'=IFERROR(INDEX({rango_tec_cargo}, {n_expr_personal}), "")',
            f'=IFERROR(INDEX({rango_tec_imss}, {n_expr_personal}), "")',
            f'=IF(A{r}="","",SUMPRODUCT(({_rango_registro(c_tecnico)}=A{r})*({_rango_registro(c_fecha_inicio)}>=$C$13)*({_rango_registro(c_fecha_inicio)}<=$E$13)*({_rango_registro(c_folio)}<>"")*(($G$13="Todos")+($G$13="")+({_rango_registro(c_area)}=$G$13)>0)))',
            f'=IF(A{r}="","",IFERROR(INDEX({_rango_registro(c_area)},MATCH(A{r},{_rango_registro(c_tecnico)},0)),""))',
        ])

    filas += [
        [],
        ["6. Observaciones y Comentarios Adicionales"],
        ["(pendiente de revisión manual)"],
        [],
        ["7. Firmas de Aprobación"],
        ["Por el Contratista (Qtek Computación)", "", "", "", "Por First Majestic (Representante Autorizado)"],
        [f"Nombre: {c['director_general_qtek']}", "", "", "", f"Nombre: {c['representante_first_majestic']}"],
        ["Cargo: Director General", "", "", "", "Cargo: Representante First Majestic"],
        ["Firma: ______________________", "", "", "", "Firma: ______________________"],
        ["Fecha: ______________________", "", "", "", "Fecha: ______________________"],
    ]

    ws = sh.add_worksheet(title=REPORTE_PDF_WORKSHEET_NAME, rows=len(filas) + 10, cols=8)
    ws.update(filas, "A1", value_input_option="USER_ENTERED")
    _formatear_reporte_pdf(ws)


def _get_worksheet():
    global _client, _worksheet, _tecnicos_ws
    if _worksheet is not None:
        return _worksheet
    sheet_id = _get_sheet_id()
    if not sheet_id:
        raise RuntimeError(
            "No se ha configurado GOOGLE_SHEET_ID en las variables de entorno."
        )
    creds = _load_credentials()
    _client = gspread.authorize(creds)
    sh = _client.open_by_key(sheet_id)
    ws = _ensure_registro_tickets(sh)
    _tecnicos_ws = _ensure_tecnicos(sh)
    _ensure_instrucciones(sh)
    _ensure_resumen_kpi(sh)
    _ensure_reporte_pdf(sh)
    _worksheet = ws
    return ws


def _get_tecnicos_ws():
    _get_worksheet()  # asegura que _tecnicos_ws esté poblado (mismo bootstrap)
    return _tecnicos_ws


def listar_tecnicos() -> list[str]:
    """Técnicos autorizados a usar el bot, leídos de la hoja 'Técnicos'
    (fuente de verdad en tiempo de ejecución — ver ADMIN_TECNICOS en
    config.py para quién puede agregar nuevos)."""
    ws = _get_tecnicos_ws()
    nombres = ws.col_values(1)[2:]  # fila1=título, fila2=encabezado
    return [n.strip() for n in nombres if n.strip()]


def agregar_tecnico(
    nombre: str, cargo: str = "Pendiente de definir", imss: str = "Pendiente de definir",
) -> Optional[str]:
    """Agrega un técnico nuevo a la hoja 'Técnicos' con un código de
    activación de un solo uso (columna E, sin chat_id todavía). Devuelve ese
    código —para que el admin se lo mande al técnico por fuera del bot— o
    None si el nombre ya existía (sin duplicar; comparación sin importar
    mayúsculas/minúsculas)."""
    nombre = nombre.strip()
    if not nombre:
        return None
    ws = _get_tecnicos_ws()
    existentes = {n.lower() for n in listar_tecnicos()}
    if nombre.lower() in existentes:
        return None
    codigo = _generar_codigo_activacion()
    ws.append_row([nombre, cargo, imss, "", codigo], value_input_option="USER_ENTERED")
    return codigo


def codigo_activacion_pendiente(nombre: str) -> Optional[str]:
    """Código de activación aún sin usar de un técnico, o None si no existe
    o ya se activó. Pensado para /api/codigo-activacion: el único caso en el
    que el admin necesita recuperar un código por HTTP en vez de que el bot
    se lo mande por chat es el/los técnico(s) semilla de config.TECNICOS —
    nadie les ha escrito al bot todavía, así que no hay a quién mandarle el
    código por Telegram."""
    ws = _get_tecnicos_ws()
    filas = ws.get_all_values()[2:]  # después de título (fila1) y encabezado (fila2)
    for fila in filas:
        if _valor(fila, COL_TEC_NOMBRE) == nombre:
            codigo = _valor(fila, COL_TEC_CODIGO).strip()
            return codigo or None
    return None


def activar_tecnico_por_codigo(codigo: str, chat_id: int) -> Optional[str]:
    """Vincula un chat de Telegram a un técnico consumiendo su código de
    activación de un solo uso (lo limpia al usarlo, para que no sirva dos
    veces). Devuelve el nombre del técnico si el código era válido, o None
    si no existe o ya se había usado."""
    codigo = codigo.strip().upper()
    if not codigo:
        return None
    ws = _get_tecnicos_ws()
    cell = ws.find(codigo, in_column=COL_TEC_CODIGO)
    if not cell:
        return None
    nombre = ws.cell(cell.row, COL_TEC_NOMBRE).value
    ws.update_cell(cell.row, COL_TEC_CHAT_ID, str(chat_id))
    ws.update_cell(cell.row, COL_TEC_CODIGO, "")
    return nombre


def tecnico_por_chat_id(chat_id: int) -> Optional[str]:
    """Técnico ya vinculado a este chat de Telegram (columna D de
    'Técnicos'), o None si ese chat todavía no se activó con un código. A
    diferencia de app/state.py, esto persiste aunque el bot se reinicie."""
    ws = _get_tecnicos_ws()
    cell = ws.find(str(chat_id), in_column=COL_TEC_CHAT_ID)
    if not cell:
        return None
    return ws.cell(cell.row, COL_TEC_NOMBRE).value


def set_periodo_reporte(
    fecha_inicio: dt.date, fecha_fin: dt.date, area: str = "Todos",
) -> None:
    """Fija el periodo y departamento/área del reporte contractual (celdas
    C13/E13/G13 de 'Reporte PDF'), controlando todos los cálculos de esa hoja."""
    ws_registro = _get_worksheet()
    sh = ws_registro.spreadsheet
    ws = sh.worksheet(REPORTE_PDF_WORKSHEET_NAME)
    ws.update([[fecha_inicio.strftime("%Y-%m-%d")]], "C13", value_input_option="USER_ENTERED")
    ws.update([[fecha_fin.strftime("%Y-%m-%d")]], "E13", value_input_option="USER_ENTERED")
    ws.update([[area]], "G13", value_input_option="USER_ENTERED")
    ws.update([[_ahora().strftime("%Y-%m-%d")]], "B6", value_input_option="USER_ENTERED")


def exportar_reporte_pdf(area: str = "Todos") -> tuple[bytes, str]:
    """Descarga la hoja 'Reporte PDF' como archivo binario PDF formateado
    y listo para enviar o imprimir."""
    ws_registro = _get_worksheet()
    sh = ws_registro.spreadsheet
    rep_ws = sh.worksheet(REPORTE_PDF_WORKSHEET_NAME)
    gid = rep_ws.id

    creds = _load_credentials()
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)

    params = {
        "format": "pdf",
        "gid": str(gid),
        "size": "letter",
        "portrait": "true",
        "fitw": "true",
        "gridlines": "false",
        "printtitle": "false",
        "sheetnames": "false",
        "fzr": "false",
    }
    url = f"https://docs.google.com/spreadsheets/d/{_get_sheet_id()}/export"
    token = creds.token
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(timeout=45, follow_redirects=True) as client:
        r = client.get(url, params=params, headers=headers)
        r.raise_for_status()
        pdf_bytes = r.content

    fecha_hoy = _ahora().strftime("%Y-%m-%d")
    sufijo_area = "General" if area in ("Todos", "General", "") else area.replace(" ", "_")
    nombre_archivo = f"Reporte_Avance_TI_{sufijo_area}_{fecha_hoy}.pdf"
    return pdf_bytes, nombre_archivo


def _next_folio() -> str:
    """Folio/ticket interno correlativo: FOLIO-0001, FOLIO-0002, ... (se usa
    cuando la actividad no trae un número de ticket real). Busca el mayor
    número correlativo existente para evitar colisiones."""
    ws = _get_worksheet()
    col = ws.col_values(COL_FOLIO)
    reales = col[3:]  # fila1=título, fila2=encabezado, fila3=ejemplo
    max_num = 0
    for val in reales:
        if val and str(val).startswith("FOLIO-"):
            try:
                num = int(str(val).split("-")[1])
                if num > max_num:
                    max_num = num
            except (ValueError, IndexError):
                pass
    siguiente = max(max_num + 1, len(reales) + 1)
    return f"FOLIO-{siguiente:04d}"


def _find_row_by_folio(folio: str) -> Optional[int]:
    ws = _get_worksheet()
    cell = ws.find(folio, in_column=COL_FOLIO)
    return cell.row if cell else None


def obtener_hora_inicio(folio: str) -> Optional[str]:
    """Obtiene la Hora Inicio guardada para un folio (columna I)."""
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return None
    ws = _get_worksheet()
    return ws.cell(row_idx, COL_HORA_INICIO).value


def start_activity(
    tecnico: str, ticket: Optional[str], area: str, ubicacion: str, problema: str,
    tipo_falla: str, prioridad: str, hora_inicio: Optional[str] = None,
) -> str:
    """Crea una fila nueva en 'Registro de Tickets'. Devuelve el folio (o el
    ticket si existía). Permite especificar una hora_inicio personalizada (HH:MM:SS)
    o usa la hora actual por defecto."""
    ws = _get_worksheet()
    folio = ticket if ticket else _next_folio()
    now = _ahora()
    fecha = now.strftime("%Y-%m-%d")
    hora_ini = hora_inicio if hora_inicio else now.strftime("%H:%M:%S")
    row = [
        "", area, folio, fecha, prioridad, ubicacion, tecnico, fecha,
        hora_ini, "", "", tipo_falla, problema, "", "", "",
        "", ESTATUS_EN_PROCESO, "", "", "", "", "", "",
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")
    row_idx = _find_row_by_folio(folio)
    if row_idx:
        ws.update_cell(row_idx, COL_NO, _formula_no(row_idx))
        ws.update_cell(row_idx, COL_DURACION, _formula_duracion(row_idx))
        ws.update_cell(row_idx, COL_RANK_PERIODO, _formula_rank_periodo(row_idx))
    return folio


def finish_activity(
    folio: str, solucion: str, recomendaciones: str = "", receptor: str = "",
    materiales: str = "", hora_fin: Optional[str] = None,
) -> bool:
    """Cierra la actividad en el Sheet. Permite especificar una hora_fin
    calculada o personalizada (HH:MM:SS) o usa la hora actual."""
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return False
    ws = _get_worksheet()
    hora_cierre = hora_fin if hora_fin else _ahora().strftime("%H:%M:%S")

    rec_val = recomendaciones if recomendaciones else "Ninguna"
    rec_final = rec_val
    if materiales and materiales != "N/A":
        extra = f"Materiales/repuestos usados: {materiales}"
        rec_final = f"{rec_val}\n{extra}".strip() if rec_val else extra

    receptor_val = receptor if receptor else "Atendido en campo"

    ws.update_cell(row_idx, COL_HORA_FIN, hora_cierre)
    ws.update_cell(row_idx, COL_ESTATUS, ESTATUS_CERRADO)
    ws.update_cell(row_idx, COL_SOLUCION, solucion)
    ws.update_cell(row_idx, COL_ENTREGADO_A, receptor_val)
    if rec_final:
        ws.update_cell(row_idx, COL_RECOMENDACIONES, rec_final)
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
            # OJO: hay que leer con value_render_option="FORMULA". Con el
            # default (FORMATTED_VALUE), una celda con =IMAGE() regresa vacío
            # -no hay texto que "mostrar" para una imagen- así que sin esto
            # cada foto nueva pensaba que "Foto 1" seguía libre y sobrescribía
            # la anterior en vez de pasar a "Foto 2".
            actual_col = ws.cell(row_idx, col, value_render_option=ValueRenderOption.formula).value
            if not actual_col:
                ws.update_cell(row_idx, col, f'=IMAGE("{url_formula}", 4, {TAMANO_FOTO_PX}, {TAMANO_FOTO_PX})')
                try:
                    _ajustar_dimensiones_foto(ws, row_idx)
                except Exception as e:
                    print(f"[sheets] aviso: no se pudieron ajustar dimensiones de foto: {e}")
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


def list_open_activities(tecnico: str) -> list[dict]:
    """Tickets 'En Proceso' del técnico (abiertos o pausados en el bot — el
    esquema del PRD no distingue eso a nivel de Sheet, ver docstring del
    módulo). La distinción "activo ahora mismo" vs "pausado" para el flujo
    del bot se hace en app/bot_logic.py comparando contra
    estado.folio_activo, no aquí.

    Lee por posición de columna (get_all_values), no por nombre de
    encabezado (get_all_records): la fila 2 del Sheet puede tener
    encabezados repetidos o vacíos de más si esa pestaña se creó con una
    versión anterior del código, y get_all_records truena en ese caso."""
    ws = _get_worksheet()
    filas = ws.get_all_values()[3:]  # después de título, encabezado y fila de ejemplo
    abiertas = []
    for fila in filas:
        folio = _valor(fila, COL_FOLIO)
        if not folio:
            continue
        if _valor(fila, COL_TECNICO) != tecnico or _valor(fila, COL_ESTATUS) != ESTATUS_EN_PROCESO:
            continue
        abiertas.append({
            "Folio": folio,
            "Tipo de Falla": _valor(fila, COL_TIPO_FALLA),
        })
    return abiertas
