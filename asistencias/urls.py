from django.urls import path
from . import views

urlpatterns = [
    path("scan/", views.scan_page, name="scan_page"),
    path("api/scan/", views.api_scan_asistencia, name="api_scan_asistencia"),

    path("historial/", views.historial_asistencias, name="historial_asistencias"),
    path("excel/", views.exportar_reporte_excel, name="exportar_reporte_excel"),
]

