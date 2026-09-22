"""
Suite de pruebas automatizadas: flujo del PRD v1.1, acceso a datos en
Supabase (con cliente simulado), exportación a Excel y endpoints.
"""
import unittest
from unittest.mock import MagicMock, patch
import os
import datetime as dt
import io

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")

from app.bot_logic import (
    _remover_acentos,
    _normalizar_estado,
    procesar_mensaje_web,
)
from app.config import ADMIN_TECNICOS
from app.state import get_estado
from app import db, excel
from openpyxl import load_workbook
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

    @patch("app.db.crear_reporte", return_value="#001")
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

        # 7. Guardar -> Llama a db.crear_reporte y confirma con #001
        resp7 = procesar_mensaje_web("TecnicoEstandar", "Guardar")
        self.assertIsNone(estado.esperando)
        self.assertEqual(estado.borrador, {})
        mock_crear.assert_called_once_with(
            ticket="TK-9988",
            tecnico="TecnicoEstandar",
            ubicacion="Nivel 10",
            actividad="Mantenimiento a Leaky Feeder",
            estado="Terminado",
            evidencias=[],
        )
        self.assertIn("#001", resp7[0])

    @patch("app.db.agregar_tecnico", return_value="ABC123")
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

    @patch("app.db.listar_reportes_pendientes")
    @patch("app.db.actualizar_reporte_pendiente", return_value=True)
    def test_flujo_continuar_pendiente(self, mock_actualizar, mock_pendientes):
        mock_pendientes.return_value = [
            {
                "numero": "#002",
                "ticket": "TK-500",
                "ubicacion": "Nivel 11",
                "actividad": "Instalación de switch",
                "estado": "Pendiente",
                "fecha": "2026-09-15",
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

        # 4. Elegir estado Terminado -> Actualiza en la base de datos
        resp4 = procesar_mensaje_web("TecnicoEstandar", "Terminado")
        self.assertIsNone(estado.esperando)
        mock_actualizar.assert_called_once_with(
            "#002",
            tecnico="TecnicoEstandar",
            nueva_actividad="Se configuró VLAN y quedó probado",
            nuevo_estado="Terminado",
        )
        self.assertIn("actualizado", resp4[0].lower())

    @patch("app.db.listar_reportes_pendientes")
    def test_no_puede_elegir_reporte_fuera_de_sus_pendientes(self, mock_pendientes):
        mock_pendientes.return_value = [{
            "numero": "#002", "ticket": "TK-500", "ubicacion": "Nivel 11",
            "actividad": "x", "estado": "Pendiente", "fecha": "2026-09-15",
        }]
        estado = get_estado("TecnicoEstandar")
        procesar_mensaje_web("TecnicoEstandar", "Mis pendientes")
        resp = procesar_mensaje_web("TecnicoEstandar", "#007")
        self.assertEqual(estado.esperando, "seleccion_pendiente")
        self.assertIn("no está en tu lista", resp[0])

    def test_estado_invalido_vuelve_a_preguntar(self):
        estado = get_estado("TecnicoEstandar")
        estado.esperando = "estado"
        estado.borrador = {"evidencias": []}
        resp = procesar_mensaje_web("TecnicoEstandar", "más o menos")
        self.assertEqual(estado.esperando, "estado")
        self.assertIn("Elige uno de estos estados", resp[0])


class TestBotonesConEmoji(unittest.TestCase):
    """Los botones de Telegram/Web llegan con emoji (algunos con el selector
    de variación U+FE0F, ej. "✏️"); bot_logic debe reconocerlos igual."""

    def setUp(self):
        for nombre in ("Miguel Abraham Lopez Ortiz", "TecnicoEstandar"):
            estado = get_estado(nombre)
            estado.esperando = None
            estado.folio_activo = None
            estado.borrador = {}

    def test_remover_acentos_quita_emoji(self):
        self.assertEqual(_remover_acentos("✏️ Editar"), "editar")
        self.assertEqual(_remover_acentos("⏸️ Mis pendientes"), "mis pendientes")
        self.assertEqual(_remover_acentos("👤 + Nuevo técnico"), "+ nuevo tecnico")

    @patch("app.db.listar_mis_reportes", return_value=[])
    @patch("app.db.listar_reportes_pendientes", return_value=[])
    def test_todos_los_botones_del_teclado_se_reconocen(self, _pend, _rep):
        from app.telegram_client import TECLADO_ADMIN
        botones = [b["text"] for fila in TECLADO_ADMIN["keyboard"] for b in fila
                   if b["text"] != "📊 Exportar Excel"]
        for boton in botones:
            get_estado("Miguel Abraham Lopez Ortiz").esperando = None
            resp = procesar_mensaje_web("Miguel Abraham Lopez Ortiz", boton)
            self.assertNotIn("no entendí", resp[0].lower(), boton)

    def test_botones_teclado_anterior_redirigen(self):
        from app.telegram_client import normalizar_texto_boton
        self.assertEqual(normalizar_texto_boton("+ Nueva actividad"), "nuevo reporte")
        self.assertEqual(normalizar_texto_boton("✓ Finalizar"), "mis pendientes")

    def test_confirmacion_boton_editar(self):
        estado = get_estado("TecnicoEstandar")
        estado.esperando = "confirmacion"
        estado.borrador = {"ticket": "TK-1", "evidencias": []}
        procesar_mensaje_web("TecnicoEstandar", "✏️ Editar")
        self.assertEqual(estado.esperando, "ticket")

    def test_ubicacion_solo_emoji_no_elige_nivel_10(self):
        estado = get_estado("TecnicoEstandar")
        estado.esperando = "ubicacion"
        estado.borrador = {"evidencias": []}
        procesar_mensaje_web("TecnicoEstandar", "🏗️")
        self.assertEqual(estado.borrador["ubicacion"], "🏗️")


def _fila_db(id_=1, estado="Terminado", evidencias=None, tecnico="Juan"):
    return {
        "id": id_, "ticket": f"TK-{id_}", "tecnico": tecnico, "ubicacion": "Nivel 10",
        "actividad": "Cambio de AP", "estado": estado, "evidencias": evidencias or [],
        "creado": "2026-09-22T17:05:09.123456+00:00",
        "actualizado": "2026-09-22T17:05:09.123456+00:00",
    }


class TestDB(unittest.TestCase):
    def test_numero_formato_y_parseo(self):
        self.assertEqual(db.formatear_numero(3), "#003")
        self.assertEqual(db.formatear_numero(1234), "#1234")
        self.assertEqual(db.parsear_numero("#002"), 2)
        self.assertEqual(db.parsear_numero(" 15 "), 15)
        self.assertIsNone(db.parsear_numero("abc"))

    def test_fila_a_reporte_en_hora_local(self):
        r = db._reporte_desde_fila(_fila_db(id_=7, evidencias=["https://x/1.jpg"]))
        self.assertEqual(r["numero"], "#007")
        # 17:05 UTC = 11:05 en America/Mexico_City (UTC-6)
        self.assertEqual((r["fecha"], r["hora"]), ("2026-09-22", "11:05:09"))
        self.assertEqual(r["evidencias"], ["https://x/1.jpg"])

    @patch("app.db.get_client")
    def test_crear_reporte_regresa_numero_del_id(self, mock_client):
        tabla = mock_client.return_value.table.return_value
        tabla.insert.return_value.execute.return_value.data = [{"id": 42}]
        numero = db.crear_reporte("TK-1", "Juan", "Nivel 10", "x", "Terminado", ["u"])
        self.assertEqual(numero, "#042")
        self.assertEqual(tabla.insert.call_args[0][0]["evidencias"], ["u"])

    @patch("app.db.get_client")
    def test_actualizar_pendiente_ajeno_no_escribe(self, mock_client):
        tabla = mock_client.return_value.table.return_value
        consulta = tabla.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value
        consulta.execute.return_value.data = []
        ok = db.actualizar_reporte_pendiente("#003", "Otro", "avance", "Terminado")
        self.assertFalse(ok)
        tabla.update.assert_not_called()

    @patch("app.db.get_client")
    def test_reportes_en_periodo_usa_dias_locales(self, mock_client):
        tabla = mock_client.return_value.table.return_value
        consulta = tabla.select.return_value.gte.return_value.lt.return_value.order.return_value
        consulta.execute.return_value.data = [_fila_db()]
        reportes = db.reportes_en_periodo(dt.date(2026, 9, 21), dt.date(2026, 9, 27))
        self.assertEqual(len(reportes), 1)
        tabla.select.return_value.gte.assert_called_once_with("creado", "2026-09-21T00:00:00-06:00")
        tabla.select.return_value.gte.return_value.lt.assert_called_once_with("creado", "2026-09-28T00:00:00-06:00")


class TestExcel(unittest.TestCase):
    def test_genera_hojas_y_datos(self):
        reportes = [
            db._reporte_desde_fila(_fila_db(1, "Terminado", ["https://x/1.jpg", "https://x/2.jpg"])),
            db._reporte_desde_fila(_fila_db(2, "Pendiente", tecnico="Ana")),
        ]
        contenido, nombre = excel.generar_excel(reportes, dt.date(2026, 9, 21), dt.date(2026, 9, 27))
        self.assertEqual(nombre, "Reporte_Campo_2026-09-21_a_2026-09-27.xlsx")

        wb = load_workbook(io.BytesIO(contenido))
        self.assertEqual(wb.sheetnames, ["Resumen", "Reportes", "Evidencias"])
        ws = wb["Reportes"]
        self.assertEqual(ws["A2"].value, "#001")
        self.assertEqual(ws["F3"].value, "Pendiente")
        self.assertEqual(ws["G2"].value, 2)  # número de fotos
        ev = wb["Evidencias"]
        self.assertEqual(ev["D3"].value, "https://x/2.jpg")
        self.assertEqual(ev["D3"].hyperlink.target, "https://x/2.jpg")
        resumen = [c.value for fila in wb["Resumen"].iter_rows() for c in fila]
        self.assertIn("Total de reportes", resumen)
        self.assertIn("Ana", resumen)

    def test_periodo_vacio(self):
        contenido, _ = excel.generar_excel([], dt.date(2026, 1, 1), dt.date(2026, 1, 7))
        wb = load_workbook(io.BytesIO(contenido))
        self.assertEqual(wb["Reportes"].max_row, 1)


class TestFastAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "healthy"})

    @patch("app.main._tecnico_de", return_value="TecnicoEstandar")
    @patch("app.telegram_client.send_opciones")
    @patch("app.telegram_client.send_text")
    def test_telegram_webhook(self, mock_send, mock_opciones, mock_tecnico):
        res = self.client.post("/telegram-webhook", json={"message": {"chat": {"id": 12345}, "text": "Hola"}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "ok"})

    @patch("app.main._tecnico_de", return_value="TecnicoEstandar")
    @patch("app.telegram_client.descargar_archivo", return_value=(b"fakebytes", "evidencias/test.jpg"))
    @patch("app.storage.upload_evidence", return_value="https://storage/test.jpg")
    @patch("app.telegram_client.send_opciones")
    @patch("app.telegram_client.send_text")
    def test_telegram_webhook_foto(self, mock_send_text, mock_send_opciones, mock_upload, mock_download, mock_tecnico):
        estado = get_estado("TecnicoEstandar")
        estado.esperando = "evidencia"
        estado.borrador = {"evidencias": []}

        res = self.client.post(
            "/telegram-webhook",
            json={"message": {"chat": {"id": 12345}, "photo": [{"file_id": "file_123"}]}},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "ok"})
        mock_send_opciones.assert_called_once()



class TestSeguridadEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("app.main.REPORTE_ADMIN_SECRET", None)
    def test_admin_sin_secreto_configurado_rechaza(self):
        # Falla en cerrado: sin REPORTE_ADMIN_SECRET nadie entra, ni con ?secret= vacío
        for url in ["/api/exportar-excel", "/api/codigo-activacion?nombre=X"]:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 403, url)

    @patch("app.main.REPORTE_ADMIN_SECRET", "s3creto")
    def test_admin_secreto_incorrecto_rechaza(self):
        res = self.client.get("/api/codigo-activacion?secret=otro&nombre=X")
        self.assertEqual(res.status_code, 403)

    @patch("app.main.REPORTE_ADMIN_SECRET", "s3creto")
    @patch("app.db.codigo_activacion_pendiente", return_value="ABC123")
    def test_admin_secreto_correcto_query_o_header(self, _mock):
        res = self.client.get("/api/codigo-activacion?secret=s3creto&nombre=X")
        self.assertEqual(res.status_code, 200)
        res = self.client.get("/api/codigo-activacion?nombre=X", headers={"X-Admin-Secret": "s3creto"})
        self.assertEqual(res.status_code, 200)

    @patch("app.main.REPORTE_ADMIN_SECRET", "s3creto")
    @patch("app.db.reportes_en_periodo", return_value=[])
    def test_exportar_excel_con_secreto(self, mock_periodo):
        res = self.client.get("/api/exportar-excel?desde=2026-09-01&hasta=2026-09-30",
                              headers={"X-Admin-Secret": "s3creto"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("Reporte_Campo_2026-09-01_a_2026-09-30.xlsx", res.headers["content-disposition"])
        mock_periodo.assert_called_once_with(dt.date(2026, 9, 1), dt.date(2026, 9, 30))

    @patch("app.main.REPORTE_ADMIN_SECRET", "s3creto")
    def test_exportar_excel_fechas_invalidas(self):
        res = self.client.get("/api/exportar-excel?secret=s3creto&desde=2026-09-30&hasta=2026-09-01")
        self.assertEqual(res.status_code, 400)

    @patch("app.main.WEBAPP_HABILITADA", False)
    def test_webapp_deshabilitada_por_default(self):
        res = self.client.post("/api/chat", json={"tecnico": "Miguel Abraham Lopez Ortiz", "texto": "nuevo tecnico"})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.client.get("/api/tecnicos").status_code, 404)
        self.assertEqual(self.client.get("/").json()["status"], "ok")

    @patch("app.main.WEBHOOK_SECRET", "hook")
    def test_webhook_secreto_incorrecto(self):
        res = self.client.post(
            "/telegram-webhook",
            json={"message": {"chat": {"id": 1}, "text": "hola"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "otro"},
        )
        self.assertEqual(res.status_code, 403)



class TestComandoReporteTelegram(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def _mandar(self, texto):
        return self.client.post("/telegram-webhook", json={"message": {"chat": {"id": 1}, "text": texto}})

    @patch("app.main._tecnico_de", return_value="Miguel Abraham Lopez Ortiz")
    @patch("app.db.reportes_en_periodo", return_value=[])
    @patch("app.telegram_client.send_document")
    @patch("app.telegram_client.send_text")
    def test_admin_recibe_excel(self, _texto, mock_doc, mock_periodo, _tec):
        self._mandar("/reporte 2026-09-01 2026-09-15")
        mock_periodo.assert_called_once_with(dt.date(2026, 9, 1), dt.date(2026, 9, 15))
        args, kwargs = mock_doc.call_args
        self.assertTrue(args[2].endswith(".xlsx"))
        self.assertIn("spreadsheetml", kwargs["mime_type"])

    @patch("app.main._tecnico_de", return_value="Miguel Abraham Lopez Ortiz")
    @patch("app.db.reportes_en_periodo", return_value=[])
    @patch("app.telegram_client.send_document")
    @patch("app.telegram_client.send_text")
    def test_boton_exportar_excel(self, _texto, mock_doc, _periodo, _tec):
        self._mandar("📊 Exportar Excel")
        mock_doc.assert_called_once()

    @patch("app.main._tecnico_de", return_value="TecnicoEstandar")
    @patch("app.telegram_client.send_document")
    @patch("app.telegram_client.send_text")
    def test_no_admin_no_recibe_excel(self, mock_texto, mock_doc, _tec):
        self._mandar("/reporte")
        mock_doc.assert_not_called()
        self.assertIn("No tienes permiso", mock_texto.call_args[0][1])

    @patch("app.main._tecnico_de", return_value="Miguel Abraham Lopez Ortiz")
    @patch("app.db.listar_mis_reportes", return_value=[])
    @patch("app.telegram_client.send_document")
    @patch("app.telegram_client.send_text")
    def test_mis_reportes_no_es_el_comando_de_admin(self, _texto, mock_doc, mock_mis, _tec):
        self._mandar("/reportes")
        mock_doc.assert_not_called()
        mock_mis.assert_called_once()


if __name__ == "__main__":
    unittest.main()
