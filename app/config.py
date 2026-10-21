"""
Configuración estática del piloto: catálogos fijos que el bot ofrece en el
chat y datos del contrato que aparecen en el Excel exportado. Edítalo aquí
cuando cambien los técnicos semilla, los admins, el contrato o los catálogos
— no requiere tocar la lógica del bot.
"""

import os
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# El servidor corre en UTC; fechas y horas se muestran en esta zona horaria.
ZONA_HORARIA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Mexico_City"))

# Semilla inicial: estos técnicos se dan de alta en la tabla `tecnicos` la
# primera vez que corre el bot (si ya existen, no se tocan). Después de eso,
# la lista vive en la base de datos y el admin la administra desde el chat
# con /nuevo_tecnico — ya no hace falta editar este archivo ni redesplegar.
TECNICOS = ["Miguel Abraham Lopez Ortiz"]

# Datos administrativos de los técnicos semilla (ver TECNICOS arriba).
# Después de la creación inicial, se editan en Supabase (tabla `tecnicos`).
TECNICOS_INFO = {
    "Miguel Abraham Lopez Ortiz": {
        "cargo": "Pendiente de definir",
        "imss": "Pendiente de definir",
    },
}

# Técnicos con permisos de administrador del bot: pueden dar de alta nuevos
# técnicos (/nuevo_tecnico) y exportar el Excel (/reporte). A diferencia de
# la lista de técnicos, esto NO vive en la base de datos a propósito —
# otorgar permisos de admin es una operación sensible y poco frecuente, así
# que se edita aquí (código + redeploy) en vez de ser auto-servicio.
ADMIN_TECNICOS = ["Miguel Abraham Lopez Ortiz"]

# Proyectos y Sedes soportadas
CATALOGO_PROYECTOS = ["Mina San Dimas", "Proyectos Durango"]

PROYECTOS_INICIALES = [
    {"nombre": "Mina San Dimas", "tipo": "Mina", "cliente": "First Majestic"},
    {"nombre": "Proyectos Durango", "tipo": "Durango", "cliente": "Qtek Computación"},
]

# Zonas sugeridas por proyecto
ZONAS_POR_PROYECTO = {
    "Mina San Dimas": ["Nivel 10", "Nivel 11", "Nivel 12", "Planta de Beneficio", "Superficie", "Campamento"],
    "Proyectos Durango": ["Oficinas Qtek", "Soporte en Sitio", "Infraestructura Redes", "Cliente Corporativo"],
}

# Ubicaciones y Estados definidos
CATALOGO_UBICACION = ["Nivel 10", "Nivel 11", "Nivel 12", "Otra"]
CATALOGO_ESTADO_REPORTE = ["Terminado", "Pendiente", "No solucionado"]

# Contrato y Carátula para Mina (San Dimas / First Majestic)
CONTRATO_INFO_MINA = {
    "contrato_marco_no": "FMS-FM-C1665",
    "orden_compra_no": "N/A",
    "contratista": "Qtek Computación, S.A. de C.V.",
    "ubicacion_servicios": "Unidad San Dimas (Mina)",
    "responsable_reporte_qtek": "Soporte Técnico TI",
    "representante_cliente": "Erick Andrade Ovalle (First Majestic)",
    "director_general_qtek": "Leobardo Simental Rueda",
    "area_servicio": "Soporte TI Mina",
    "sub_plazo_correspondiente": "Soporte técnico correctivo y preventivo diario",
    "descripcion_sub_plazo": "Atención de tickets de soporte TI conforme a demanda del área en mina",
}

# Contrato y Carátula para Proyectos Durango
CONTRATO_INFO_DURANGO = {
    "contrato_marco_no": "DGO-PROY-LOCALES",
    "orden_compra_no": "N/A",
    "contratista": "Qtek Computación, S.A. de C.V.",
    "ubicacion_servicios": "Durango, Dgo. (Proyectos Locales)",
    "responsable_reporte_qtek": "Soporte Técnico TI",
    "representante_cliente": "Clientes / Proyectos Durango",
    "director_general_qtek": "Leobardo Simental Rueda",
    "area_servicio": "Soporte TI y Proyectos Durango",
    "sub_plazo_correspondiente": "Atención y desarrollo de proyectos locales",
    "descripcion_sub_plazo": "Servicios de soporte, infraestructura y proyectos de TI en Durango",
}

# Retrocompatibilidad
CONTRATO_INFO = CONTRATO_INFO_MINA


def obtener_info_contrato(proyecto: str | None = None) -> dict:
    """Devuelve la configuración de carátula correspondiente según el proyecto."""
    if not proyecto:
        return CONTRATO_INFO_MINA
    p_norm = proyecto.lower()
    if "durango" in p_norm:
        return CONTRATO_INFO_DURANGO
    return CONTRATO_INFO_MINA

