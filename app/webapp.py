"""
Web app del piloto FieldTI AI — la misma lógica de bot_logic.py, pero servida
como una página web en vez de por WhatsApp. El técnico abre un link en su
celular, elige su nombre, y escribe igual que le escribiría a un chat.

Correr localmente:
    uvicorn app.webapp:app --reload
Desplegar en Railway igual que el webhook de WhatsApp, pero con este comando
de arranque en vez del de app.main:
    uvicorn app.webapp:app --host 0.0.0.0 --port $PORT
(Puedes desplegar los dos —app.main y app.webapp— como dos servicios
separados dentro del mismo proyecto de Railway, apuntando ambos al mismo repo.)
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.bot_logic import procesar_mensaje_web

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Mismo piloto de 2-3 técnicos. Cámbialo por los nombres reales de tu equipo.
TECNICOS = ["Miguel Abraham Lopez Ortiz"]


class MensajeIn(BaseModel):
    tecnico: str
    texto: str


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/tecnicos")
def listar_tecnicos():
    return {"tecnicos": TECNICOS}


@app.post("/api/chat")
def chat(mensaje: MensajeIn):
    if mensaje.tecnico not in TECNICOS:
        return {"respuestas": ["Técnico no reconocido. Recarga la página e intenta de nuevo."]}
    respuestas = procesar_mensaje_web(mensaje.tecnico, mensaje.texto)
    return {"respuestas": respuestas}
