"""Comprobaciones del login institucional único del administrador."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class LoginAdminUnicoTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.org", password="12345678"
        )

    def test_formulario_institucional_admite_admin_y_abre_gestion(self):
        response = self.client.post(reverse("login"), {
            "username": "admin", "password": "12345678",
        })
        self.assertRedirects(response, reverse("gestion_inicio"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("gestion_inicio")).status_code, 200)

    def test_acceso_direccion_raiz_del_admin_inicia_en_gestion(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("post_login"))
        self.assertRedirects(response, reverse("gestion_inicio"), fetch_redirect_response=False)

    def test_gestion_sin_sesion_redirige_al_login_de_manhattan(self):
        response = self.client.get(reverse("gestion_inicio"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/login/?next="), response.url)

    def test_docente_no_accede_a_panel_de_gestion(self):
        user = get_user_model().objects.create_user(username="docente", password="ClaveDocenteSegura#1")
        self.client.force_login(user)
        response = self.client.get(reverse("gestion_inicio"))
        self.assertEqual(response.status_code, 302)
