"""
Estado de la conversación por número de WhatsApp.

LIMITACIÓN DELIBERADA DEL PILOTO: esto vive en memoria del proceso. Si Railway
reinicia el servicio, se pierde el estado de "en qué paso de la conversación
va cada técnico" (aunque las actividades YA GUARDADAS en Sheets no se pierden).
Para 2-3 técnicos en un piloto de unas semanas es un riesgo aceptable. Si el
piloto se aprueba y pasa a producción, esto debe moverse a Supabase/Redis, tal
como ya lo contempla el PRD original (no es opcional en producción).
"""
from dataclasses import dataclass, field
from typing import Optional

_estado_por_tecnico: dict[str, "EstadoTecnico"] = {}


@dataclass
class EstadoTecnico:
    nombre: str
    esperando: Optional[str] = None       # "ticket" | "problema" | "solucion" | "receptor" | "confirmacion"
    folio_activo: Optional[str] = None    # folio/ticket de la actividad EN CURSO
    borrador: dict = field(default_factory=dict)  # datos que se van juntando entre mensajes


def get_estado(tecnico: str) -> EstadoTecnico:
    if tecnico not in _estado_por_tecnico:
        _estado_por_tecnico[tecnico] = EstadoTecnico(nombre=tecnico)
    return _estado_por_tecnico[tecnico]
