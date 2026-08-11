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

Estructura esperada de la hoja "Actividades" (fila 1 = encabezados):
Folio | Ticket | Técnico | Fecha | Hora Apertura | Hora Pausa | Hora Reanudación |
Hora Finalizado | Estado | Área | Problema | Solución | Receptor | Evidencias |
Foto 1 | Foto 2 | Foto 3

Las columnas "Foto N" muestran una miniatura de la imagen (fórmula =IMAGE()) para
hasta 3 evidencias por actividad; si se suben más de 3, las adicionales solo
quedan como link de texto en "Evidencias". La columna "Evidencias" sigue
llevando el registro completo en texto de todos los links, como respaldo.
"""
import os
import json
import datetime as dt
from typing import Optional
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
CREDENTIALS_PATH = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
WORKSHEET_NAME = os.environ.get("GOOGLE_WORKSHEET_NAME", "Actividades")

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
    "Folio", "Ticket", "Técnico", "Fecha", "Hora Apertura", "Hora Pausa",
    "Hora Reanudación", "Hora Finalizado", "Estado", "Área", "Problema",
    "Solución", "Receptor", "Evidencias", "Foto 1", "Foto 2", "Foto 3",
]

COL_EVIDENCIAS = 14
COL_FOTOS = [15, 16, 17]  # columnas con miniatura =IMAGE(), una por evidencia (máx. 3)

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
        _asegurar_columnas_evidencia(ws)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=len(HEADERS))
        ws.append_row(HEADERS)
    _worksheet = ws
    return ws


def _asegurar_columnas_evidencia(ws) -> None:
    """Migra hojas creadas antes de las columnas Foto 1-3: agrega los
    encabezados que falten y expande la cuadrícula si hace falta. No toca
    filas ya existentes."""
    encabezados = ws.row_values(1)
    if len(encabezados) >= len(HEADERS):
        return
    if ws.col_count < len(HEADERS):
        ws.add_cols(len(HEADERS) - ws.col_count)
    faltantes = HEADERS[len(encabezados):]
    rango = f"{rowcol_to_a1(1, len(encabezados) + 1)}:{rowcol_to_a1(1, len(HEADERS))}"
    ws.update([faltantes], rango)


def _next_folio() -> str:
    """Folio interno correlativo: FOLIO-0001, FOLIO-0002, ..."""
    ws = _get_worksheet()
    col = ws.col_values(1)  # columna Folio
    count = max(0, len(col) - 1)  # menos encabezado
    return f"FOLIO-{count + 1:04d}"


def _find_row_by_folio(folio: str) -> Optional[int]:
    ws = _get_worksheet()
    cell = ws.find(folio, in_column=1)
    return cell.row if cell else None


def start_activity(tecnico: str, ticket: Optional[str], area: str, problema: str) -> str:
    """Crea una fila nueva. Devuelve el folio (o el ticket si existía)."""
    ws = _get_worksheet()
    folio = ticket if ticket else _next_folio()
    now = _ahora()
    row = [
        folio, ticket or "", tecnico, now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M:%S"), "", "", "", "En proceso", area, problema,
        "", "", "", "", "", "",
    ]
    ws.append_row(row)
    return folio


def pause_activity(folio: str) -> bool:
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return False
    ws = _get_worksheet()
    now = _ahora().strftime("%H:%M:%S")
    ws.update_cell(row_idx, 6, now)          # Hora Pausa
    ws.update_cell(row_idx, 9, "Pausada")    # Estado
    return True


def resume_activity(folio: str) -> bool:
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return False
    ws = _get_worksheet()
    now = _ahora().strftime("%H:%M:%S")
    ws.update_cell(row_idx, 7, now)             # Hora Reanudación
    ws.update_cell(row_idx, 9, "En proceso")    # Estado
    return True


def finish_activity(folio: str, solucion: str, receptor: str) -> bool:
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return False
    ws = _get_worksheet()
    now = _ahora().strftime("%H:%M:%S")
    ws.update_cell(row_idx, 8, now)              # Hora Finalizado
    ws.update_cell(row_idx, 9, "Finalizada")     # Estado
    ws.update_cell(row_idx, 12, solucion)        # Solución
    ws.update_cell(row_idx, 13, receptor)        # Receptor
    return True


def add_evidence(folio: str, link: str, mime_type: str = "image/jpeg") -> bool:
    """Anexa un link de evidencia a la fila del folio (columna Evidencias, texto
    completo como respaldo). Si además es una imagen y hay un hueco libre entre
    las columnas Foto 1-3, escribe ahí una miniatura con =IMAGE() para verla
    directo en el Sheet. A partir de la 4a foto (o si no es imagen), solo queda
    el link en texto."""
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return False
    ws = _get_worksheet()

    actual = ws.cell(row_idx, COL_EVIDENCIAS).value or ""
    nuevo = f"{actual}\n{link}".strip() if actual else link
    ws.update_cell(row_idx, COL_EVIDENCIAS, nuevo)

    if mime_type.startswith("image/"):
        for col in COL_FOTOS:
            if not ws.cell(row_idx, col).value:
                ws.update_cell(row_idx, col, f'=IMAGE("{link}", 4, 120, 120)')
                break

    return True


def list_open_activities(tecnico: str) -> list[dict]:
    ws = _get_worksheet()
    records = ws.get_all_records()
    return [
        r for r in records
        if r.get("Técnico") == tecnico and r.get("Estado") in ("En proceso", "Pausada")
    ]
