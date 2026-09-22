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

# Ubicaciones y Estados definidos en el PRD v1.1
CATALOGO_UBICACION = ["Nivel 10", "Nivel 11", "Nivel 12", "Otra"]
CATALOGO_ESTADO_REPORTE = ["Terminado", "Pendiente", "No solucionado"]

# Datos fijos del contrato, para la hoja "Resumen" del Excel exportado.
# Edítalos si cambia el contrato, el director general o los representantes.
CONTRATO_INFO = {
    "contrato_marco_no": "FMS-FM-C1665",
    "orden_compra_no": "N/A",
    "contratista": "Qtek Computación, S.A. de C.V.",
    "ubicacion_servicios": "Unidad San Dimas",
    "responsable_reporte_qtek": "Soporte Técnico TI",
    "representante_first_majestic": "Erick Andrade Ovalle",
    "director_general_qtek": "Leobardo Simental Rueda",
    "area_servicio": "Soporte TI",
    "sub_plazo_correspondiente": "Soporte técnico correctivo y preventivo diario",
    "descripcion_sub_plazo": "Atención de tickets de soporte TI conforme a demanda del área",
}
