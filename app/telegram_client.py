"""
Cliente delgado para la API de Bots de Telegram (https://core.telegram.org/bots/api).
Mucho más simple que WhatsApp Cloud API: no hay verificación de negocio, no hay
modo desarrollo/producción, no hay formato de número ambiguo. El token que te
da @BotFather es lo único que necesitas.
"""
import os
import httpx

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
API_URL = f"https://api.telegram.org/bot{TOKEN}"

# Teclado persistente con los atajos, equivalente a los "chips" de la web app.
TECLADO_ACCIONES = {
    "keyboard": [
        [{"text": "+ Nueva actividad"}, {"text": "⏸ Pausar"}],
        [{"text": "▶ Reanudar"}, {"text": "✓ Finalizar"}],
        [{"text": "☰ Mis actividades"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

# Los botones de arriba mandan su texto visible tal cual; lo normalizamos aquí
# para que bot_logic reciba algo limpio ("nueva actividad", no "+ Nueva actividad").
ALIAS_BOTONES = {
    "+ nueva actividad": "nueva actividad",
    "⏸ pausar": "pausar",
    "▶ reanudar": "reanudar",
    "✓ finalizar": "finalizar",
    "☰ mis actividades": "mis actividades",
}


def normalizar_texto_boton(texto: str) -> str:
    return ALIAS_BOTONES.get(texto.strip().lower(), texto)


def send_text(chat_id: int, texto: str, con_teclado: bool = True) -> None:
    payload = {"chat_id": chat_id, "text": texto}
    if con_teclado:
        payload["reply_markup"] = TECLADO_ACCIONES
    with httpx.Client(timeout=10) as http:
        r = http.post(f"{API_URL}/sendMessage", json=payload)
        if r.status_code >= 400:
            print(f"[telegram] error {r.status_code}: {r.text}")


def send_seleccion_tecnico(chat_id: int, nombres: list[str]) -> None:
    """Botones en línea (uno por técnico) para el /start."""
    teclado = {
        "inline_keyboard": [[{"text": nombre, "callback_data": f"login:{nombre}"}] for nombre in nombres]
    }
    payload = {
        "chat_id": chat_id,
        "text": "¿Quién eres? Elige tu nombre para empezar.",
        "reply_markup": teclado,
    }
    with httpx.Client(timeout=10) as http:
        r = http.post(f"{API_URL}/sendMessage", json=payload)
        if r.status_code >= 400:
            print(f"[telegram] error {r.status_code}: {r.text}")


def responder_callback(callback_query_id: str) -> None:
    """Le confirma a Telegram que ya procesamos el clic del botón (evita el 'reloj' de carga)."""
    with httpx.Client(timeout=10) as http:
        http.post(f"{API_URL}/answerCallbackQuery", json={"callback_query_id": callback_query_id})


def set_webhook(url: str) -> dict:
    with httpx.Client(timeout=10) as http:
        r = http.post(f"{API_URL}/setWebhook", json={"url": url})
        return r.json()


def descargar_foto(file_id: str) -> tuple[bytes, str]:
    """Descarga una foto de Telegram. Regresa (contenido_en_bytes, file_path)."""
    with httpx.Client(timeout=30) as http:
        r = http.get(f"{API_URL}/getFile", params={"file_id": file_id})
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        r2 = http.get(file_url)
        r2.raise_for_status()
        return r2.content, file_path
