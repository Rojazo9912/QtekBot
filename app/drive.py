"""
Sube evidencias (fotos) a Google Drive y regresa un link para verlas desde el
Google Sheet. Usa la MISMA cuenta de servicio que ya tienes para Sheets — solo
necesita permiso extra de Drive.

Setup adicional (una sola vez):
1. En Google Cloud Console, habilita también la "Google Drive API" (además de
   la de Sheets que ya habilitaste).
2. En tu Google Drive normal (el de tu cuenta, no la cuenta de servicio),
   crea una carpeta para las evidencias del piloto.
3. Comparte esa carpeta como Editor con el mismo email de la cuenta de
   servicio (el "client_email" del JSON, ej. fieldti-bot@...gserviceaccount.com)
   — igual que hiciste con el Sheet.
4. Copia el ID de la carpeta de la URL (la parte después de /folders/) y
   ponlo en la variable de entorno DRIVE_FOLDER_ID.

Nota de privacidad, para que la conozcas: las fotos se suben con permiso
"cualquiera con el link puede ver" — no son públicas por buscador, pero
tampoco están restringidas a personas específicas. Es lo más simple para que
el link funcione directo desde el Sheet sin pedir login. Si necesitas más
control de acceso, se puede cambiar por compartir solo con los correos de tu
equipo, pero eso complica el setup.
"""
import io
import os
import json

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")

_drive_service = None


def _load_credentials() -> Credentials:
    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    credentials_path = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    if credentials_json:
        info = json.loads(credentials_json)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    if os.path.exists(credentials_path):
        return Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    raise RuntimeError(
        "No hay credenciales de Google configuradas. Define GOOGLE_CREDENTIALS_JSON "
        "o GOOGLE_CREDENTIALS_PATH (las mismas que usa app/sheets.py)."
    )


def _get_service():
    global _drive_service
    if _drive_service is not None:
        return _drive_service
    creds = _load_credentials()
    _drive_service = build("drive", "v3", credentials=creds)
    return _drive_service


def upload_photo(contenido: bytes, nombre_archivo: str, mime_type: str = "image/jpeg") -> str:
    """Sube una foto a Drive y regresa el link para verla (webViewLink)."""
    service = _get_service()
    metadata = {"name": nombre_archivo}
    if DRIVE_FOLDER_ID:
        metadata["parents"] = [DRIVE_FOLDER_ID]
    media = MediaIoBaseUpload(io.BytesIO(contenido), mimetype=mime_type, resumable=False)
    archivo = service.files().create(body=metadata, media_body=media, fields="id, webViewLink").execute()

    # La hacemos visible por link para que se pueda abrir directo desde el Sheet.
    service.permissions().create(
        fileId=archivo["id"], body={"type": "anyone", "role": "reader"}
    ).execute()

    return archivo["webViewLink"]
