"""
Sube evidencias (fotos y documentos) a Google Drive y regresa un link para verlas desde el
Google Sheet. Usa la MISMA cuenta de servicio que ya tienes para Sheets — solo
necesita permiso de Drive.
"""
import io
import mimetypes
import os
import json

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
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


def _get_folder_id() -> str:
    raw = os.environ.get("DRIVE_FOLDER_ID", "").strip()
    if not raw:
        return ""
    if "/folders/" in raw:
        # Extrae el ID si se pegó la URL completa de Google Drive
        raw = raw.split("/folders/")[-1].split("?")[0].split("/")[0].strip()
    return raw


def upload_photo(contenido: bytes, nombre_archivo: str, mime_type: str = "image/jpeg") -> str:
    """Sube una foto o archivo a Drive y regresa el link para verla (webViewLink)."""
    service = _get_service()
    
    # Inferir mime_type si viene genérico o por la extensión del archivo
    if mime_type == "image/jpeg" or not mime_type:
        guessed_type, _ = mimetypes.guess_type(nombre_archivo)
        if guessed_type:
            mime_type = guessed_type

    folder_id = _get_folder_id()
    metadata = {"name": nombre_archivo}
    if folder_id:
        metadata["parents"] = [folder_id]
    else:
        print("[drive] AVISO: DRIVE_FOLDER_ID no está configurado. La foto se subirá al directorio raíz de la cuenta de servicio.")


    media = MediaIoBaseUpload(io.BytesIO(contenido), mimetype=mime_type, resumable=False)
    archivo = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, webViewLink",
        supportsAllDrives=True,
    ).execute()

    # Intentamos hacerla visible por enlace. Si las políticas del dominio de la cuenta lo impiden, no rompemos el proceso.
    try:
        service.permissions().create(
            fileId=archivo["id"],
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
        ).execute()
    except Exception as pe:
        print(f"[drive] Aviso: No se pudo asignar permiso público 'anyone' ({pe}). El archivo igual se subió en Drive: {archivo.get('webViewLink')}")

    return archivo.get("webViewLink", f"https://drive.google.com/file/d/{archivo['id']}/view")


