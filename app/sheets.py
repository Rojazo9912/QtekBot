"""
Escritura a Google Sheets — esquema "Reportes" (PRD v1.1 - Reporte de Campo Ágil para Mina).

Una sola hoja "Reportes" con 10 columnas:
1. Numero (Consecutivo #001, #002…)
2. Ticket (Texto libre, obligatorio)
3. Tecnico (Nombre del técnico)
4. Ubicacion (Nivel 10 / Nivel 11 / Nivel 12 / Otra)
5. Actividad (Descripción; se le anexan actualizaciones)
6. Estado (Terminado / Pendiente / No solucionado)
7. Evidencias (Links de Google Drive)
8. Fecha (YYYY-MM-DD)
9. Hora (HH:MM:SS)
10. Actualizado (YYYY-MM-DD HH:MM:SS)
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
    CATALOGO_UBICACION, CATALOGO_ESTADO_REPORTE,
    TECNICOS, TECNICOS_INFO, ADMIN_TECNICOS,
)

import httpx
import google.auth.transport.requests

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Servidor corre en UTC, ajustamos a la zona horaria del proyecto
ZONA_HORARIA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Mexico_City"))


def _ahora() -> dt.datetime:
    return dt.datetime.now(ZONA_HORARIA)


def _get_sheet_id() -> str:
    return os.environ.get("GOOGLE_SHEET_ID", "").strip()


def _get_credentials_json() -> Optional[str]:
    return os.environ.get("GOOGLE_CREDENTIALS_JSON")


def _get_worksheet_name() -> str:
    val = os.environ.get("GOOGLE_WORKSHEET_NAME", "Reportes")
    return val.strip() if val else "Reportes"


def _load_credentials() -> Credentials:
    creds_json = _get_credentials_json()
    creds_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    if creds_json:
        try:
            info = json.loads(creds_json)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                "GOOGLE_CREDENTIALS_JSON no es un JSON válido."
            ) from e
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    if os.path.exists(creds_path):
        return Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    raise RuntimeError(
        "No hay credenciales de Google configuradas. Define GOOGLE_CREDENTIALS_JSON "
        "o GOOGLE_CREDENTIALS_PATH."
    )


# --- Columnas de "Reportes" (PRD v1.1 - 10 Columnas) ---
COL_NUMERO = 1
COL_TICKET = 2
COL_TECNICO = 3
COL_UBICACION = 4
COL_ACTIVIDAD = 5
COL_ESTADO = 6
COL_EVIDENCIAS = 7
COL_FECHA = 8
COL_HORA = 9
COL_ACTUALIZADO = 10

HEADERS_REPORTES = [
    "Numero", "Ticket", "Tecnico", "Ubicacion", "Actividad",
    "Estado", "Evidencias", "Fecha", "Hora", "Actualizado",
]

TITULO_REPORTES = "Reportes de Campo TI — Unidad San Dimas"

# Hoja de técnicos
TECNICOS_WORKSHEET_NAME = "Técnicos"
TITULO_TECNICOS = "Técnicos Autorizados"
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


def _valor(fila: list, col: int) -> str:
    idx = col - 1
    return fila[idx] if idx < len(fila) else ""


def _ensure_reportes(sh):
    ws_name = _get_worksheet_name()
    try:
        return sh.worksheet(ws_name)
    except gspread.WorksheetNotFound:
        pass

    # Intentar fallback a 'Reporte Diario' si existía esa pestaña en el sheet del usuario
    try:
        return sh.worksheet("Reporte Diario")
    except gspread.WorksheetNotFound:
        pass

    ws = sh.add_worksheet(title=ws_name, rows=2000, cols=len(HEADERS_REPORTES))
    ws.update([[TITULO_REPORTES]], "A1")
    ws.update([HEADERS_REPORTES], "A2", value_input_option="USER_ENTERED")
    return ws


def _ensure_tecnicos(sh):
    try:
        return sh.worksheet(TECNICOS_WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        pass
    ws = sh.add_worksheet(title=TECNICOS_WORKSHEET_NAME, rows=50, cols=len(HEADERS_TECNICOS))
    ws.update([[TITULO_TECNICOS]], "A1")
    ws.update([HEADERS_TECNICOS], "A2", value_input_option="USER_ENTERED")
    return ws


def _get_worksheet():
    global _client, _worksheet, _tecnicos_ws
    if _worksheet is not None:
        return _worksheet
    sheet_id = _get_sheet_id()
    if not sheet_id:
        raise RuntimeError("No se ha configurado GOOGLE_SHEET_ID en las variables de entorno.")
    creds = _load_credentials()
    _client = gspread.authorize(creds)
    sh = _client.open_by_key(sheet_id)
    ws = _ensure_reportes(sh)
    _tecnicos_ws = _ensure_tecnicos(sh)
    _worksheet = ws
    return ws


def _get_tecnicos_ws():
    _get_worksheet()
    return _tecnicos_ws


def listar_tecnicos() -> list[str]:
    ws = _get_tecnicos_ws()
    nombres = ws.col_values(1)[2:]
    return [n.strip() for n in nombres if n.strip()]


def agregar_tecnico(
    nombre: str, cargo: str = "Técnico de Campo", imss: str = "N/A",
) -> Optional[str]:
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
    ws = _get_tecnicos_ws()
    filas = ws.get_all_values()[2:]
    for fila in filas:
        if _valor(fila, COL_TEC_NOMBRE) == nombre:
            codigo = _valor(fila, COL_TEC_CODIGO).strip()
            return codigo or None
    return None


def activar_tecnico_por_codigo(codigo: str, chat_id: int) -> Optional[str]:
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
    ws = _get_tecnicos_ws()
    cell = ws.find(str(chat_id), in_column=COL_TEC_CHAT_ID)
    if not cell:
        return None
    return ws.cell(cell.row, COL_TEC_NOMBRE).value


def _next_numero_reporte(ws) -> str:
    filas = ws.get_all_values()
    # Fila 1 es título, fila 2 son encabezados.
    cant_registros = max(0, len(filas) - 2)
    siguiente = cant_registros + 1
    return f"#{siguiente:03d}"


def crear_reporte(
    ticket: str,
    tecnico: str,
    ubicacion: str,
    actividad: str,
    estado: str,
    evidencias: Optional[str] = None,
) -> str:
    """Crea un nuevo reporte en la hoja 'Reportes' con consecutivo automático (#001, #002...)."""
    ws = _get_worksheet()
    numero = _next_numero_reporte(ws)
    now = _ahora()
    fecha_str = now.strftime("%Y-%m-%d")
    hora_str = now.strftime("%H:%M:%S")
    actualizado_str = now.strftime("%Y-%m-%d %H:%M:%S")
    evidencias_str = evidencias.strip() if evidencias else ""

    row_data = [
        numero,
        ticket.strip(),
        tecnico.strip(),
        ubicacion.strip(),
        actividad.strip(),
        estado.strip(),
        evidencias_str,
        fecha_str,
        hora_str,
        actualizado_str,
    ]
    ws.append_row(row_data, value_input_option="USER_ENTERED")
    return numero


def listar_reportes_pendientes(tecnico: str) -> list[dict]:
    """Obtiene los reportes en estado 'Pendiente' del técnico especificado."""
    ws = _get_worksheet()
    filas = ws.get_all_values()[2:]
    pendientes = []
    for fila in filas:
        if not fila or len(fila) < 6:
            continue
        num = _valor(fila, COL_NUMERO)
        tec = _valor(fila, COL_TECNICO)
        est = _valor(fila, COL_ESTADO)
        if tec.lower() == tecnico.lower() and _normalizar_estado(est) == "Pendiente":
            pendientes.append({
                "Numero": num,
                "Ticket": _valor(fila, COL_TICKET),
                "Ubicacion": _valor(fila, COL_UBICACION),
                "Actividad": _valor(fila, COL_ACTIVIDAD),
                "Estado": est,
                "Fecha": _valor(fila, COL_FECHA),
                "Hora": _valor(fila, COL_HORA),
            })
    return pendientes


def actualizar_reporte_pendiente(
    numero: str,
    nueva_actividad: str,
    nuevo_estado: str,
) -> bool:
    """Anexa una actualización al campo Actividad y cambia el Estado del reporte."""
    ws = _get_worksheet()
    cell = ws.find(numero, in_column=COL_NUMERO)
    if not cell:
        return False
    row_idx = cell.row
    actividad_actual = ws.cell(row_idx, COL_ACTIVIDAD).value or ""
    now = _ahora()
    timestamp = now.strftime("[%Y-%m-%d %H:%M]")
    nueva_act = nueva_actividad.strip()
    if nueva_act:
        actividad_actualizada = f"{actividad_actual}\n{timestamp} {nueva_act}".strip()
    else:
        actividad_actualizada = actividad_actual

    actualizado_timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    ws.update_cell(row_idx, COL_ACTIVIDAD, actividad_actualizada)
    ws.update_cell(row_idx, COL_ESTADO, nuevo_estado.strip())
    ws.update_cell(row_idx, COL_ACTUALIZADO, actualizado_timestamp)
    return True


def listar_mis_reportes(tecnico: str) -> list[dict]:
    """Lista todos los reportes creados por un técnico."""
    ws = _get_worksheet()
    filas = ws.get_all_values()[2:]
    reportes = []
    for fila in filas:
        if not fila or len(fila) < 6:
            continue
        tec = _valor(fila, COL_TECNICO)
        if tec.lower() == tecnico.lower():
            reportes.append({
                "Numero": _valor(fila, COL_NUMERO),
                "Ticket": _valor(fila, COL_TICKET),
                "Ubicacion": _valor(fila, COL_UBICACION),
                "Estado": _valor(fila, COL_ESTADO),
                "Fecha": _valor(fila, COL_FECHA),
            })
    return reportes


def limpiar_registros_tickets() -> int:
    """Elimina los registros reales (fila 3 en adelante) en 'Reportes'."""
    ws = _get_worksheet()
    todas = ws.get_all_values()
    cant_filas = len(todas)
    if cant_filas >= 3:
        ws.delete_rows(3, cant_filas)
        return cant_filas - 2
    return 0


def _normalizar_estado(est: str) -> str:
    est_clean = est.strip().lower()
    if "pendiente" in est_clean:
        return "Pendiente"
    if "terminado" in est_clean or "cerrado" in est_clean:
        return "Terminado"
    if "no solucionado" in est_clean or "fallo" in est_clean:
        return "No solucionado"
    return est.strip()


# Helpers para compatibilidad con código/tests anteriores
def start_activity(*args, **kwargs):
    tecnico = kwargs.get("tecnico", args[0] if args else "")
    ticket = kwargs.get("ticket") or "TK-0001"
    ubicacion = kwargs.get("ubicacion") or "Nivel 10"
    problema = kwargs.get("problema") or "Actividad iniciada"
    return crear_reporte(ticket=ticket, tecnico=tecnico, ubicacion=ubicacion, actividad=problema, estado="Pendiente")


def finish_activity(folio, solucion="Concluido", **kwargs):
    return actualizar_reporte_pendiente(folio, nueva_actividad=solucion, nuevo_estado="Terminado")


def list_open_activities(tecnico: str) -> list[dict]:
    pendientes = listar_reportes_pendientes(tecnico)
    return [{"Folio": p["Numero"], "Tipo de Falla": p["Actividad"]} for p in pendientes]


def set_periodo_reporte(fecha_inicio: dt.date, fecha_fin: dt.date, area: str = "Todos") -> None:
    pass


def exportar_reporte_pdf(area: str = "Todos") -> tuple[bytes, str]:
    return b"%PDF-1.4 Reportes", "Reporte_Campo.pdf"
