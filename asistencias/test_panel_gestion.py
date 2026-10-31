"""Pruebas locales del nuevo panel. Nunca llama a Brevo real."""
from datetime import date
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import Profesor, JustificacionAsistencia, DiaEspecial, ReporteEnvio
from .servicio_reportes import preparar_envio, EnvioNoPermitido, semana_actual

@override_settings(BREVO_API_KEY="clave-simulada", BREVO_SENDER_EMAIL="test@example.org")
class TestGestion(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="adminpruebas", email="admin@example.org", password="ClaveDePruebaSegura#2026")
        self.prof = Profesor.objects.create(dni="12345678", nombres="Elena", apellidos="Prueba", condicion="N", email="docente@example.org", activo=True)

    def test_acceso_protegido(self):
        self.assertEqual(self.client.get(reverse("gestion_inicio")).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("gestion_inicio")).status_code, 200)

    def test_justificacion_por_rango_salta_sabado_domingo_y_especial(self):
        DiaEspecial.objects.create(fecha=date(2026,11,3), tipo="FERIADO", activo=True)
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse("gestion_justificar"), data={
            "profesor":self.prof.pk, "modo":"rango", "desde":"2026-11-02", "hasta":"2026-11-08",
            "tipo":"P", "detalle":"Permiso institucional",
        })
        self.assertEqual(respuesta.status_code, 302)
        fechas = set(JustificacionAsistencia.objects.filter(profesor=self.prof).values_list("fecha", flat=True))
        self.assertEqual(fechas, {date(2026,11,2),date(2026,11,4),date(2026,11,5),date(2026,11,6)})
        # Repetir la operación no duplica ni altera justificaciones anteriores.
        self.client.post(reverse("gestion_justificar"), data={
            "profesor":self.prof.pk,"modo":"rango", "desde":"2026-11-02", "hasta":"2026-11-08",
            "tipo":"DM", "detalle":"Cambiar motivo",
        })
        self.assertEqual(JustificacionAsistencia.objects.filter(profesor=self.prof).count(),4)
        self.assertEqual(JustificacionAsistencia.objects.get(profesor=self.prof, fecha=date(2026,11,2)).tipo,"P")

    def test_justificacion_cantidad_habiles(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse("gestion_justificar"), data={
            "profesor":self.prof.pk, "modo":"cantidad", "desde":"2026-10-30", "cantidad":3,
            "tipo":"DM", "detalle":"Descanso médico",
        })
        self.assertEqual(respuesta.status_code,302)
        fechas = list(JustificacionAsistencia.objects.filter(profesor=self.prof).order_by("fecha").values_list("fecha",flat=True))
        self.assertEqual(fechas,[date(2026,10,30),date(2026,11,2),date(2026,11,3)])

    def test_cantidad_saltea_especiales_y_completa_tres_dias(self):
        DiaEspecial.objects.create(fecha=date(2026, 11, 2), tipo="FERIADO", activo=True)
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("gestion_justificar"), data={
            "profesor": self.prof.pk, "modo": "cantidad", "desde": "2026-10-30",
            "cantidad": 3, "tipo": "DM", "detalle": "Prueba de tres días",
        })
        self.assertEqual(resp.status_code, 302)
        fechas = set(JustificacionAsistencia.objects.filter(profesor=self.prof).values_list("fecha", flat=True))
        self.assertEqual(fechas, {date(2026, 10, 30), date(2026, 11, 3), date(2026, 11, 4)})

    @patch("asistencias.servicio_reportes.call_command")
    def test_envio_semanal_no_se_duplica(self, mock_cmd):
        def simular(*args, **kwargs):
            kwargs["stdout"].write("[DONE] Enviados: 1. Bloqueados: 0. Errores: 0. Saltados (sin email): 0. Saltados (sin registros): 0.")
        mock_cmd.side_effect=simular
        lote=preparar_envio(usuario=self.admin)
        self.assertEqual(lote.enviados,1)
        self.assertEqual(lote.estado,"completado")
        self.assertEqual(lote.semana_inicio,semana_actual())
        with self.assertRaises(EnvioNoPermitido):
            preparar_envio(usuario=self.admin)
        self.assertEqual(mock_cmd.call_count,1)


class TestSimulacionYEnlaceSeguro(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.org", password="ClaveSeguraPruebas123!"
        )

    @patch("asistencias.gestion.call_command")
    def test_simulacion_admin_no_envia(self, mock_cmd):
        def simular(*args, **kwargs):
            self.assertTrue(kwargs["dry_run"])
            kwargs["stdout"].write("[DRY-RUN] OK")
        mock_cmd.side_effect = simular
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("gestion_simular"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "[DRY-RUN] OK")
        self.assertEqual(mock_cmd.call_count, 1)

    def test_enlace_antiguo_no_hace_envio_general(self):
        from django.test import override_settings
        with override_settings(REPORT_TRIGGER_TOKEN="TOKEN_EXCLUSIVO_PRUEBAS"):
            respuesta = self.client.get(reverse("cron_reporte_asistencia"), {"token": "TOKEN_EXCLUSIVO_PRUEBAS"})
        self.assertEqual(respuesta.status_code, 405)
        self.assertContains(respuesta, "panel administrativo", status_code=405)
