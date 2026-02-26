from django.contrib import admin
from django.utils.html import format_html
from django.http import HttpResponse
import csv
from .models import LoginEvidencia
from .models import Profesor, Asistencia, JustificacionAsistencia


# =========================
# ✅ CONFIG GLOBAL ADMIN
# =========================
admin.site.site_header = "Panel de Asistencias"
admin.site.site_title = "Manhattan Admin"
admin.site.index_title = "Administración del sistema"


# =========================
# ✅ PROFESOR
# =========================
@admin.register(Profesor)
class ProfesorAdmin(admin.ModelAdmin):
    # ✅ título de sección (si tu modelo no tiene verbose_name)
    # (no rompe nada si ya lo tienes en models.py)
    # verbose_name = "Profesor"
    # verbose_name_plural = "Profesores"

    list_display = ("dni", "apellidos", "nombres", "condicion", "email")
    search_fields = ("dni", "apellidos", "nombres", "email")
    list_filter = ("condicion",)
    ordering = ("apellidos", "nombres")

    # ✅ mejoras
    list_per_page = 25
    list_display_links = ("dni", "apellidos", "nombres")

    # ✅ UX admin
    actions_on_top = True
    actions_on_bottom = True
    save_on_top = True
    show_full_result_count = False
    empty_value_display = "—"


# =========================
# ✅ ASISTENCIA
# =========================
@admin.register(Asistencia)
class AsistenciaAdmin(admin.ModelAdmin):
    list_display = ("profesor", "fecha", "fecha_hora", "tipo", "registrado_por", "ip")
    search_fields = ("profesor__dni", "profesor__apellidos", "profesor__nombres")
    list_filter = ("tipo", "fecha")
    date_hierarchy = "fecha"
    ordering = ("-fecha_hora",)

    # ✅ mejoras (no quitan columnas)
    list_select_related = ("profesor", "registrado_por")
    autocomplete_fields = ("profesor", "registrado_por")
    list_per_page = 50
    list_display_links = ("profesor", "fecha_hora")

    actions = ["exportar_csv_asistencias"]

    # ✅ UX admin
    actions_on_top = True
    actions_on_bottom = True
    save_on_top = True
    show_full_result_count = False
    empty_value_display = "—"

    # ✅ filtros laterales colapsables (Django 5.2+)
    list_filter = (
        ("tipo", admin.ChoicesFieldListFilter),
        ("fecha", admin.DateFieldListFilter),
    )

    def exportar_csv_asistencias(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="asistencias.csv"'
        writer = csv.writer(response)
        writer.writerow(["Profesor", "Fecha", "Fecha/Hora", "Tipo", "Registrado por", "IP"])
        for obj in queryset.select_related("profesor", "registrado_por"):
            writer.writerow([
                str(obj.profesor),
                obj.fecha,
                obj.fecha_hora,
                obj.tipo,
                str(obj.registrado_por) if obj.registrado_por else "",
                obj.ip or "",
            ])
        return response

    exportar_csv_asistencias.short_description = "Exportar asistencias seleccionadas a CSV"


# =========================
# ✅ JUSTIFICACIÓN
# =========================
@admin.register(JustificacionAsistencia)
class JustificacionAsistenciaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "profesor", "tipo", "detalle", "ver_pdf", "creado_por", "creado_en")
    list_filter = ("fecha", "tipo")
    search_fields = ("profesor__apellidos", "profesor__nombres", "profesor__dni", "profesor__codigo", "detalle")
    readonly_fields = ("ver_pdf",)

    # ✅ mejoras (no quitan columnas)
    list_select_related = ("profesor", "creado_por", "actualizado_por")
    autocomplete_fields = ("profesor", "creado_por", "actualizado_por")
    date_hierarchy = "fecha"
    list_per_page = 50
    list_display_links = ("fecha", "profesor")

    actions = ["exportar_csv_justificaciones"]

    # ✅ UX admin
    actions_on_top = True
    actions_on_bottom = True
    save_on_top = True
    show_full_result_count = False
    empty_value_display = "—"

    # ✅ filtros con mejor UI
    list_filter = (
        ("fecha", admin.DateFieldListFilter),
        ("tipo", admin.ChoicesFieldListFilter),
    )

    def ver_pdf(self, obj):
        if obj.archivo:
            return format_html(
                '<a class="button" href="{}" target="_blank" rel="noopener">📄 Ver PDF</a>',
                obj.archivo.url
            )
        return "—"
    ver_pdf.short_description = "PDF"

    def exportar_csv_justificaciones(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="justificaciones.csv"'
        writer = csv.writer(response)
        writer.writerow(["Fecha", "Profesor", "Tipo", "Detalle", "PDF", "Creado por", "Creado en"])
        for obj in queryset.select_related("profesor", "creado_por"):
            writer.writerow([
                obj.fecha,
                str(obj.profesor),
                obj.tipo,
                obj.detalle,
                obj.archivo.url if obj.archivo else "",
                str(obj.creado_por) if obj.creado_por else "",
                obj.creado_en,
            ])
        return response

    exportar_csv_justificaciones.short_description = "Exportar justificaciones seleccionadas a CSV"

@admin.register(LoginEvidencia)
class LoginEvidenciaAdmin(admin.ModelAdmin):
    list_display = (
        "fecha_hora_servidor",
        "usuario",
        "username_intentado",
        "exito",
        "estado_geo",
        "permiso_geo",
        "latitud",
        "longitud",
        "precision_m",
        "ip",
        "ver_mapa_google",
        "ver_mapa_osm",
    )
    list_filter = ("exito", "estado_geo", "permiso_geo", "fecha_hora_servidor")
    search_fields = ("username_intentado", "usuario__username", "ip", "device_info")
    readonly_fields = (
        "usuario",
        "username_intentado",
        "exito",
        "fecha_hora_servidor",
        "fecha_hora_cliente",
        "latitud",
        "longitud",
        "precision_m",
        "estado_geo",
        "permiso_geo",
        "device_info",
        "ip",
        "ver_mapa_google",
        "ver_mapa_osm",
        "mapa_embed_html",
    )
    ordering = ("-fecha_hora_servidor",)

    fieldsets = (
        ("Acceso", {
            "fields": ("usuario", "username_intentado", "exito", "fecha_hora_servidor", "fecha_hora_cliente")
        }),
        ("Geolocalización", {
            "fields": (
                "estado_geo", "permiso_geo",
                "latitud", "longitud", "precision_m",
                "ver_mapa_google", "ver_mapa_osm",
                "mapa_embed_html",
            )
        }),
        ("Dispositivo / Red", {
            "fields": ("ip", "device_info")
        }),
    )

    def has_add_permission(self, request):
        return False

    def _coords_ok(self, obj):
        return obj.latitud is not None and obj.longitud is not None

    def ver_mapa_google(self, obj):
        if not self._coords_ok(obj):
            return "—"
        url = f"https://www.google.com/maps?q={obj.latitud},{obj.longitud}"
        return format_html(
            '<a class="button" href="{}" target="_blank" rel="noopener">🗺️ Google Maps</a>',
            url
        )
    ver_mapa_google.short_description = "Mapa (Google)"

    def ver_mapa_osm(self, obj):
        if not self._coords_ok(obj):
            return "—"
        # Zoom 18 aprox
        url = f"https://www.openstreetmap.org/?mlat={obj.latitud}&mlon={obj.longitud}#map=18/{obj.latitud}/{obj.longitud}"
        return format_html(
            '<a class="button" href="{}" target="_blank" rel="noopener">🧭 OpenStreetMap</a>',
            url
        )
    ver_mapa_osm.short_description = "Mapa (OSM)"

    def mapa_embed_html(self, obj):
        """
        Vista previa simple embebida (OpenStreetMap + leaflet static via iframe OSM export).
        Si no hay coords, no muestra nada.
        """
        if not self._coords_ok(obj):
            return "—"

        lat = float(obj.latitud)
        lng = float(obj.longitud)

        # bbox pequeño alrededor del punto
        delta = 0.003
        left = lng - delta
        right = lng + delta
        bottom = lat - delta
        top = lat + delta

        src = (
            "https://www.openstreetmap.org/export/embed.html"
            f"?bbox={left}%2C{bottom}%2C{right}%2C{top}"
            f"&layer=mapnik&marker={lat}%2C{lng}"
        )
        return format_html(
            '<iframe src="{}" width="100%" height="320" '
            'style="border:1px solid #ddd;border-radius:8px;" loading="lazy"></iframe>',
            src
        )
    mapa_embed_html.short_description = "Vista previa del mapa"