"""
Suite de pruebas automatizadas para validar el flujo del PRD v1.1 y el esquema de Google Sheets (10 columnas).
"""
import unittest
from unittest.mock import MagicMock, patch
import os
import datetime as dt

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("GOOGLE_SHEET_ID", "test_sheet_id")

from app.bot_logic import (
    _remover_acentos,
    _normalizar_estado,
    procesar_mensaje_web,
)
from app.config import ADMIN_TECNICOS
from app.state import get_estado
from app import sheets
from fastapi.testclient import TestClient
from app.main import app


class TestBotLogicPRDv11(unittest.TestCase):
    def setUp(self):
        estado_admin = get_estado("Miguel Abraham Lopez Ortiz")
        estado_admin.esperando = None
        estado_admin.folio_activo = None
        estado_admin.borrador = {}

        estado_tec = get_estado("TecnicoEstandar")
        estado_tec.esperando = None
        estado_tec.folio_activo = None
        estado_tec.borrador = {}

    def test_remover_acentos(self):
        self.assertEqual(_remover_acentos("Nivel 10"), "nivel 10")
        self.assertEqual(_remover_acentos("Términado"), "terminado")

    def test_normalizar_estado(self):
        self.assertEqual(_normalizar_estado("✅ Terminado"), "Terminado")
        self.assertEqual(_normalizar_estado("⏸️ Pendiente"), "Pendiente")
        self.assertEqual(_normalizar_estado("❌ No solucionado"), "No solucionado")

    def test_cancelar_en_cualquier_paso(self):
        estado = get_estado("TecnicoEstandar")
        estado.esperando = "ubicacion"
        estado.borrador = {"ticket": "TK-123"}

        resp = procesar_mensaje_web("TecnicoEstandar", "cancelar")
        self.assertIn("cancelada", resp[0].lower())
        self.assertIsNone(estado.esperando)
        self.assertEqual(estado.borrador, {})

    @patch("app.sheets.crear_reporte", return_value="#001")
    def test_flujo_completo_5_pasos(self, mock_crear):
        estado = get_estado("TecnicoEstandar")

        # 1. Inicio -> Pide ticket
        resp1 = procesar_mensaje_web("TecnicoEstandar", "➕ Nuevo reporte")
        self.assertEqual(estado.esperando, "ticket")
        self.assertIn("paso 1", resp1[0].lower())

        # 2. Enviar Ticket -> Pide Ubicación
        resp2 = procesar_mensaje_web("TecnicoEstandar", "TK-9988")
        self.assertEqual(estado.esperando, "ubicacion")
        self.assertEqual(estado.borrador["ticket"], "TK-9988")
        self.assertIn("paso 2", resp2[0].lower())

        # 3. Enviar Ubicación -> Pide Actividad
        resp3 = procesar_mensaje_web("TecnicoEstandar", "Nivel 10")
        self.assertEqual(estado.esperando, "actividad")
        self.assertEqual(estado.borrador["ubicacion"], "Nivel 10")
        self.assertIn("paso 3", resp3[0].lower())

        # 4. Enviar Actividad -> Pide Estado
        resp4 = procesar_mensaje_web("TecnicoEstandar", "Mantenimiento a Leaky Feeder")
        self.assertEqual(estado.esperando, "estado")
        self.assertEqual(estado.borrador["actividad"], "Mantenimiento a Leaky Feeder")
        self.assertIn("paso 4", resp4[0].lower())

        # 5. Enviar Estado -> Pide Evidencia
        resp5 = procesar_mensaje_web("TecnicoEstandar", "Terminado")
        self.assertEqual(estado.esperando, "evidencia")
        self.assertEqual(estado.borrador["estado"], "Terminado")
        self.assertIn("paso 5", resp5[0].lower())

        # 6. Omitir Evidencia -> Pide Confirmación
        resp6 = procesar_mensaje_web("TecnicoEstandar", "Omitir")
        self.assertEqual(estado.esperando, "confirmacion")
        self.assertIn("confirmación", resp6[0].lower())

        # 7. Guardar -> Llama a sheets.crear_reporte y confirma con #001
        resp7 = procesar_mensaje_web("TecnicoEstandar", "Guardar")
        self.assertIsNone(estado.esperando)
        self.assertEqual(estado.borrador, {})
        mock_crear.assert_called_once_with(
            ticket="TK-9988",
            tecnico="TecnicoEstandar",
            ubicacion="Nivel 10",
            actividad="Mantenimiento a Leaky Feeder",
            estado="Terminado",
            evidencias="",
        )
        self.assertIn("#001", resp7[0])

    @patch("app.sheets.agregar_tecnico", return_value="ABC123")
    def test_admin_flujo_nuevo_tecnico(self, mock_agregar):
        estado = get_estado("Miguel Abraham Lopez Ortiz")

        resp = procesar_mensaje_web("Miguel Abraham Lopez Ortiz", "dar de alta")
        self.assertEqual(estado.esperando, "admin_nombre_tecnico")

        resp2 = procesar_mensaje_web("Miguel Abraham Lopez Ortiz", "Juan Pérez")
        self.assertIsNone(estado.esperando)
        mock_agregar.assert_called_once_with("Juan Pérez")
        self.assertIn("/start abc123", resp2[0].lower())

    def test_no_admin_bloqueado(self):
        resp = procesar_mensaje_web("TecnicoEstandar", "nuevo tecnico")
        self.assertIn("no tienes permisos", resp[0].lower())

    @patch("app.sheets.listar_reportes_pendientes")
    @patch("app.sheets.actualizar_reporte_pendiente", return_value=True)
    def test_flujo_continuar_pendiente(self, mock_actualizar, mock_pendientes):
        mock_pendientes.return_value = [
            {
                "Numero": "#002",
                "Ticket": "TK-500",
                "Ubicacion": "Nivel 11",
                "Actividad": "Instalación de switch",
                "Estado": "Pendiente",
                "Fecha": "2026-09-15",
                "Hora": "10:00:00",
            }
        ]

        estado = get_estado("TecnicoEstandar")

        # 1. Consultar mis pendientes
        resp1 = procesar_mensaje_web("TecnicoEstandar", "Mis pendientes")
        self.assertEqual(estado.esperando, "seleccion_pendiente")
        self.assertIn("#002", resp1[0])

        # 2. Seleccionar reporte #002 -> Pide descripción
        resp2 = procesar_mensaje_web("TecnicoEstandar", "002")
        self.assertEqual(estado.esperando, "continuar_pendiente_actividad")
        self.assertEqual(estado.folio_activo, "#002")

        # 3. Enviar descripción -> Pide nuevo estado
        resp3 = procesar_mensaje_web("TecnicoEstandar", "Se configuró VLAN y quedó probado")
        self.assertEqual(estado.esperando, "continuar_pendiente_estado")

        # 4. Elegir estado Terminado -> Actualiza en sheets
        resp4 = procesar_mensaje_web("TecnicoEstandar", "Terminado")
        self.assertIsNone(estado.esperando)
        mock_actualizar.assert_called_once_with(
            "#002",
            nueva_actividad="Se configuró VLAN y quedó probado",
            nuevo_estado="Terminado",
        )
        self.assertIn("actualizado", resp4[0].lower())


class TestSheetsConsecutivo(unittest.TestCase):
    def test_consecutivo_numero(self):
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = [
            ["Reportes de Campo TI"],
            ["Numero", "Ticket", "Tecnico"],
            ["#001", "TK-100", "Juan"],
            ["#002", "TK-101", "Pedro"],
        ]
        siguiente = sheets._next_numero_reporte(mock_ws)
        self.assertEqual(siguiente, "#003")


class TestFastAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "healthy"})


if __name__ == "__main__":
    unittest.main()
