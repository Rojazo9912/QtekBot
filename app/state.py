"""
Estado de la conversación en memoria para la máquina de estados del Bot.
Soporta el flujo de 5 pasos del PRD v1.1.
"""
from dataclasses import dataclass, field
from typing import Optional

_estado_por_tecnico: dict[str, "EstadoTecnico"] = {}


@dataclass
class EstadoTecnico:
    nombre: str
    esperando: Optional[str] = None       # "ticket" | "ubicacion" | "actividad" | "estado" | "evidencia" | "confirmacion" | "continuar_..."
    folio_activo: Optional[str] = None    # Folio/Número del reporte activo o en edición
    borrador: dict = field(default_factory=dict)  # {"ticket", "ubicacion", "actividad", "estado", "evidencias": []}


def get_estado(tecnico: str) -> EstadoTecnico:
    if tecnico not in _estado_por_tecnico:
        _estado_por_tecnico[tecnico] = EstadoTecnico(nombre=tecnico)
    return _estado_por_tecnico[tecnico]
