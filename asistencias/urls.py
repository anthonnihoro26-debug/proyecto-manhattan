from django.urls import path
from . import views

urlpatterns = [
    # ✅ SCAN (solo grupo SCANNER)
    path("scan/", views.scan_page, name="scan_page"),
    path("api/scan/", views.api_scan_asistencia, name="api_scan_asistencia"),

    # ✅ HISTORIAL (solo grupo HISTORIAL)
    path("historial/", views.historial_asistencias, name="historial_asistencias"),
    path("excel/", views.exportar_reporte_excel, name="exportar_reporte_excel"),

    # ✅ Registro manual por DNI (solo HISTORIAL)
    path("manual/", views.registro_manual, name="registro_manual"),

    # ✅ Justificaciones (solo grupo JUSTIFICACIONES)
    path("justificaciones/", views.panel_justificaciones, name="panel_justificaciones"),
    path("justificaciones/set/", views.set_justificacion, name="set_justificacion"),
]
