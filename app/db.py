"""
Acceso a datos en Supabase Postgres: tablas `tecnicos` y `reportes` (ver
supabase/schema.sql). Es la fuente de verdad del bot; el Excel se genera a
partir de aquí cuando el admin lo pide (ver app/excel.py).

Los reportes se devuelven como dicts con llaves en minúsculas:
numero, ticket, tecnico, ubicacion, actividad, estado, evidencias (lista),
fecha, hora y actualizado (texto en la zona horaria local).
"""
import datetime as dt
import secrets
import string
from typing import Optional

from app.config import TECNICOS, TECNICOS_INFO, ZONA_HORARIA
from app.supabase_client import get_client

_ALFABETO_CODIGO = string.ascii_uppercase + string.digits
_semilla_lista = False


def _ahora() -> dt.datetime:
    return dt.datetime.now(ZONA_HORARIA)


def _generar_codigo_activacion() -> str:
    return "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(6))


def formatear_numero(id_reporte: int) -> str:
    return f"#{id_reporte:03d}"


def parsear_numero(numero: str) -> Optional[int]:
    """"#002", "002" o "2" → 2. None si no es un número."""
    limpio = numero.replace("#", "").strip()
    return int(limpio) if limpio.isdigit() else None


def _a_local(ts: str) -> dt.datetime:
    """Timestamp ISO de Postgres (UTC) → datetime en la zona horaria local."""
    return dt.datetime.fromisoformat(ts).astimezone(ZONA_HORARIA)


def _reporte_desde_fila(fila: dict) -> dict:
    creado = _a_local(fila["creado"])
    return {
        "numero": formatear_numero(fila["id"]),
        "ticket": fila["ticket"],
        "tecnico": fila["tecnico"],
        "ubicacion": fila["ubicacion"],
        "actividad": fila["actividad"],
        "estado": fila["estado"],
        "evidencias": fila.get("evidencias") or [],
        "fecha": creado.strftime("%Y-%m-%d"),
        "hora": creado.strftime("%H:%M:%S"),
        "actualizado": _a_local(fila["actualizado"]).strftime("%Y-%m-%d %H:%M:%S"),
    }


# --- Técnicos ---

def _asegurar_semilla() -> None:
    """Da de alta a los técnicos semilla de config.TECNICOS la primera vez
    (si ya existen, no toca nada). Su código de activación se recupera con
    /api/codigo-activacion."""
    global _semilla_lista
    if _semilla_lista:
        return
    filas = [
        {
            "nombre": nombre,
            "cargo": TECNICOS_INFO.get(nombre, {}).get("cargo", "Técnico de Campo"),
            "imss": TECNICOS_INFO.get(nombre, {}).get("imss", "N/A"),
            "codigo_activacion": _generar_codigo_activacion(),
        }
        for nombre in TECNICOS
    ]
    if filas:
        get_client().table("tecnicos").upsert(
            filas, on_conflict="nombre", ignore_duplicates=True
        ).execute()
    _semilla_lista = True


def _tabla_tecnicos():
    _asegurar_semilla()
    return get_client().table("tecnicos")


def listar_tecnicos() -> list[str]:
    res = _tabla_tecnicos().select("nombre").order("nombre").execute()
    return [f["nombre"] for f in res.data]


def agregar_tecnico(
    nombre: str, cargo: str = "Técnico de Campo", imss: str = "N/A",
) -> Optional[str]:
    """Da de alta un técnico y regresa su código de activación. None si el
    nombre viene vacío o ya existe (sin distinguir mayúsculas)."""
    nombre = " ".join(nombre.split())
    if not nombre:
        return None
    if nombre.lower() in {n.lower() for n in listar_tecnicos()}:
        return None
    codigo = _generar_codigo_activacion()
    _tabla_tecnicos().insert({
        "nombre": nombre, "cargo": cargo, "imss": imss, "codigo_activacion": codigo,
    }).execute()
    return codigo


def codigo_activacion_pendiente(nombre: str) -> Optional[str]:
    res = (
        _tabla_tecnicos().select("codigo_activacion")
        .eq("nombre", nombre).limit(1).execute()
    )
    return res.data[0]["codigo_activacion"] if res.data else None


def activar_tecnico_por_codigo(codigo: str, chat_id: int) -> Optional[str]:
    """Vincula el chat al técnico dueño del código y consume el código, en un
    solo UPDATE (dos personas no pueden usar el mismo código)."""
    codigo = codigo.strip().upper()
    if not codigo:
        return None
    res = (
        _tabla_tecnicos()
        .update({"chat_id": chat_id, "codigo_activacion": None})
        .eq("codigo_activacion", codigo)
        .execute()
    )
    return res.data[0]["nombre"] if res.data else None


def tecnico_por_chat_id(chat_id: int) -> Optional[str]:
    res = _tabla_tecnicos().select("nombre").eq("chat_id", chat_id).limit(1).execute()
    return res.data[0]["nombre"] if res.data else None


# --- Reportes ---

def crear_reporte(
    ticket: str,
    tecnico: str,
    ubicacion: str,
    actividad: str,
    estado: str,
    evidencias: Optional[list[str]] = None,
) -> str:
    """Guarda un reporte nuevo y regresa su número (#001, #002…)."""
    res = get_client().table("reportes").insert({
        "ticket": ticket.strip(),
        "tecnico": tecnico.strip(),
        "ubicacion": ubicacion.strip(),
        "actividad": actividad.strip(),
        "estado": estado.strip(),
        "evidencias": evidencias or [],
    }).execute()
    return formatear_numero(res.data[0]["id"])


def listar_reportes_pendientes(tecnico: str) -> list[dict]:
    res = (
        get_client().table("reportes").select("*")
        .eq("tecnico", tecnico).eq("estado", "Pendiente")
        .order("id").execute()
    )
    return [_reporte_desde_fila(f) for f in res.data]


def listar_mis_reportes(tecnico: str, limite: int = 10) -> list[dict]:
    """Últimos `limite` reportes del técnico, del más viejo al más nuevo."""
    res = (
        get_client().table("reportes").select("*")
        .eq("tecnico", tecnico).order("id", desc=True).limit(limite).execute()
    )
    return [_reporte_desde_fila(f) for f in reversed(res.data)]


def actualizar_reporte_pendiente(
    numero: str, tecnico: str, nueva_actividad: str, nuevo_estado: str,
) -> bool:
    """Anexa una actualización con marca de tiempo a la Actividad y cambia el
    Estado. Solo el técnico dueño puede actualizar su reporte, y solo si
    sigue Pendiente. False si no existe o no cumple eso."""
    id_reporte = parsear_numero(numero)
    if id_reporte is None:
        return False
    tabla = get_client().table("reportes")
    res = (
        tabla.select("actividad").eq("id", id_reporte)
        .eq("tecnico", tecnico).eq("estado", "Pendiente").limit(1).execute()
    )
    if not res.data:
        return False

    ahora = _ahora()
    actividad = res.data[0]["actividad"] or ""
    nueva = nueva_actividad.strip()
    if nueva:
        actividad = f"{actividad}\n{ahora.strftime('[%Y-%m-%d %H:%M]')} {nueva}".strip()
    tabla.update({
        "actividad": actividad,
        "estado": nuevo_estado.strip(),
        "actualizado": ahora.isoformat(),
    }).eq("id", id_reporte).execute()
    return True


def reportes_en_periodo(desde: dt.date, hasta: dt.date) -> list[dict]:
    """Reportes creados entre `desde` y `hasta` (ambos inclusive, en fechas
    locales), en orden de número."""
    inicio = dt.datetime.combine(desde, dt.time.min, tzinfo=ZONA_HORARIA)
    fin = dt.datetime.combine(hasta + dt.timedelta(days=1), dt.time.min, tzinfo=ZONA_HORARIA)
    res = (
        get_client().table("reportes").select("*")
        .gte("creado", inicio.isoformat()).lt("creado", fin.isoformat())
        .order("id").execute()
    )
    return [_reporte_desde_fila(f) for f in res.data]
