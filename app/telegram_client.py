"""
Cliente delgado para la API de Bots de Telegram (https://core.telegram.org/bots/api).
Mucho más simple que WhatsApp Cloud API: no hay verificación de negocio, no hay
modo desarrollo/producción, no hay formato de número ambiguo. El token que te
da @BotFather es lo único que necesitas.
"""
import os
import httpx

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_URL = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else ""

# Teclado persistente para técnicos estándar
TECLADO_ACCIONES = {
    "keyboard": [
        [{"text": "+ Nueva actividad"}, {"text": "⏸ Pausar"}],
        [{"text": "▶ Reanudar"}, {"text": "✓ Finalizar"}],
        [{"text": "☰ Mis actividades"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

# Teclado persistente exclusivo para administradores
TECLADO_ADMIN = {
    "keyboard": [
        [{"text": "+ Nueva actividad"}, {"text": "⏸ Pausar"}],
        [{"text": "▶ Reanudar"}, {"text": "✓ Finalizar"}],
        [{"text": "☰ Mis actividades"}],
        [{"text": "👤 + Nuevo técnico"}, {"text": "📄 Reporte PDF"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

# Mapeo de botones y frases comunes a comandos limpios para bot_logic
ALIAS_BOTONES = {
    "+ nueva actividad": "nueva actividad",
    "⏸ pausar": "pausar",
    "▶ reanudar": "reanudar",
    "✓ finalizar": "finalizar",
    "☰ mis actividades": "mis actividades",
    "👤 + nuevo técnico": "nuevo tecnico",
    "👤 + nuevo tecnico": "nuevo tecnico",
    "+ nuevo técnico": "nuevo tecnico",
    "+ nuevo tecnico": "nuevo tecnico",
    "nuevo técnico": "nuevo tecnico",
    "nuevo tecnico": "nuevo tecnico",
    "dar de alta a un usuario": "nuevo tecnico",
    "dar de alta usuario": "nuevo tecnico",
    "dar de alta": "nuevo tecnico",
    "agregar técnico": "nuevo tecnico",
    "agregar tecnico": "nuevo tecnico",
    "📄 reporte pdf": "reporte pdf",
    "reporte pdf": "reporte pdf",
    "generar reporte": "reporte pdf",
    "reporte": "reporte pdf",
    "comandos": "ayuda",
    "ayuda": "ayuda",
}


def normalizar_texto_boton(texto: str) -> str:
    return ALIAS_BOTONES.get(texto.strip().lower(), texto)


def send_text(chat_id: int, texto: str, con_teclado: bool = True, es_admin: bool = False) -> None:
    if not TOKEN:
        print("[telegram] AVISO: TELEGRAM_BOT_TOKEN no está configurado.")
        return
    payload = {"chat_id": chat_id, "text": texto}
    if con_teclado:
        payload["reply_markup"] = TECLADO_ADMIN if es_admin else TECLADO_ACCIONES
    try:
        with httpx.Client(timeout=10) as http:
            r = http.post(f"{API_URL}/sendMessage", json=payload)
            if r.status_code >= 400:
                print(f"[telegram] error {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[telegram] error enviando mensaje: {e}")


def send_opciones(chat_id: int, texto: str, opciones: list[str]) -> None:
    """Teclado de respuesta rápida, una opción por fila (catálogos fijos
    como Tipo de Falla o Prioridad). Es de un solo uso: en cuanto el técnico
    responde, Telegram lo reemplaza por el teclado persistente de atajos."""
    if not TOKEN:
        print("[telegram] AVISO: TELEGRAM_BOT_TOKEN no está configurado.")
        return
    teclado = {
        "keyboard": [[{"text": o}] for o in opciones],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }
    payload = {"chat_id": chat_id, "text": texto, "reply_markup": teclado}
    try:
        with httpx.Client(timeout=10) as http:
            r = http.post(f"{API_URL}/sendMessage", json=payload)
            if r.status_code >= 400:
                print(f"[telegram] error {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[telegram] error enviando opciones: {e}")


def set_webhook(url: str) -> dict:
    if not TOKEN:
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN no configurado"}
    with httpx.Client(timeout=10) as http:
        r = http.post(f"{API_URL}/setWebhook", json={"url": url})
        return r.json()


def get_file_url(file_id: str) -> str:
    """Obtiene el link directo de descarga del archivo desde los servidores de Telegram.
    No descarga el contenido — solo resuelve la URL. El link es válido mientras el bot tenga acceso al archivo.
    """
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN no está configurado.")
    with httpx.Client(timeout=10) as http:
        r = http.get(f"{API_URL}/getFile", params={"file_id": file_id})
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]
        return f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"


def descargar_foto(file_id: str) -> tuple[bytes, str]:
    """Descarga una foto o archivo de Telegram. Regresa (contenido_en_bytes, file_path)."""
    return descargar_archivo(file_id)


def descargar_archivo(file_id: str) -> tuple[bytes, str]:
    """Descarga un archivo/foto de Telegram. Regresa (contenido_en_bytes, file_path)."""
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN no está configurado.")
    with httpx.Client(timeout=30) as http:
        r = http.get(f"{API_URL}/getFile", params={"file_id": file_id})
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        r2 = http.get(file_url)
        r2.raise_for_status()
        return r2.content, file_path
