"""Pruebas del enlace privado de correos, sin enviar mensajes reales."""
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from asistencias.views import trigger_reporte_asistencia


@override_settings(
    REPORT_TRIGGER_TOKEN="token-solo-de-pruebas",
    BREVO_API_KEY="clave-simulada",
    BREVO_SENDER_EMAIL="remitente@example.com",
)
class ReporteCorreosTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.url = "/cron/reporte-asistencia/"

    def get(self, **params):
        return trigger_reporte_asistencia(self.factory.get(self.url, data=params))

    def test_token_incorrecto_rechazado(self):
        self.assertEqual(self.get(token="incorrecto", modo="verificar").status_code, 403)

    @patch("asistencias.views.call_command")
    def test_verificar_no_hace_envios(self, cmd):
        response = self.get(token="token-solo-de-pruebas", modo="verificar")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"ok": true', response.content)
        cmd.assert_not_called()

    @patch("asistencias.management.commands.enviar_reporte_asistencia.Command._brevo_send_email")
    def test_prueba_envia_un_solo_correo_sin_reportes(self, send):
        response = self.get(token="token-solo-de-pruebas", modo="prueba", correo="prueba@example.com")
        self.assertEqual(response.status_code, 200)
        send.assert_called_once()
        args = send.call_args.args
        self.assertEqual(args[0], "prueba@example.com")
        self.assertNotIn("reporte semanal", args[2].lower())

    @patch("asistencias.management.commands.enviar_reporte_asistencia.Command._brevo_send_email")
    def test_prueba_rechaza_correo_invalido(self, send):
        response = self.get(token="token-solo-de-pruebas", modo="prueba", correo="incorrecto")
        self.assertEqual(response.status_code, 400)
        send.assert_not_called()

    @patch("asistencias.views.call_command")
    def test_simular_llama_a_dry_run(self, cmd):
        response = self.get(token="token-solo-de-pruebas", modo="simular")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(cmd.call_args.kwargs["dry_run"])

    @patch("asistencias.views.call_command")
    def test_enlace_original_bloquea_envio_masivo(self, cmd):
        response = self.get(token="token-solo-de-pruebas")
        self.assertEqual(response.status_code, 405)
        self.assertIn(b'gestion/reportes/', response.content)
        cmd.assert_not_called()

    @patch("asistencias.views.call_command")
    def test_modo_no_permitido_no_envia(self, cmd):
        response = self.get(token="token-solo-de-pruebas", modo="otro")
        self.assertEqual(response.status_code, 400)
        cmd.assert_not_called()

    @patch("asistencias.views.call_command")
    def test_simular_un_reporte_filtra_correo_y_no_envia(self, cmd):
        response = self.get(
            token="token-solo-de-pruebas", modo="reporte-simular", correo="prueba@example.com"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(cmd.call_args.kwargs["email_profesor"], "prueba@example.com")
        self.assertTrue(cmd.call_args.kwargs["dry_run"])
        self.assertEqual(cmd.call_args.kwargs["max_emails"], 1)

    @patch("asistencias.views.call_command")
    def test_reporte_real_solo_un_docente(self, cmd):
        def simulate_one_report(*args, **kwargs):
            kwargs["stdout"].write("[SEND] to=prueba@example.com\n[DONE] Enviados: 1. Bloqueados: 0. Errores: 0.\n")
        cmd.side_effect = simulate_one_report
        response = self.get(
            token="token-solo-de-pruebas", modo="reporte-prueba", correo="prueba@example.com"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(cmd.call_args.kwargs["email_profesor"], "prueba@example.com")
        self.assertFalse(cmd.call_args.kwargs["dry_run"])
        self.assertEqual(cmd.call_args.kwargs["max_emails"], 1)

    @patch("asistencias.views.call_command")
    def test_reporte_real_error_no_confirma_envio(self, cmd):
        def simulate_failure(*args, **kwargs):
            kwargs["stdout"].write("[DONE] Enviados: 0. Bloqueados: 0. Errores: 1.\n")
        cmd.side_effect = simulate_failure
        response = self.get(
            token="token-solo-de-pruebas", modo="reporte-prueba", correo="prueba@example.com"
        )
        self.assertEqual(response.status_code, 502)

    @patch("asistencias.views.call_command")
    def test_reporte_real_rechaza_correo_invalido(self, cmd):
        response = self.get(
            token="token-solo-de-pruebas", modo="reporte-prueba", correo="mal-correo"
        )
        self.assertEqual(response.status_code, 400)
        cmd.assert_not_called()


class DisenoReporteInstitucionalTests(SimpleTestCase):
    def test_plantilla_sin_marcha_blanca_y_con_tabla_compacta(self):
        from pathlib import Path
        from asistencias.management.commands import enviar_reporte_asistencia
        source = Path(enviar_reporte_asistencia.__file__).read_text(encoding="utf-8")
        self.assertNotIn("marcha blanca", source.lower())
        self.assertIn('max-width:600px', source)
        self.assertIn('table-layout:fixed', source)
        self.assertIn('Día / Fecha', source)

    def test_pruebas_tienen_asunto_unico_y_sin_logo_base64(self):
        from pathlib import Path
        from asistencias.management.commands import enviar_reporte_asistencia
        source = Path(enviar_reporte_asistencia.__file__).read_text(encoding="utf-8")
        self.assertIn("uuid.uuid4().hex[:8]", source)
        self.assertIn("if email_profesor and not dry_run:", source)
        self.assertNotIn('data:image/png;base64,', source)
