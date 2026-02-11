from django.contrib import admin
from .models import Profesor, Asistencia
from .models import JustificacionAsistencia

@admin.register(Profesor)
class ProfesorAdmin(admin.ModelAdmin):
    list_display = ("dni", "apellidos", "nombres", "condicion", "email")
    search_fields = ("dni", "apellidos", "nombres", "email")
    list_filter = ("condicion",)
    ordering = ("apellidos", "nombres")


@admin.register(Asistencia)
class AsistenciaAdmin(admin.ModelAdmin):
    list_display = ("profesor", "fecha", "fecha_hora", "tipo", "registrado_por", "ip")
    search_fields = ("profesor__dni", "profesor__apellidos", "profesor__nombres")
    list_filter = ("tipo", "fecha")
    date_hierarchy = "fecha"
    ordering = ("-fecha_hora",)

@admin.register(JustificacionAsistencia)
class JustificacionAsistenciaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "profesor", "tipo", "detalle", "creado_por", "creado_en")
    list_filter = ("fecha", "tipo")
    search_fields = ("profesor__dni", "profesor__codigo", "profesor__apellidos", "profesor__nombres", "detalle")