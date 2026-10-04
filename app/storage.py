"""
Sube evidencias (fotos y documentos) a Supabase Storage y regresa una URL
pública permanente, que se guarda en el reporte y aparece en la hoja
"Evidencias" del Excel.

Setup (una sola vez):
1. En tu proyecto de Supabase, ve a Storage > New Bucket.
   - Nombre: "evidencias" (o el que prefieras, en SUPABASE_BUCKET).
   - Activa "Public bucket" para que los links abran sin login.
2. SUPABASE_URL y SUPABASE_KEY (service_role) son las mismas que usa la base
   de datos (ver app/supabase_client.py).
"""
import mimetypes
import os
from typing import Optional
from urllib.parse import unquote, urlparse

from app.supabase_client import get_client

SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "evidencias")


def ruta_normalizada(nombre_archivo: str) -> str:
    """Supabase rechaza paths con espacios; los reemplazamos con guiones."""
    return nombre_archivo.replace(" ", "-")


def upload_evidence(contenido: bytes, nombre_archivo: str, mime_type: str = "image/jpeg") -> str:
    """Sube una foto o archivo a Supabase Storage.
    Devuelve la URL pública permanente del archivo.
    """
    client = get_client()

    # Inferir mime_type por extensión si viene genérico
    if not mime_type or mime_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(nombre_archivo)
        if guessed:
            mime_type = guessed

    ruta = ruta_normalizada(nombre_archivo)

    try:
        client.storage.from_(SUPABASE_BUCKET).upload(
            path=ruta,
            file=contenido,
            file_options={"content-type": mime_type, "upsert": "true"},
        )
    except Exception as upload_err:
        # Algunas versiones del SDK de Supabase lanzan un error interno
        # ("cannot access local variable 'response'") aunque el archivo
        # se subió correctamente; en ese caso ignoramos la excepción.
        err_msg = str(upload_err)
        if "response" not in err_msg and "already exists" not in err_msg.lower():
            raise

    url = client.storage.from_(SUPABASE_BUCKET).get_public_url(ruta)
    # El SDK (storage3) siempre concatena "?" al final, incluso sin
    # parámetros de query; lo quitamos para guardar un link limpio.
    return url.rstrip("?")


def ruta_desde_url(url: str) -> Optional[str]:
    """".../storage/v1/object/public/<bucket>/<ruta>" → "<ruta>".
    None si el link no es de este bucket."""
    marca = f"/object/public/{SUPABASE_BUCKET}/"
    camino = urlparse(url).path
    if marca not in camino:
        return None
    return unquote(camino.split(marca, 1)[1])


def descargar_evidencia(url: str) -> bytes:
    """Descarga una evidencia guardada con upload_evidence. Usa la
    service_role key, así que funciona aunque el bucket no sea público."""
    ruta = ruta_desde_url(url)
    if ruta is None:
        raise ValueError(f"El link no es del bucket {SUPABASE_BUCKET}: {url}")
    return get_client().storage.from_(SUPABASE_BUCKET).download(ruta)
