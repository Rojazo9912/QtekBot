"""
Escritura a Google Sheets — reemplaza al Excel manual.

Requiere:
- Una cuenta de servicio de Google Cloud con la API de Sheets habilitada.
- El Google Sheet compartido como Editor con el email de esa cuenta de servicio.
- El JSON de credenciales guardado en la ruta indicada por GOOGLE_CREDENTIALS_PATH.

Estructura esperada de la hoja "Actividades" (fila 1 = encabezados):
Folio | Ticket | Técnico | Fecha | Hora Apertura | Hora Pausa | Hora Reanudación |
Hora Finalizado | Estado | Área | Problema | Solución | Receptor | Evidencias
"""
import os
import datetime as dt
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
CREDENTIALS_PATH = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
WORKSHEET_NAME = os.environ.get("GOOGLE_WORKSHEET_NAME", "Actividades")

HEADERS = [
    "Folio", "Ticket", "Técnico", "Fecha", "Hora Apertura", "Hora Pausa",
    "Hora Reanudación", "Hora Finalizado", "Estado", "Área", "Problema",
    "Solución", "Receptor", "Evidencias",
]

_client = None
_worksheet = None


def _get_worksheet():
    global _client, _worksheet
    if _worksheet is not None:
        return _worksheet
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    _client = gspread.authorize(creds)
    sh = _client.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=len(HEADERS))
        ws.append_row(HEADERS)
    _worksheet = ws
    return ws


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
    now = dt.datetime.now()
    row = [
        folio, ticket or "", tecnico, now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M:%S"), "", "", "", "En proceso", area, problema,
        "", "", "",
    ]
    ws.append_row(row)
    return folio


def pause_activity(folio: str) -> bool:
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return False
    ws = _get_worksheet()
    now = dt.datetime.now().strftime("%H:%M:%S")
    ws.update_cell(row_idx, 6, now)          # Hora Pausa
    ws.update_cell(row_idx, 9, "Pausada")    # Estado
    return True


def resume_activity(folio: str) -> bool:
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return False
    ws = _get_worksheet()
    now = dt.datetime.now().strftime("%H:%M:%S")
    ws.update_cell(row_idx, 7, now)             # Hora Reanudación
    ws.update_cell(row_idx, 9, "En proceso")    # Estado
    return True


def finish_activity(folio: str, solucion: str, receptor: str) -> bool:
    row_idx = _find_row_by_folio(folio)
    if not row_idx:
        return False
    ws = _get_worksheet()
    now = dt.datetime.now().strftime("%H:%M:%S")
    ws.update_cell(row_idx, 8, now)              # Hora Finalizado
    ws.update_cell(row_idx, 9, "Finalizada")     # Estado
    ws.update_cell(row_idx, 12, solucion)        # Solución
    ws.update_cell(row_idx, 13, receptor)        # Receptor
    return True


def list_open_activities(tecnico: str) -> list[dict]:
    ws = _get_worksheet()
    records = ws.get_all_records()
    return [
        r for r in records
        if r.get("Técnico") == tecnico and r.get("Estado") in ("En proceso", "Pausada")
    ]
