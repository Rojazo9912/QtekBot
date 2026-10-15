"""
Generación de archivo ZIP en memoria con las fotos y evidencias de los reportes.
Permite descargar en lote todas las imágenes de un periodo para auditoría o supervisión.
"""
import datetime as dt
import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx

from app import storage


def _descargar_foto(url: str) -> Optional[bytes]:
    """Intenta descargar la evidencia desde Supabase Storage o mediante HTTP."""
    try:
        return storage.descargar_evidencia(url)
    except Exception:
        pass
    try:
        res = httpx.get(url, timeout=15, follow_redirects=True)
        res.raise_for_status()
        return res.content
    except Exception as e:
        print(f"[zip_export] Error descargando {url}: {e}")
        return None


def _limpiar_nombre(texto: str) -> str:
    """Convierte un string en algo seguro para nombre de archivo en ZIP."""
    return re.sub(r"[^\w\-_.]", "_", texto.strip())


def generar_zip_evidencias(
    reportes: list[dict],
    desde: dt.date,
    hasta: dt.date,
) -> tuple[bytes, str]:
    """Genera un archivo ZIP con las fotos de los reportes del periodo.
    Regresa (bytes_del_zip, nombre_del_archivo).
    """
    nombre_zip = f"Evidencias_{desde.strftime('%Y%m%d')}_{hasta.strftime('%Y%m%d')}.zip"

    # Mapear evidencias a descargar
    items_a_descargar = []
    for rep in reportes:
        num = _limpiar_nombre(rep.get("numero", "rep"))
        tkt = _limpiar_nombre(rep.get("ticket", "st"))
        evidencias = rep.get("evidencias") or []
        for idx, url in enumerate(evidencias, 1):
            items_a_descargar.append({
                "url": url,
                "nombre": f"{num}_{tkt}_foto_{idx}.jpg",
            })

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if not items_a_descargar:
            zf.writestr(
                "informacion.txt",
                f"No se registraron evidencias fotográficas para el periodo del {desde.isoformat()} al {hasta.isoformat()}.",
            )
        else:
            urls = [item["url"] for item in items_a_descargar]
            with ThreadPoolExecutor(max_workers=8) as pool:
                contenidos = list(pool.map(_descargar_foto, urls))

            for item, contenido in zip(items_a_descargar, contenidos):
                if contenido:
                    zf.writestr(item["nombre"], contenido)

    buffer.seek(0)
    return buffer.getvalue(), nombre_zip
