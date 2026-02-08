from django.urls import path
from . import views

urlpatterns = [
    # Página principal del módulo: /asistencia/
    path('', views.registrar_asistencia, name='registrar_asistencia'),

    # Historial: /asistencia/historial/
    path('historial/', views.historial_asistencias, name='historial_asistencias'),

    # AJAX (opcional): /asistencia/buscar_profesor/
    path('buscar_profesor/', views.buscar_profesor, name='buscar_profesor'),

   # ✅ Un solo Excel (asistieron + faltaron)
    path('historial/excel/', views.exportar_reporte_excel, name='exportar_reporte_excel'),
]

