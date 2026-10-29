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

from app.config import (
    TECNICOS,
    TECNICOS_INFO,
    ADMIN_TECNICOS,
    ZONA_HORARIA,
    CATALOGO_PROYECTOS,
    PROYECTOS_INICIALES,
    ZONAS_POR_PROYECTO,
    CATALOGO_UBICACION,
)
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
        "proyecto": fila.get("proyecto") or "Mina San Dimas",
        "departamento": fila.get("departamento") or "Infraestructura",
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


def separar_nombre_y_proyecto(texto: str, proyecto_explicito: str = "") -> tuple[str, str]:
    """Separa 'Nombre | Proyecto' o detecta si el usuario escribió el proyecto
    al final del nombre sin usar '|' (ej. 'Miguel Lopez Mina San Dimas')."""
    limpio = " ".join(texto.split())
    if proyecto_explicito.strip():
        return limpio, proyecto_explicito.strip()
    if "|" in limpio:
        partes = [p.strip() for p in limpio.split("|", 1)]
        return partes[0], (partes[1] if len(partes) > 1 and partes[1] else "Ambos")

    proyectos_conocidos = list(CATALOGO_PROYECTOS)
    try:
        for p in listar_nombres_proyectos():
            if p not in proyectos_conocidos:
                proyectos_conocidos.append(p)
    except Exception:
        pass

    lower = limpio.lower()
    for proy in sorted(proyectos_conocidos, key=len, reverse=True):
        proy_l = proy.lower()
        if lower.endswith(" " + proy_l):
            nombre_sin_proy = limpio[: -(len(proy) + 1)].strip(" -|")
            if nombre_sin_proy:
                return nombre_sin_proy, proy
    return limpio, "Ambos"


def agregar_tecnico(
    nombre: str, cargo: str = "Técnico de Campo", imss: str = "N/A", proyecto: str = "Ambos",
) -> Optional[str]:
    """Da de alta un técnico y regresa su código de activación. None si el
    nombre viene vacío o ya existe (sin distinguir mayúsculas)."""
    nombre_limpio, proy_detectado = separar_nombre_y_proyecto(
        nombre, proyecto if proyecto and proyecto != "Ambos" else ""
    )
    if not nombre_limpio:
        return None
    if nombre_limpio.lower() in {n.lower() for n in listar_tecnicos()}:
        return None
    codigo = _generar_codigo_activacion()
    datos = {
        "nombre": nombre_limpio, "cargo": cargo, "imss": imss, "codigo_activacion": codigo,
    }
    proy_final = proyecto.strip() if (proyecto and proyecto != "Ambos") else proy_detectado
    if proy_final:
        datos["proyecto"] = proy_final
    _tabla_tecnicos().insert(datos).execute()
    return codigo


def asignar_proyecto_tecnico(nombre: str, proyecto: str) -> bool:
    """Asigna o actualiza el proyecto/sede de un técnico (Mina San Dimas, Proyectos Durango, Ambos)."""
    try:
        res = _tabla_tecnicos().update({"proyecto": proyecto.strip()}).ilike("nombre", nombre.strip()).execute()
        return bool(res.data)
    except Exception as e:
        print(f"[db] error asignando proyecto a técnico {nombre}: {e}")
        return False


def obtener_proyectos_de_tecnico(tecnico: str) -> list[str]:
    """Obtiene los proyectos que tiene autorizados un técnico para reportar.
    Si tiene 'Ambos', 'Todos' o no está definido, retorna todos los proyectos activos."""
    todos = listar_nombres_proyectos()
    try:
        res = _tabla_tecnicos().select("proyecto").ilike("nombre", tecnico.strip()).limit(1).execute()
        if res.data:
            proy_str = (res.data[0].get("proyecto") or "").strip()
            if not proy_str or proy_str.lower() in ("ambos", "todos", "all"):
                return todos
            partes = [p.strip().lower() for p in proy_str.split(",") if p.strip()]
            coincidentes = [t for t in todos if any(p in t.lower() or t.lower() in p for p in partes)]
            if coincidentes:
                return coincidentes
    except Exception as e:
        print(f"[db] error obteniendo proyectos de técnico {tecnico}: {e}")
    return todos


def listar_tecnicos_con_info() -> list[dict]:
    """Lista técnicos con su cargo, proyecto asignado y estado de activación."""
    try:
        res = _tabla_tecnicos().select("nombre, cargo, proyecto, es_admin, chat_id").order("nombre").execute()
        return [
            {
                "nombre": f["nombre"],
                "cargo": f.get("cargo", "Técnico de Campo"),
                "proyecto": f.get("proyecto") or "Ambos",
                "es_admin": bool(f.get("es_admin")),
                "activo": f.get("chat_id") is not None,
            }
            for f in res.data
        ]
    except Exception:
        return [
            {"nombre": n, "cargo": "Técnico de Campo", "proyecto": "Ambos", "es_admin": es_admin(n), "activo": True}
            for n in listar_tecnicos()
        ]


def codigo_activacion_pendiente(nombre: str) -> Optional[str]:
    res = (
        _tabla_tecnicos().select("codigo_activacion")
        .eq("nombre", nombre).limit(1).execute()
    )
    return res.data[0]["codigo_activacion"] if res.data else None


def activar_tecnico_por_codigo(codigo: str, chat_id: int) -> Optional[str]:
    """Vincula el chat al técnico dueño del código y consume el código, en un
    solo UPDATE (dos personas no pueden usar el mismo código). Si el chat_id
    estaba vinculado a un registro anterior, lo libera primero."""
    codigo = codigo.strip().upper()
    if not codigo:
        return None
    tabla = _tabla_tecnicos()
    try:
        prev = tabla.select("nombre").eq("codigo_activacion", codigo).limit(1).execute()
        if prev.data:
            tabla.update({"chat_id": None}).eq("chat_id", chat_id).neq("codigo_activacion", codigo).execute()
    except Exception:
        pass
    res = (
        tabla
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
    departamento: str | list[str] = "Infraestructura",
    evidencias: Optional[list[str]] = None,
    proyecto: str = "Mina San Dimas",
) -> str:
    """Guarda un reporte nuevo y regresa su número (#001, #002…)."""
    if isinstance(departamento, list) and evidencias is None:
        evidencias = departamento
        departamento_str = "Infraestructura"
    elif isinstance(departamento, str):
        departamento_str = departamento.strip()
    else:
        departamento_str = "Infraestructura"

    proyecto_str = (proyecto or "Mina San Dimas").strip()

    payload = {
        "ticket": ticket.strip(),
        "tecnico": tecnico.strip(),
        "proyecto": proyecto_str,
        "ubicacion": ubicacion.strip(),
        "actividad": actividad.strip(),
        "estado": estado.strip(),
        "departamento": departamento_str,
        "evidencias": evidencias or [],
        "creado_por": tecnico.strip(),
    }

    client = get_client()

    try:
        proy_res = client.table("proyectos").select("id").ilike("nombre", proyecto_str).limit(1).execute()
        if proy_res.data:
            payload["proyecto_id"] = proy_res.data[0]["id"]
    except Exception:
        pass

    try:
        dep_res = client.table("departamentos").select("id").ilike("nombre", departamento_str).limit(1).execute()
        if dep_res.data:
            payload["departamento_id"] = dep_res.data[0]["id"]
    except Exception:
        pass

    try:
        zona_res = client.table("zonas").select("id").ilike("nombre", ubicacion.strip()).limit(1).execute()
        if zona_res.data:
            payload["zona_id"] = zona_res.data[0]["id"]
    except Exception:
        pass

    try:
        res = client.table("reportes").insert(payload).execute()
    except Exception as e:
        err_str = str(e)
        if "23503" in err_str or "reportes_tecnico_fkey" in err_str or "tecnicos" in err_str:
            nombre_limpio, proy_det = separar_nombre_y_proyecto(tecnico.strip())
            tecnico_resuelto = nombre_limpio or tecnico.strip()
            try:
                exist = client.table("tecnicos").select("nombre").ilike("nombre", tecnico_resuelto).limit(1).execute()
                if exist.data:
                    tecnico_resuelto = exist.data[0]["nombre"]
                else:
                    client.table("tecnicos").upsert(
                        {
                            "nombre": tecnico_resuelto,
                            "cargo": "Técnico de Campo",
                            "imss": "N/A",
                            "proyecto": proy_det if proy_det != "Ambos" else proyecto_str,
                        },
                        on_conflict="nombre",
                    ).execute()
            except Exception as e_tec:
                print(f"[db] aviso auto-registrando técnico '{tecnico_resuelto}': {e_tec}")
            payload["tecnico"] = tecnico_resuelto
            payload["creado_por"] = tecnico_resuelto
            res = client.table("reportes").insert(payload).execute()
        else:
            raise
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


def reportes_en_periodo(desde: dt.date, hasta: dt.date, proyecto: Optional[str] = None) -> list[dict]:
    """Reportes creados entre `desde` y `hasta` (ambos inclusive, en fechas
    locales), opcionalmente filtrados por proyecto."""
    inicio = dt.datetime.combine(desde, dt.time.min, tzinfo=ZONA_HORARIA)
    fin = dt.datetime.combine(hasta + dt.timedelta(days=1), dt.time.min, tzinfo=ZONA_HORARIA)
    consulta = (
        get_client().table("reportes").select("*")
        .gte("creado", inicio.isoformat()).lt("creado", fin.isoformat())
    )
    if proyecto and proyecto.strip() and proyecto.strip().lower() not in ("todos", "general", "todas"):
        consulta = consulta.ilike("proyecto", f"%{proyecto.strip()}%")
    res = consulta.order("id").execute()
    return [_reporte_desde_fila(f) for f in res.data]


# --- Catálogos dinámicos: Proyectos ---

def listar_proyectos() -> list[dict]:
    try:
        res = get_client().table("proyectos").select("*").eq("activo", True).order("id").execute()
        if res.data:
            return res.data
    except Exception:
        pass
    return [dict(p, id=i) for i, p in enumerate(PROYECTOS_INICIALES, 1)]


def listar_nombres_proyectos() -> list[str]:
    proyectos = listar_proyectos()
    return [p["nombre"] for p in proyectos]


def agregar_proyecto(nombre: str, tipo: str = "Durango", cliente: str = "") -> bool:
    nombre = " ".join(nombre.split())
    tipo_norm = "Mina" if "mina" in tipo.lower() else "Durango"
    if not nombre or len(nombre) > 120:
        return False
    try:
        existente = get_client().table("proyectos").select("id").ilike("nombre", nombre).limit(1).execute()
        if existente.data:
            return False
        get_client().table("proyectos").insert({
            "nombre": nombre,
            "tipo": tipo_norm,
            "cliente": cliente.strip(),
            "activo": True,
        }).execute()
        return True
    except Exception as e:
        print(f"[db] error agregando proyecto {nombre}: {e}")
        return False


# --- Catálogos dinámicos: Departamentos y Zonas ---

def listar_departamentos() -> list[str]:
    res = get_client().table("departamentos").select("nombre").eq("activo", True).order("nombre").execute()
    return [f["nombre"] for f in res.data]


def agregar_departamento(nombre: str) -> bool:
    nombre = " ".join(nombre.split())
    if not nombre or len(nombre) > 100:
        return False
    existente = get_client().table("departamentos").select("id").ilike("nombre", nombre).limit(1).execute()
    if existente.data:
        return False
    get_client().table("departamentos").insert({"nombre": nombre}).execute()
    return True


def listar_zonas(proyecto: Optional[str] = None) -> list[str]:
    try:
        consulta = get_client().table("zonas").select("nombre, proyecto").eq("activo", True)
        if proyecto:
            res = consulta.ilike("proyecto", f"%{proyecto.strip()}%").order("nombre").execute()
        else:
            res = consulta.order("nombre").execute()
        if res.data:
            return [f["nombre"] for f in res.data]
    except Exception:
        pass

    if proyecto:
        for p_key, zonas in ZONAS_POR_PROYECTO.items():
            if p_key.lower() in proyecto.lower() or proyecto.lower() in p_key.lower():
                return list(zonas)
    return list(CATALOGO_UBICACION)


def asegurar_zona(nombre: str, proyecto: Optional[str] = None) -> str:
    nombre = " ".join(nombre.split())
    if not nombre or len(nombre) > 160:
        raise ValueError("Nombre de zona inválido")
    try:
        existente = get_client().table("zonas").select("nombre").ilike("nombre", nombre).limit(1).execute()
        if existente.data:
            return existente.data[0]["nombre"]
        payload = {"nombre": nombre}
        if proyecto:
            payload["proyecto"] = proyecto.strip()
            try:
                p_res = get_client().table("proyectos").select("id").ilike("nombre", proyecto.strip()).limit(1).execute()
                if p_res.data:
                    payload["proyecto_id"] = p_res.data[0]["id"]
            except Exception:
                pass
        res = get_client().table("zonas").insert(payload).execute()
        return res.data[0]["nombre"]
    except Exception:
        return nombre


# --- Administradores Dinámicos ---

def es_admin(tecnico: str) -> bool:
    """Verifica si un técnico tiene privilegios de administrador.
    Revisa la configuración estática ADMIN_TECNICOS y la columna es_admin en Supabase."""
    if not tecnico:
        return False
    if tecnico in ADMIN_TECNICOS:
        return True
    try:
        res = _tabla_tecnicos().select("es_admin").eq("nombre", tecnico).limit(1).execute()
        if res.data and res.data[0].get("es_admin"):
            return True
    except Exception:
        pass
    return False


def asignar_admin(nombre: str, es_admin: bool = True) -> bool:
    """Otorga o revoca permisos de administrador a un técnico en la base de datos."""
    nombre = " ".join(nombre.split())
    if not nombre:
        return False
    try:
        res = _tabla_tecnicos().update({"es_admin": es_admin}).eq("nombre", nombre).execute()
        return bool(res.data)
    except Exception as e:
        print(f"[db] error asignando admin a {nombre}: {e}")
        return False


# --- Consultas y Búsquedas Avanzadas ---

def buscar_reporte(termino: str, limite: int = 5) -> list[dict]:
    """Busca reportes por número (#001), ID o por número de ticket."""
    termino_limpio = termino.strip()
    if not termino_limpio:
        return []

    id_num = parsear_numero(termino_limpio)
    client = get_client()

    try:
        if id_num is not None:
            res = client.table("reportes").select("*").eq("id", id_num).limit(1).execute()
            if res.data:
                return [_reporte_desde_fila(f) for f in res.data]

        res = client.table("reportes").select("*").ilike("ticket", f"%{termino_limpio}%").order("id", desc=True).limit(limite).execute()
        return [_reporte_desde_fila(f) for f in res.data]
    except Exception as e:
        print(f"[db] error buscando reporte con término '{termino_limpio}': {e}")
        return []


def listar_reportes_por_zona(zona: str, limite: int = 10) -> list[dict]:
    """Obtiene los reportes más recientes registrados en una zona específica."""
    zona_limpia = zona.strip()
    if not zona_limpia:
        return []
    try:
        res = (
            get_client().table("reportes").select("*")
            .ilike("ubicacion", f"%{zona_limpia}%")
            .order("id", desc=True).limit(limite).execute()
        )
        return [_reporte_desde_fila(f) for f in reversed(res.data)]
    except Exception as e:
        print(f"[db] error listando reportes por zona '{zona_limpia}': {e}")
        return []


# --- Persistencia de Sesión Conversacional ---

def guardar_estado_conversacion(
    tecnico: str,
    esperando: Optional[str],
    folio_activo: Optional[str],
    borrador: dict,
) -> bool:
    """Persiste el borrador y paso actual de la conversación en Supabase."""
    if not tecnico:
        return False
    try:
        get_client().table("sesiones_estado").upsert({
            "tecnico": tecnico,
            "esperando": esperando,
            "folio_activo": folio_activo,
            "borrador": borrador or {},
            "actualizado": _ahora().isoformat(),
        }, on_conflict="tecnico").execute()
        return True
    except Exception:
        # Falla silenciosamente si la tabla sesiones_estado aún no ha sido migrada
        return False


def cargar_estado_conversacion(tecnico: str) -> Optional[dict]:
    """Carga el estado persistido del técnico si existe en Supabase."""
    if not tecnico:
        return None
    try:
        res = get_client().table("sesiones_estado").select("*").eq("tecnico", tecnico).limit(1).execute()
        if res.data:
            fila = res.data[0]
            return {
                "esperando": fila.get("esperando"),
                "folio_activo": fila.get("folio_activo"),
                "borrador": fila.get("borrador") or {},
            }
    except Exception:
        pass
    return None


def limpiar_estado_conversacion(tecnico: str) -> bool:
    """Elimina el estado guardado del técnico en Supabase al terminar o cancelar."""
    if not tecnico:
        return False
    try:
        get_client().table("sesiones_estado").delete().eq("tecnico", tecnico).execute()
        return True
    except Exception:
        return False