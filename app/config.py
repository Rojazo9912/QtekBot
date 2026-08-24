"""
Configuración estática del piloto: catálogos fijos que el bot ofrece en el
chat y datos administrativos/contractuales usados solo en la hoja "Reporte
PDF" del Google Sheet. Edítalo aquí cuando cambien los técnicos, el contrato
o el catálogo de fallas — no requiere tocar la lógica del bot.
"""

# Semilla inicial: solo se usa una vez, para crear la hoja "Técnicos" del
# Google Sheet la primera vez que corre el bot. Después de eso, la lista de
# técnicos vive en esa hoja (fuente de verdad en tiempo de ejecución) y se
# administra desde el chat con el admin (ver ADMIN_TECNICOS) usando
# /nuevo_tecnico — ya no hace falta editar este archivo ni redesplegar para
# dar de alta a alguien.
TECNICOS = ["Miguel Abraham Lopez Ortiz"]

# Datos administrativos por técnico, usados solo como semilla de la hoja
# "Técnicos" (ver TECNICOS arriba). Después de la creación inicial, cargo e
# IMSS se editan directamente en esa hoja.
TECNICOS_INFO = {
    "Miguel Abraham Lopez Ortiz": {
        "cargo": "Pendiente de definir",
        "imss": "Pendiente de definir",
    },
}

# Técnicos con permisos de administrador del bot: pueden dar de alta nuevos
# técnicos (/nuevo_tecnico) y fijar el periodo del reporte contractual
# (/reporte). A diferencia de la lista de técnicos, esto NO vive en el Sheet
# a propósito — otorgar permisos de admin es una operación sensible y poco
# frecuente, así que se edita aquí (código + redeploy) en vez de ser
# auto-servicio desde el chat.
ADMIN_TECNICOS = ["Miguel Abraham Lopez Ortiz"]

# Catálogo fijo que el bot ofrece como botones al iniciar una actividad, para
# que "Tipo de Falla" quede uniforme en el Registro de Tickets (en vez de
# texto libre distinto cada vez).
CATALOGO_TIPO_FALLA = [
    "Falla de red",
    "Revision de Leaky Feeder",
    "Hardware / Equipo dañado",
    "Software / Configuración",
    "Impresión",
    "Cuentas y accesos",
    "Mantenimiento preventivo",
    "Otro",
]

# Catálogos del PRD "Estandarización del Reporte de Tickets TI" (columnas B,
# E y R del "Registro de Tickets") — valores cerrados, el bot nunca escribe
# texto libre del usuario en estas columnas.
CATALOGO_AREA = ["Infraestructura", "Soporte"]
CATALOGO_PRIORIDAD = ["Alta", "Media", "Baja"]
CATALOGO_ESTATUS = ["Abierto", "En Proceso", "Cerrado", "Cancelado"]

# Datos fijos del contrato, para la sección "1. Información General" de
# "Reporte PDF". Edítalos si cambia el contrato, el director general o los
# representantes.
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
