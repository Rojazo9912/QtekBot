"""
Sube evidencias (fotos y documentos) a Supabase Storage y regresa una URL
pública permanente para guardar en el Google Sheet.

Ventajas sobre Google Drive con cuenta de servicio:
- Sin problemas de cuota: la cuenta de servicio de Google no tiene storage propio.
- URLs públicas permanentes y directas.
- Plan gratuito de Supabase: 1 GB de almacenamiento incluido.

Setup (una sola vez):
1. Crea un proyecto en https://supabase.com (plan gratuito suficiente).
2. En tu proyecto, ve a Storage > New Bucket.
   - Nombre: "evidencias" (o el que prefieras).
   - Activa "Public bucket" para que los archivos sean accesibles por URL sin login.
3. En Project Settings > API, copia:
   - Project URL  → SUPABASE_URL
   - service_role key (no la anon key) → SUPABASE_KEY
4. Agrega esas dos variables en Railway (y en tu .env local).
"""
import mimetypes
import os

from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "evidencias")

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is not None:
        return _client
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "Supabase no está configurado. Define SUPABASE_URL y SUPABASE_KEY "
            "en las variables de entorno (Railway o .env local)."
        )
    _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def ruta_normalizada(nombre_archivo: str) -> str:
    """Supabase rechaza paths con espacios; los reemplazamos con guiones."""
    return nombre_archivo.replace(" ", "-")


def upload_evidence(contenido: bytes, nombre_archivo: str, mime_type: str = "image/jpeg") -> str:
    """Sube una foto o archivo a Supabase Storage.
    Devuelve la URL pública permanente del archivo.
    """
    client = _get_client()

    # Inferir mime_type por extensión si viene genérico
    if not mime_type or mime_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(nombre_archivo)
        if guessed:
            mime_type = guessed

    ruta = ruta_normalizada(nombre_archivo)

    client.storage.from_(SUPABASE_BUCKET).upload(
        path=ruta,
        file=contenido,
        file_options={"content-type": mime_type, "upsert": "true"},
    )

    url = client.storage.from_(SUPABASE_BUCKET).get_public_url(ruta)
    # El SDK de Supabase (storage3) siempre concatena "?" al final, incluso
    # sin parámetros de query. Un "?" colgante puede hacer que el detector de
    # tipo de imagen de Google Sheets (=IMAGE()) no reconozca la URL como
    # foto y la muestre en negro/rota.
    return url.rstrip("?")


def download_evidence(ruta: str) -> tuple[bytes, str]:
    """Descarga el archivo desde Supabase Storage. Se usa para volver a
    servirlo desde nuestro propio servidor (ver /evidencia/<ruta> en
    app/main.py) en vez de mandar directo la URL de Supabase para la
    miniatura =IMAGE() del Sheet: las respuestas de Supabase Storage traen
    el header "X-Robots-Tag: none" (lo agrega Supabase, no algo que
    controlemos desde este SDK), y el fetcher de imágenes de Google Sheets
    lo respeta, así que no renderiza la miniatura aunque la URL funcione
    perfecto para abrir en el navegador."""
    client = _get_client()
    contenido = client.storage.from_(SUPABASE_BUCKET).download(ruta)
    mime_type, _ = mimetypes.guess_type(ruta)
    return contenido, mime_type or "application/octet-stream"
