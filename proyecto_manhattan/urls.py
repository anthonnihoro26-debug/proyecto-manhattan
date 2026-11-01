"""
URL configuration for proyecto_manhattan project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

from asistencias import views as asist_views
from asistencias import gestion as gestion_views

urlpatterns = [
    path("gestion/", gestion_views.inicio, name="gestion_inicio"),
    path("gestion/profesores/", gestion_views.profesores, name="gestion_profesores"),
    path("gestion/profesores/nuevo/", gestion_views.profesor_formulario, name="gestion_profesor_nuevo"),
    path("gestion/profesores/<int:pk>/editar/", gestion_views.profesor_formulario, name="gestion_profesor_editar"),
    path("gestion/historial/", gestion_views.historial, name="gestion_historial"),
    path("gestion/justificaciones/", gestion_views.justificaciones, name="gestion_justificaciones"),
    path("gestion/dias-especiales/", gestion_views.dias_especiales, name="gestion_dias_especiales"),
    path("gestion/dias-especiales/nuevo/", gestion_views.dia_especial_formulario, name="gestion_dia_nuevo"),
    path("gestion/dias-especiales/<int:pk>/editar/", gestion_views.dia_especial_formulario, name="gestion_dia_editar"),
    path("gestion/reportes/historial/", gestion_views.historial_reportes, name="gestion_envios_historial"),
    path("gestion/reportes/desde-enlace/", gestion_views.enviar_desde_enlace, name="gestion_envio_enlace"),
    path("gestion/justificar/", gestion_views.justificar_rango, name="gestion_justificar"),
    path("gestion/reportes/", gestion_views.reportes, name="gestion_reportes"),
    path("gestion/reportes/simular/", gestion_views.simular_reportes, name="gestion_simular"),
    path("gestion/reportes/enviar/", gestion_views.enviar_todos, name="gestion_enviar"),
    # Cerrar sesión administrativa y volver al login ÚNICO de Manhattan
    path(
        "admin/logout/",
        auth_views.LogoutView.as_view(next_page="/login/"),
        name="admin_logout",
    ),

    # Admin
    path("admin/", admin.site.urls),

    # Login personalizado con geocerca
    path("login/", asist_views.login_view_geocerca, name="login"),

    # Logout del sistema principal
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),

    # Redirección post-login
    path("", asist_views.post_login_redirect, name="post_login"),

    # Cron privado
    path(
        "cron/reporte-asistencia/",
        asist_views.trigger_reporte_asistencia,
        name="cron_reporte_asistencia",
    ),

    # App
    path("asistencia/", include("asistencias.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)