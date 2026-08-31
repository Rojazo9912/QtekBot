"""
Suite de pruebas para validar todas las correcciones, modo offline, flujos de administración,
reportes por departamento y exportación PDF en QtekBot.
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
    parsear_hora,
    parsear_fecha,
    extraer_horas_de_texto,
    calcular_hora_fin,
    procesar_mensaje_web,
)
from app.config import ADMIN_TECNICOS, CATALOGO_AREA, CATALOGO_PRIORIDAD, CATALOGO_TIPO_FALLA
from app.state import get_estado
from app import sheets, ai_extract, telegram_client
from fastapi.testclient import TestClient
from app.main import app


class TestOfflineTimeParsing(unittest.TestCase):
    def test_parsear_hora_formatos(self):
        self.assertEqual(parsear_hora("7:50"), "07:50:00")
        self.assertEqual(parsear_hora("07:50 am"), "07:50:00")
        self.assertEqual(parsear_hora("7:50 pm"), "19:50:00")
        self.assertEqual(parsear_hora("14:30"), "14:30:00")
        self.assertIsNotNone(parsear_hora("ahora"))

    def test_parsear_fecha_formatos(self):
        hoy = dt.datetime.now(sheets.ZONA_HORARIA).date()
        self.assertEqual(parsear_fecha("ayer"), (hoy - dt.timedelta(days=1)).isoformat())
        self.assertEqual(parsear_fecha("antier"), (hoy - dt.timedelta(days=2)).isoformat())
        self.assertEqual(parsear_fecha("2026-08-25"), "2026-08-25")
        self.assertEqual(parsear_fecha("25/08/2026"), "2026-08-25")

    def test_extraer_horas_de_texto(self):
        ini, fin = extraer_horas_de_texto("cambio de AP el 18/08/2026 a las 9 de la mañana y se termino a las 10")
        self.assertEqual(ini, "09:00:00")
        self.assertEqual(fin, "10:00:00")

    def test_calcular_hora_fin(self):
        self.assertEqual(calcular_hora_fin("07:50:00", "3 horas"), "10:50:00")
        self.assertEqual(calcular_hora_fin("07:50:00", "3h"), "10:50:00")
        self.assertEqual(calcular_hora_fin("07:50:00", "3"), "10:50:00")
        self.assertEqual(calcular_hora_fin("07:50:00", "45 min"), "08:35:00")
        self.assertEqual(calcular_hora_fin("07:50:00", "45 minutos"), "08:35:00")
        self.assertEqual(calcular_hora_fin("07:50:00", "1.5 horas"), "09:20:00")
        self.assertEqual(calcular_hora_fin("07:50:00", "1h 30m"), "09:20:00")
        self.assertEqual(calcular_hora_fin("07:50:00", "1 hora y media"), "09:20:00")


class TestBotLogic(unittest.TestCase):
    def setUp(self):
        estado = get_estado("Miguel Abraham Lopez Ortiz")
        estado.esperando = None
        estado.folio_activo = None
        estado.borrador = {}

        estado_tecnico = get_estado("TecnicoEstandar")
        estado_tecnico.esperando = None
        estado_tecnico.folio_activo = None
        estado_tecnico.borrador = {}

    def test_remover_acentos(self):
        self.assertEqual(_remover_acentos("Impresión"), "impresion")
        self.assertEqual(_remover_acentos("CONFIGURACIÓN"), "configuracion")
        self.assertEqual(_remover_acentos("  Área  "), "area")

    def test_match_catalogo_acentos_y_mayusculas(self):
        self.assertEqual(_match_catalogo("impresion", CATALOGO_TIPO_FALLA), "Impresión")
        self.assertEqual(_match_catalogo("IMPRESIÓN", CATALOGO_TIPO_FALLA), "Impresión")
        self.assertEqual(_match_catalogo("software / configuracion", CATALOGO_TIPO_FALLA), "Software / Configuración")
        self.assertEqual(_match_catalogo("soporte", CATALOGO_AREA), "Soporte")
        self.assertEqual(_match_catalogo("ALTA", CATALOGO_PRIORIDAD), "Alta")

    def test_match_catalogo_por_numero(self):
        self.assertEqual(_match_catalogo("1", CATALOGO_AREA), CATALOGO_AREA[0])
        self.assertEqual(_match_catalogo("2", CATALOGO_AREA), CATALOGO_AREA[1])
        self.assertIsNone(_match_catalogo("99", CATALOGO_AREA))

    def test_cancelar_en_cualquier_paso(self):
        estado = get_estado("Miguel Abraham Lopez Ortiz")
        estado.esperando = "area"
        estado.borrador = {"ticket": "TICK-001"}

        resp = procesar_mensaje_web("Miguel Abraham Lopez Ortiz", "cancelar")
        self.assertIn("cancelada", resp[0].lower())
        self.assertIsNone(estado.esperando)
        self.assertEqual(estado.borrador, {})

    @patch("app.sheets.start_activity", return_value="FOLIO-0001")
    @patch("app.sheets.finish_activity", return_value=True)
    def test_flujo_completo_con_duracion_offline(self, mock_finish, mock_start):
        estado = get_estado("TecnicoEstandar")

        # 1. Iniciar actividad -> Pide problema y ubicación
        procesar_mensaje_web("TecnicoEstandar", "+ Nueva actividad")
        self.assertEqual(estado.esperando, "problema_y_ubicacion")

        # 2. Responder problema y ubicación -> Pide tipo de falla
        procesar_mensaje_web("TecnicoEstandar", "Ruptura de cable de red en Rampa Elia 174")
        self.assertEqual(estado.esperando, "tipo_falla")

        # 3. Elegir tipo de falla -> Inicia la actividad en Sheets automáticamente
        procesar_mensaje_web("TecnicoEstandar", "1")
        self.assertIsNone(estado.esperando)
        self.assertEqual(estado.folio_activo, "FOLIO-0001")
        mock_start.assert_called_once()
        self.assertEqual(mock_start.call_args.kwargs.get("tipo_falla"), "Falla de red")
        self.assertEqual(mock_start.call_args.kwargs.get("area"), "Infraestructura")

        # 4. Finalizar actividad -> Pide solución y evidencia
        procesar_mensaje_web("TecnicoEstandar", "finalizar")
        self.assertEqual(estado.esperando, "solucion_y_evidencia")

        # 5. Enviar solución -> Cierra la actividad en Sheets
        procesar_mensaje_web("TecnicoEstandar", "Se empalmó el cable y se cambió amplificador")
        self.assertIsNone(estado.esperando)
        self.assertIsNone(estado.folio_activo)
        mock_finish.assert_called_once()

    @patch("app.sheets.agregar_tecnico", return_value="XYZ789")
    def test_admin_flujo_nuevo_tecnico(self, mock_agregar):
        estado = get_estado("Miguel Abraham Lopez Ortiz")

        resp = procesar_mensaje_web("Miguel Abraham Lopez Ortiz", "dar de alta a un usuario")
        self.assertEqual(estado.esperando, "admin_nombre_tecnico")
        self.assertIn("nombre completo", resp[0].lower())

        resp2 = procesar_mensaje_web("Miguel Abraham Lopez Ortiz", "Isrrael Ramírez")
        self.assertIsNone(estado.esperando)
        mock_agregar.assert_called_once_with("Isrrael Ramírez")
        self.assertIn("/start xyz789", resp2[0].lower())

    @patch("app.sheets.set_periodo_reporte")
    def test_admin_flujo_reporte_por_departamento(self, mock_set_rep):
        estado = get_estado("Miguel Abraham Lopez Ortiz")

        # 1. Iniciar reporte interactivo -> pregunta tipo
        resp = procesar_mensaje_web("Miguel Abraham Lopez Ortiz", "reporte pdf")
        self.assertEqual(estado.esperando, "admin_tipo_reporte")
        self.assertIn("tipo de reporte", resp[0].lower())

        # 2. Elegir departamento -> pregunta periodo
        resp2 = procesar_mensaje_web("Miguel Abraham Lopez Ortiz", "Infraestructura")
        self.assertEqual(estado.esperando, "admin_periodo_reporte")
        self.assertIn("periodo", resp2[0].lower())

        # 3. Elegir semana actual -> fija periodo y área
        resp3 = procesar_mensaje_web("Miguel Abraham Lopez Ortiz", "Semana actual")
        self.assertIsNone(estado.esperando)
        mock_set_rep.assert_called_once()
        self.assertEqual(mock_set_rep.call_args.kwargs.get("area"), "Infraestructura")
        self.assertIn("infraestructura", resp3[0].lower())

    @patch("app.sheets.set_periodo_reporte")
    def test_admin_flujo_reporte_3_pdfs(self, mock_set_rep):
        estado = get_estado("Miguel Abraham Lopez Ortiz")

        procesar_mensaje_web("Miguel Abraham Lopez Ortiz", "reporte pdf")
        procesar_mensaje_web("Miguel Abraham Lopez Ortiz", "Generar los 3 PDFs")
        resp = procesar_mensaje_web("Miguel Abraham Lopez Ortiz", "Semana actual")
        self.assertIsNone(estado.esperando)
        self.assertIn("los 3 pdfs", resp[0].lower())

    def test_no_admin_bloqueado(self):
        resp = procesar_mensaje_web("TecnicoEstandar", "nuevo tecnico")
        self.assertIn("no tienes permiso", resp[0].lower())

    def test_comando_ayuda(self):
        resp_admin = procesar_mensaje_web("Miguel Abraham Lopez Ortiz", "comandos")
        self.assertIn("administrador", resp_admin[0].lower())

        resp_tec = procesar_mensaje_web("TecnicoEstandar", "comandos")
        self.assertNotIn("administrador", resp_tec[0].lower())


class TestSheetsExportAndFormulas(unittest.TestCase):
    def test_formula_duracion(self):
        formula = sheets._formula_duracion(4)
        self.assertIn("OR(", formula)
        self.assertIn("J4", formula)
        self.assertIn("I4", formula)

    def test_formula_rank_periodo_con_filtro_area(self):
        formula = sheets._formula_rank_periodo(4)
        self.assertIn("$G$13", formula)
        self.assertIn("Todos", formula)

    def test_next_folio_correlativo(self):
        with patch.object(sheets, "_get_worksheet") as mock_ws:
            ws_instance = MagicMock()
            ws_instance.col_values.return_value = [
                "Folio", "Encabezado", "EJEMPLO-0001",
                "FOLIO-0001", "FOLIO-0005", "INC-9999", "FOLIO-0003",
            ]
            mock_ws.return_value = ws_instance
            folio = sheets._next_folio()
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
            sheets.set_periodo_reporte(ini, fin, area="Infraestructura")

            mock_rep_ws.update.assert_any_call([["2026-01-01"]], "C13", value_input_option="USER_ENTERED")
            mock_rep_ws.update.assert_any_call([["2026-01-07"]], "E13", value_input_option="USER_ENTERED")
            mock_rep_ws.update.assert_any_call([["Infraestructura"]], "G13", value_input_option="USER_ENTERED")

    @patch("app.sheets._load_credentials")
    @patch("app.sheets._get_worksheet")
    @patch("httpx.Client.get")
    def test_exportar_reporte_pdf(self, mock_http_get, mock_get_ws, mock_load_creds):
        mock_ws_reg = MagicMock()
        mock_sh = MagicMock()
        mock_rep_ws = MagicMock()
        mock_rep_ws.id = 12345
        mock_ws_reg.spreadsheet = mock_sh
        mock_sh.worksheet.return_value = mock_rep_ws
        mock_get_ws.return_value = mock_ws_reg

        mock_creds = MagicMock()
        mock_creds.token = "fake_token"
        mock_load_creds.return_value = mock_creds

        mock_resp = MagicMock()
        mock_resp.content = b"%PDF-1.4 test binary"
        mock_http_get.return_value = mock_resp

        pdf_bytes, filename = sheets.exportar_reporte_pdf(area="Infraestructura")
        self.assertEqual(pdf_bytes, b"%PDF-1.4 test binary")
        self.assertIn("Infraestructura", filename)


class TestTelegramClient(unittest.TestCase):
    @patch("httpx.Client.post")
    def test_send_document(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        telegram_client.send_document(123456, b"%PDF-1.4...", "Reporte.pdf", caption="Reporte listo")
        mock_post.assert_called_once()


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
            self.assertTrue(data.get("es_admin"))

    @patch("app.sheets.exportar_reporte_pdf", return_value=(b"%PDF-1.4 test content", "Reporte_Infraestructura_Test.pdf"))
    def test_descargar_reporte_pdf_endpoint(self, mock_export):
        res = self.client.get("/api/descargar-reporte-pdf?area=Infraestructura")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, b"%PDF-1.4 test content")
        self.assertEqual(res.headers["content-type"], "application/pdf")
        mock_export.assert_called_once_with(area="Infraestructura")


if __name__ == "__main__":
    unittest.main()
