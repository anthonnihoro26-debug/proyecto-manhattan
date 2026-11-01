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
        self.assertEqual(JustificacionAsistencia.objects.get(profesor=self.prof, fecha=date(2026,11,2)).tipo,"O")

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

class TestPantallasUnificadas(TestCase):
    def setUp(self):
        from .models import Asistencia
        self.admin = get_user_model().objects.create_superuser(
            username="admin-v9", email="admin@example.org", password="SeguraDePrueba!2026"
        )
        self.prof = Profesor.objects.create(
            dni="43218765", apellidos="DOCENTE", nombres="PRUEBA", condicion="N", activo=True
        )

    def test_todas_las_secciones_utilizan_plantillas_de_gestion(self):
        self.client.force_login(self.admin)
        for nombre in ["gestion_inicio", "gestion_profesores", "gestion_historial",
                       "gestion_justificaciones", "gestion_dias_especiales", "gestion_reportes"]:
            with self.subTest(nombre=nombre):
                res = self.client.get(reverse(nombre))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, "Administración de Asistencias")

    def test_rango_no_justifica_dia_con_asistencia_y_aparece_en_historial(self):
        from .models import Asistencia
        self.client.force_login(self.admin)
        Asistencia.objects.create(profesor=self.prof, fecha=date(2026, 11, 2), tipo="E")
        res = self.client.post(reverse("gestion_justificar"), {
            "profesor":self.prof.id, "modo":"rango", "desde":"2026-11-02",
            "hasta":"2026-11-04", "tipo":"DM", "detalle":"Prueba por rango"
        })
        self.assertEqual(res.status_code, 302)
        self.assertFalse(JustificacionAsistencia.objects.filter(profesor=self.prof, fecha=date(2026,11,2)).exists())
        self.assertEqual(JustificacionAsistencia.objects.filter(profesor=self.prof).count(), 2)
        self.assertEqual(Asistencia.objects.filter(profesor=self.prof, tipo="J").count(), 2)
        res = self.client.get(reverse("gestion_historial"), {"fecha":"2026-11-03"})
        self.assertContains(res, "Justificado")

    def test_pantalla_de_justificaciones_tiene_acceso_a_rango(self):
        self.client.force_login(self.admin)
        res = self.client.get(reverse("gestion_justificaciones"))
        self.assertContains(res, reverse("gestion_justificar"))

    @override_settings(REPORT_TRIGGER_TOKEN="secreto-de-pruebas-para-enlace")
    @patch("asistencias.gestion.enviar_todos")
    def test_enlace_de_prueba_no_dispara_envio_general(self, mock_envio):
        self.client.force_login(self.admin)
        url = "https://testserver/cron/reporte-asistencia/?token=secreto-de-pruebas-para-enlace&modo=prueba"
        res = self.client.post(reverse("gestion_envio_enlace"), {
            "confirmar": "CONFIRMAR_ENVIO", "enlace":url,
        })
        self.assertEqual(res.status_code, 302)
        mock_envio.assert_not_called()


class TestGestionSimplificada(TestCase):
    def setUp(self):
        from .models import Asistencia
        self.user = get_user_model().objects.create_superuser(
            username="pruebas-panel-simple", email="admin@ejemplo.test", password="ClaveDePruebaFuerte!2026"
        )
        self.prof = Profesor.objects.create(dni="90000001", nombres="Lucía", apellidos="Paredes", condicion="N")
        self.client.force_login(self.user)

    def test_un_dia_sin_tipo_se_registra_generico(self):
        r = self.client.post(reverse("gestion_justificar"), {
            "profesor": self.prof.pk, "modo": "un_dia", "desde": "2026-10-30",
            "detalle": "Justificación autorizada",
        })
        self.assertEqual(r.status_code, 302)
        j = JustificacionAsistencia.objects.get(profesor=self.prof)
        self.assertEqual(j.fecha, date(2026, 10, 30))
        self.assertEqual(j.tipo, "O")

    def test_no_sobrescribe_entrada_en_un_dia(self):
        from .models import Asistencia
        Asistencia.objects.create(profesor=self.prof, fecha=date(2026,10,30), tipo="E")
        self.client.post(reverse("gestion_justificar"), {
            "profesor": self.prof.pk, "modo": "un_dia", "desde": "2026-10-30",
        })
        self.assertFalse(JustificacionAsistencia.objects.filter(profesor=self.prof).exists())

    def test_filtro_por_docente_muestra_historial_de_distintos_dias(self):
        from .models import Asistencia
        Asistencia.objects.create(profesor=self.prof, fecha=date(2026,10,27), tipo="E")
        Asistencia.objects.create(profesor=self.prof, fecha=date(2026,10,29), tipo="E")
        r = self.client.get(reverse("gestion_historial"), {"modo": "docente", "q": "Paredes"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "27/10/2026")
        self.assertContains(r, "29/10/2026")

    def test_tipo_oculto_y_navegacion_cinco_opciones(self):
        r = self.client.get(reverse("gestion_justificaciones"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'name="tipo"')
        self.assertContains(r, "Cuántos días hábiles")
        self.assertContains(r, "Ayer")
        self.assertNotContains(r, "Agregar profesor</a>")
