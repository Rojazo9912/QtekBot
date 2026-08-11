"""
Web app (Módulo de compatibilidad).

La aplicación principal se ha consolidado en app/main.py para servir tanto el
bot de Telegram como la interfaz Web App desde un único comando.
"""
from app.main import app

__all__ = ["app"]

