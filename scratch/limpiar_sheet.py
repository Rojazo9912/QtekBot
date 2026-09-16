"""
Script de utilidad para limpiar todos los registros de prueba en la hoja 'Registro de Tickets' de Google Sheets,
dejando la hoja lista para un nuevo piloto desde la fila 4 (con el primer folio correlativo FOLIO-0001).
"""
import sys
import os

# Añadir el directorio raíz al path de Python
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from app import sheets
    print("Conectando a Google Sheets...")
    borrados = sheets.limpiar_registros_tickets()
    print(f"✅ Éxito: Se eliminaron {borrados} registros de prueba de la hoja 'Registro de Tickets'.")
    print("El consecutivo de folios ha sido reiniciado a #001 (FOLIO-0001).")
except Exception as e:
    print(f"❌ Error al limpiar Google Sheets: {e}")
