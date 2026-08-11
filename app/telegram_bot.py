"""
Bot de Telegram (Módulo de compatibilidad).

La aplicación principal se ha consolidado en app/main.py para simplificar el
despliegue en Railway y la gestión del bot.
"""
from app.main import app

__all__ = ["app"]

