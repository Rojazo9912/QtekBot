"""
Estado de la conversación para la máquina de estados del Bot.
Mantiene caché en memoria de alto rendimiento y sincroniza opcionalmente
con Supabase para que las sesiones sobrevivan a reinicios de servidor.
"""
from dataclasses import dataclass, field
from typing import Optional

_estado_por_tecnico: dict[str, "EstadoTecnico"] = {}


@dataclass
class EstadoTecnico:
    nombre: str
    esperando: Optional[str] = None       # Paso actual del flujo
    folio_activo: Optional[str] = None    # Folio del reporte en edición o continuación
    borrador: dict = field(default_factory=dict)  # Datos temporales del reporte


def get_estado(tecnico: str) -> EstadoTecnico:
    """Obtiene el estado de la sesión del técnico. Si no está en memoria,
    intenta restaurarlo desde la base de datos."""
    if tecnico not in _estado_por_tecnico:
        estado = EstadoTecnico(nombre=tecnico)
        try:
            # Carga diferida de db para evitar importación circular
            from app import db
            datos_guardados = db.cargar_estado_conversacion(tecnico)
            if datos_guardados:
                estado.esperando = datos_guardados.get("esperando")
                estado.folio_activo = datos_guardados.get("folio_activo")
                estado.borrador = datos_guardados.get("borrador") or {}
        except Exception:
            pass
        _estado_por_tecnico[tecnico] = estado
    return _estado_por_tecnico[tecnico]


def persistir_estado(tecnico: str) -> None:
    """Guarda el estado actual del técnico en la base de datos."""
    if tecnico in _estado_por_tecnico:
        try:
            from app import db
            est = _estado_por_tecnico[tecnico]
            db.guardar_estado_conversacion(
                tecnico=tecnico,
                esperando=est.esperando,
                folio_activo=est.folio_activo,
                borrador=est.borrador,
            )
        except Exception:
            pass


def resetear_estado(tecnico: str) -> None:
    """Reinicia el estado en memoria y limpia la persistencia en base de datos."""
    est = get_estado(tecnico)
    est.esperando = None
    est.folio_activo = None
    est.borrador = {}
    try:
        from app import db
        db.limpiar_estado_conversacion(tecnico)
    except Exception:
        pass
