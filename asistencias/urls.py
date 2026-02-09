from django.urls import path
from . import views

urlpatterns = [
    
    path("", views.registrar_asistencia, name="registrar_asistencia"),
    path("scan/", views.scan_page, name="scan_page"),
    path("api/scan/", views.api_scan_asistencia, name="api_scan_asistencia"),
    path("historial/", views.historial_asistencias, name="historial_asistencias"),
    path("reporte-excel/", views.exportar_reporte_excel, name="exportar_reporte_excel"),
    # ✅ formulario manual queda en /manual/
    #path("manual/", views.registrar_asistencia, name="registrar_asistencia"),

    #path("buscar-profesor/", views.buscar_profesor, name="buscar_profesor"),
    #path("historial/", views.historial_asistencias, name="historial_asistencias"),
    #path("reporte-excel/", views.exportar_reporte_excel, name="exportar_reporte_excel"),

    # ✅ API escáner
    #path("api/scan-asistencia/", views.api_scan_asistencia, name="api_scan_asistencia"),
]


