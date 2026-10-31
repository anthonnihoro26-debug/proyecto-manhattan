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
    def test_enlace_original_conserva_envio(self, cmd):
        response = self.get(token="token-solo-de-pruebas")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("dry_run", cmd.call_args.kwargs)

    @patch("asistencias.views.call_command")
    def test_modo_no_permitido_no_envia(self, cmd):
        response = self.get(token="token-solo-de-pruebas", modo="otro")
        self.assertEqual(response.status_code, 400)
        cmd.assert_not_called()
