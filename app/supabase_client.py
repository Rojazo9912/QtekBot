"""
Cliente único de Supabase, compartido por la base de datos (app/db.py) y el
Storage de evidencias (app/storage.py).
"""
import os

from supabase import create_client, Client

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "Supabase no está configurado. Define SUPABASE_URL y SUPABASE_KEY "
            "en las variables de entorno (Railway o .env local)."
        )
    _client = create_client(url, key)
    return _client
