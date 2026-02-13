from django.contrib import admin
from .models import Profesor, Asistencia
from .models import JustificacionAsistencia
from django.utils.html import format_html

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
    list_display = ("fecha", "profesor", "tipo", "detalle", "ver_pdf", "creado_por", "creado_en")
    list_filter = ("fecha", "tipo")
    search_fields = (
        "profesor__apellidos",
        "profesor__nombres",
        "profesor__dni",
        "profesor__codigo",
        "detalle",
    )

    readonly_fields = ("ver_pdf",)

    def ver_pdf(self, obj):
        if obj.archivo:
            return format_html('<a href="{}" target="_blank" rel="noopener">📄 Ver PDF</a>', obj.archivo.url)
        return "—"
    ver_pdf.short_description = "PDF"