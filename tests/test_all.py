"""
Suite de pruebas para validar todas las correcciones en el proyecto QtekBot.
"""
import unittest
from unittest.mock import MagicMock, patch
import os
import datetime as dt

# Asegurar variables de prueba mínimas
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("GOOGLE_SHEET_ID", "test_sheet_id")
os.environ.setdefault("OPENAI_API_KEY", "test_openai_key")

from app.bot_logic import (
    _match_catalogo,
    _remover_acentos,
    procesar_mensaje_web,
)
from app.config import CATALOGO_AREA, CATALOGO_PRIORIDAD, CATALOGO_TIPO_FALLA
from app.state import get_estado
from app import sheets, ai_extract, telegram_client
from fastapi.testclient import TestClient
from app.main import app


class TestBotLogic(unittest.TestCase):
    def setUp(self):
        # Reset estado para el técnico de prueba
        estado = get_estado("TecnicoPrueba")
        estado.esperando = None
        estado.folio_activo = None
        estado.borrador = {}

    def test_remover_acentos(self):
        self.assertEqual(_remover_acentos("Impresión"), "impresion")
        self.assertEqual(_remover_acentos("CONFIGURACIÓN"), "configuracion")
        self.assertEqual(_remover_acentos("  Área  "), "area")

    def test_match_catalogo_acentos_y_mayusculas(self):
        # Con y sin acentos
        self.assertEqual(_match_catalogo("impresion", CATALOGO_TIPO_FALLA), "Impresión")
        self.assertEqual(_match_catalogo("IMPRESIÓN", CATALOGO_TIPO_FALLA), "Impresión")
        self.assertEqual(_match_catalogo("software / configuracion", CATALOGO_TIPO_FALLA), "Software / Configuración")
        self.assertEqual(_match_catalogo("soporte", CATALOGO_AREA), "Soporte")
        self.assertEqual(_match_catalogo("ALTA", CATALOGO_PRIORIDAD), "Alta")

    def test_match_catalogo_por_numero(self):
        # Selección por número 1-indexado
        self.assertEqual(_match_catalogo("1", CATALOGO_AREA), CATALOGO_AREA[0])
        self.assertEqual(_match_catalogo("2", CATALOGO_AREA), CATALOGO_AREA[1])
        self.assertIsNone(_match_catalogo("99", CATALOGO_AREA))

    def test_cancelar_en_cualquier_paso(self):
        estado = get_estado("TecnicoPrueba")
        estado.esperando = "area"
        estado.borrador = {"ticket": "TICK-001"}

        resp = procesar_mensaje_web("TecnicoPrueba", "cancelar")
        self.assertIn("cancelada", resp[0].lower())
        self.assertIsNone(estado.esperando)
        self.assertEqual(estado.borrador, {})

    def test_comandos_directos_sin_ia(self):
        # Comandos estándar responden directamente
        resp = procesar_mensaje_web("TecnicoPrueba", "+ Nueva actividad")
        self.assertIn("ticket", resp[0].lower())

        estado = get_estado("TecnicoPrueba")
        self.assertEqual(estado.esperando, "ticket_si_no")

        # Responder que no tiene ticket
        resp = procesar_mensaje_web("TecnicoPrueba", "no")
        self.assertEqual(estado.esperando, "area")


class TestSheetsFormulas(unittest.TestCase):
    def test_formula_duracion(self):
        formula = sheets._formula_duracion(4)
        self.assertIn("OR(", formula)
        self.assertIn("J4", formula)
        self.assertIn("I4", formula)

    def test_next_folio_correlativo(self):
        with patch.object(sheets, "_get_worksheet") as mock_ws:
            ws_instance = MagicMock()
            # Simulamos columna con títulos, encabezados, ejemplo y folios existentes
            ws_instance.col_values.return_value = [
                "Folio", "Encabezado", "EJEMPLO-0001",
                "FOLIO-0001", "FOLIO-0005", "INC-9999", "FOLIO-0003",
            ]
            mock_ws.return_value = ws_instance
            folio = sheets._next_folio()
            # El siguiente número mayor a 5 debe ser FOLIO-0006
            self.assertEqual(folio, "FOLIO-0006")

    def test_set_periodo_reporte_argumentos(self):
        with patch.object(sheets, "_get_worksheet") as mock_ws:
            ws_registro = MagicMock()
            mock_sh = MagicMock()
            mock_rep_ws = MagicMock()
            ws_registro.spreadsheet = mock_sh
            mock_sh.worksheet.return_value = mock_rep_ws
            mock_ws.return_value = ws_registro

            ini = dt.date(2026, 1, 1)
            fin = dt.date(2026, 1, 7)
            sheets.set_periodo_reporte(ini, fin)

            # Verificar que ws.update recibe (values, range_name)
            mock_rep_ws.update.assert_any_call([["2026-01-01"]], "C13", value_input_option="USER_ENTERED")
            mock_rep_ws.update.assert_any_call([["2026-01-07"]], "E13", value_input_option="USER_ENTERED")


class TestAIExtract(unittest.TestCase):
    def test_interpretar_mensaje_fallback_sin_crash(self):
        with patch("app.ai_extract._get_client", return_value=None):
            res = ai_extract.interpretar_mensaje("quiero abrir ticket")
            self.assertEqual(res["intencion"], "desconocido")
            self.assertEqual(res["confianza"], "baja")


class TestFastAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "healthy"})

    def test_api_chat(self):
        with patch.object(sheets, "listar_tecnicos", return_value=["Miguel Abraham Lopez Ortiz"]):
            res = self.client.post("/api/chat", json={
                "tecnico": "Miguel Abraham Lopez Ortiz",
                "texto": "mis actividades",
            })
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("respuestas", data)
            self.assertIn("opciones", data)


if __name__ == "__main__":
    unittest.main()
