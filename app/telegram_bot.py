"""
Módulo de compatibilidad: Railway aún puede arrancar con
`uvicorn app.telegram_bot:app`. La aplicación vive en app/main.py.
"""
from app.main import app

__all__ = ["app"]
