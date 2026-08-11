"""
Configuración estática del piloto: catálogos fijos que el bot ofrece en el
chat y datos administrativos/contractuales usados solo en el Reporte
Semanal. Edítalo aquí cuando cambien los técnicos, el contrato o el
catálogo de fallas — no requiere tocar la lógica del bot.
"""

# Mismo piloto de 2-3 técnicos. Cámbialo por los nombres reales de tu equipo.
TECNICOS = ["Miguel Abraham Lopez Ortiz"]

# Datos administrativos por técnico. Se usan solo en la tabla "Personal
# Asignado en el Periodo" del Reporte Semanal — no se le piden al técnico
# por chat. Complétalos con los datos reales de tu equipo.
TECNICOS_INFO = {
    "Miguel Abraham Lopez Ortiz": {
        "cargo": "Pendiente de definir",
        "imss": "Pendiente de definir",
    },
}

# Catálogo fijo que el bot ofrece como botones al iniciar una actividad, para
# que "Tipo de Falla" quede uniforme en el Reporte Diario (en vez de texto
# libre distinto cada vez).
CATALOGO_TIPO_FALLA = [
    "Falla de red",
    "Hardware / Equipo dañado",
    "Software / Configuración",
    "Impresión",
    "Cuentas y accesos",
    "Mantenimiento preventivo",
    "Otro",
]

CATALOGO_PRIORIDAD = ["Baja", "Media", "Alta", "Urgente"]

# Datos fijos del contrato, para la sección "1. Información General" del
# Reporte Semanal. Edítalos si cambia el contrato, el director general o los
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
