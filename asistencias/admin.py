from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html
import csv

from .models import Profesor, Asistencia, JustificacionAsistencia, LoginEvidencia, DiaEspecial

# Opcional: ocultar modelos técnicos de axes del panel principal
try:
    from axes.models import AccessAttempt, AccessFailureLog, AccessLog

    for model in (AccessAttempt, AccessFailureLog, AccessLog):
        try:
            admin.site.unregister(model)
        except admin.sites.NotRegistered:
            pass
except Exception:
    pass


# =========================================================
# CONFIG GLOBAL ADMIN
# =========================================================
admin.site.site_header = "Proyecto Manhattan"
admin.site.site_title = "Panel administrativo"
admin.site.index_title = "Administración institucional"


# =========================================================
# MIXIN CSV
# =========================================================
class ExportCsvMixin:
    filename = "export.csv"
    csv_headers = []

    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{self.filename}"'

        writer = csv.writer(response)
        if self.csv_headers:
            writer.writerow(self.csv_headers)

        for row in self.get_csv_rows(queryset):
            writer.writerow(row)

        return response

    export_as_csv.short_description = "Exportar seleccionados a CSV"

    def get_csv_rows(self, queryset):
        raise NotImplementedError("Debes implementar get_csv_rows().")


# =========================================================
# PROFESOR
# =========================================================
@admin.register(Profesor)
class ProfesorAdmin(admin.ModelAdmin):
    list_display = (
        "dni",
        "apellidos",
        "nombres",
        "condicion_badge",
        "email",
    )
    search_fields = ("dni", "apellidos", "nombres", "email")
    list_filter = ("condicion",)
    ordering = ("apellidos", "nombres")
    list_per_page = 25
    list_display_links = ("dni", "apellidos", "nombres")
    actions_on_top = True
    actions_on_bottom = True
    save_on_top = True
    show_full_result_count = False
    empty_value_display = "—"

    @admin.display(description="Condición", ordering="condicion")
    def condicion_badge(self, obj):
        valor = (obj.condicion or "").strip()
        texto = valor if valor else "Sin condición"

        color = "#2563eb"
        bg = "rgba(37,99,235,.16)"
        border = "rgba(37,99,235,.28)"

        texto_lower = texto.lower()
        if "nombr" in texto_lower or "ordin" in texto_lower:
            color = "#16a34a"
            bg = "rgba(22,163,74,.16)"
            border = "rgba(22,163,74,.28)"
        elif "contrat" in texto_lower or "temp" in texto_lower:
            color = "#ca8a04"
            bg = "rgba(202,138,4,.16)"
            border = "rgba(202,138,4,.28)"

        return format_html(
            '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
            'font-weight:700;font-size:12px;color:{};background:{};border:1px solid {};">'
            '{}'
            "</span>",
            color,
            bg,
            border,
            texto,
        )


# =========================================================
# ASISTENCIA
# =========================================================
@admin.register(Asistencia)
class AsistenciaAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = (
        "profesor",
        "fecha",
        "fecha_hora",
        "tipo_badge",
        "registrado_por",
        "ip",
    )
    search_fields = (
        "profesor__dni",
        "profesor__apellidos",
        "profesor__nombres",
        "registrado_por__username",
        "ip",
    )
    list_filter = (
        ("tipo", admin.ChoicesFieldListFilter),
        ("fecha", admin.DateFieldListFilter),
    )
    date_hierarchy = "fecha"
    ordering = ("-fecha_hora",)
    list_select_related = ("profesor", "registrado_por")
    autocomplete_fields = ("profesor", "registrado_por")
    list_per_page = 20
    list_display_links = ("profesor", "fecha_hora")
    actions = ["export_as_csv"]
    actions_on_top = True
    actions_on_bottom = True
    save_on_top = True
    show_full_result_count = False
    empty_value_display = "—"
    filename = "asistencias.csv"
    csv_headers = ["Profesor", "Fecha", "Fecha/Hora", "Tipo", "Registrado por", "IP"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("profesor", "registrado_por")

    @admin.display(description="Tipo", ordering="tipo")
    def tipo_badge(self, obj):
        tipo = (obj.tipo or "").strip()
        texto = tipo if tipo else "—"

        colores = {
            "e": ("#16a34a", "rgba(22,163,74,.16)", "rgba(22,163,74,.28)"),
            "entrada": ("#16a34a", "rgba(22,163,74,.16)", "rgba(22,163,74,.28)"),
            "s": ("#dc2626", "rgba(220,38,38,.16)", "rgba(220,38,38,.28)"),
            "salida": ("#dc2626", "rgba(220,38,38,.16)", "rgba(220,38,38,.28)"),
            "j": ("#7c3aed", "rgba(124,58,237,.16)", "rgba(124,58,237,.28)"),
            "justificación": ("#7c3aed", "rgba(124,58,237,.16)", "rgba(124,58,237,.28)"),
            "justificacion": ("#7c3aed", "rgba(124,58,237,.16)", "rgba(124,58,237,.28)"),
            "manual": ("#2563eb", "rgba(37,99,235,.16)", "rgba(37,99,235,.28)"),
        }

        color, bg, border = colores.get(
            texto.lower(),
            ("#ca8a04", "rgba(202,138,4,.16)", "rgba(202,138,4,.28)")
        )

        return format_html(
            '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
            'font-weight:700;font-size:12px;color:{};background:{};border:1px solid {};">'
            '{}'
            "</span>",
            color,
            bg,
            border,
            texto.upper(),
        )

    def get_csv_rows(self, queryset):
        queryset = queryset.select_related("profesor", "registrado_por")
        for obj in queryset:
            yield [
                str(obj.profesor),
                obj.fecha,
                obj.fecha_hora,
                obj.tipo,
                str(obj.registrado_por) if obj.registrado_por else "",
                obj.ip or "",
            ]


# =========================================================
# JUSTIFICACIÓN
# =========================================================
@admin.register(JustificacionAsistencia)
class JustificacionAsistenciaAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = (
        "fecha",
        "profesor",
        "tipo_badge",
        "detalle_resumen",
        "ver_pdf",
        "creado_por",
        "creado_en",
    )
    list_filter = (
        ("fecha", admin.DateFieldListFilter),
        ("tipo", admin.ChoicesFieldListFilter),
    )
    search_fields = (
        "profesor__apellidos",
        "profesor__nombres",
        "profesor__dni",
        "profesor__codigo",
        "detalle",
    )
    readonly_fields = ("ver_pdf",)
    list_select_related = ("profesor", "creado_por", "actualizado_por")
    autocomplete_fields = ("profesor", "creado_por", "actualizado_por")
    date_hierarchy = "fecha"
    ordering = ("-fecha", "-creado_en")
    list_per_page = 20
    list_display_links = ("fecha", "profesor")
    actions = ["export_as_csv"]
    actions_on_top = True
    actions_on_bottom = True
    save_on_top = True
    show_full_result_count = False
    empty_value_display = "—"
    filename = "justificaciones.csv"
    csv_headers = ["Fecha", "Profesor", "Tipo", "Detalle", "PDF", "Creado por", "Creado en"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "profesor", "creado_por", "actualizado_por"
        )

    @admin.display(description="Tipo", ordering="tipo")
    def tipo_badge(self, obj):
        tipo = (obj.tipo or "").strip()
        texto = tipo if tipo else "—"

        colores = {
            "dm": ("#2563eb", "rgba(37,99,235,.16)", "rgba(37,99,235,.28)"),
            "c": ("#7c3aed", "rgba(124,58,237,.16)", "rgba(124,58,237,.28)"),
            "p": ("#16a34a", "rgba(22,163,74,.16)", "rgba(22,163,74,.28)"),
            "o": ("#ca8a04", "rgba(202,138,4,.16)", "rgba(202,138,4,.28)"),
            "oficio": ("#7c3aed", "rgba(124,58,237,.16)", "rgba(124,58,237,.28)"),
            "citt": ("#16a34a", "rgba(22,163,74,.16)", "rgba(22,163,74,.28)"),
        }

        color, bg, border = colores.get(
            texto.lower(),
            ("#ca8a04", "rgba(202,138,4,.16)", "rgba(202,138,4,.28)")
        )

        try:
            texto_mostrar = obj.get_tipo_display()
        except Exception:
            texto_mostrar = texto.upper()

        return format_html(
            '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
            'font-weight:700;font-size:12px;color:{};background:{};border:1px solid {};">'
            '{}'
            "</span>",
            color,
            bg,
            border,
            texto_mostrar,
        )

    @admin.display(description="Detalle")
    def detalle_resumen(self, obj):
        detalle = (obj.detalle or "").strip()
        if not detalle:
            return "—"
        if len(detalle) <= 70:
            return detalle
        return f"{detalle[:70]}..."

    @admin.display(description="PDF")
    def ver_pdf(self, obj):
        if obj.archivo:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener" '
                'style="display:inline-block;padding:6px 12px;border-radius:10px;'
                'background:linear-gradient(135deg,#7b1e2b,#9a2534);color:#fff;'
                'text-decoration:none;font-weight:700;">📄 Ver PDF</a>',
                obj.archivo.url,
            )
        return "—"

    def get_csv_rows(self, queryset):
        queryset = queryset.select_related("profesor", "creado_por")
        for obj in queryset:
            yield [
                obj.fecha,
                str(obj.profesor),
                obj.tipo,
                obj.detalle,
                obj.archivo.url if obj.archivo else "",
                str(obj.creado_por) if obj.creado_por else "",
                obj.creado_en,
            ]


# =========================================================
# DÍAS ESPECIALES
# =========================================================
@admin.register(DiaEspecial)
class DiaEspecialAdmin(admin.ModelAdmin):
    list_display = (
        "fecha",
        "tipo_badge",
        "descripcion_resumen",
        "activo_badge",
    )
    list_filter = (
        ("fecha", admin.DateFieldListFilter),
        ("tipo", admin.ChoicesFieldListFilter),
        "activo",
    )
    search_fields = ("descripcion",)
    ordering = ("-fecha",)
    list_per_page = 20
    list_display_links = ("fecha",)
    actions_on_top = True
    actions_on_bottom = True
    save_on_top = True
    show_full_result_count = False
    empty_value_display = "—"

    @admin.display(description="Tipo", ordering="tipo")
    def tipo_badge(self, obj):
        tipo = (obj.tipo or "").strip().upper()
        texto = tipo if tipo else "—"

        colores = {
            "FERIADO": ("#b45309", "rgba(245,158,11,.16)", "rgba(245,158,11,.28)"),
            "HUELGA": ("#9a3412", "rgba(234,88,12,.16)", "rgba(234,88,12,.28)"),
            "PARO": ("#c2410c", "rgba(249,115,22,.16)", "rgba(249,115,22,.28)"),
            "SUSPENSION": ("#92400e", "rgba(245,158,11,.16)", "rgba(245,158,11,.28)"),
            "REMOTO": ("#1d4ed8", "rgba(37,99,235,.16)", "rgba(37,99,235,.28)"),
            "NO_LABORABLE": ("#475569", "rgba(100,116,139,.16)", "rgba(100,116,139,.28)"),
            "OTRO": ("#7c3aed", "rgba(124,58,237,.16)", "rgba(124,58,237,.28)"),
        }

        color, bg, border = colores.get(
            texto,
            ("#475569", "rgba(100,116,139,.16)", "rgba(100,116,139,.28)")
        )

        try:
            texto_mostrar = obj.get_tipo_display()
        except Exception:
            texto_mostrar = texto.replace("_", " ").title()

        return format_html(
            '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
            'font-weight:700;font-size:12px;color:{};background:{};border:1px solid {};">'
            '{}'
            "</span>",
            color,
            bg,
            border,
            texto_mostrar,
        )

    @admin.display(description="Descripción")
    def descripcion_resumen(self, obj):
        detalle = (obj.descripcion or "").strip()
        if not detalle:
            return "—"
        if len(detalle) <= 80:
            return detalle
        return f"{detalle[:80]}..."

    @admin.display(description="Activo", ordering="activo")
    def activo_badge(self, obj):
        if obj.activo:
            return format_html(
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'font-weight:700;font-size:12px;color:#16a34a;'
                'background:rgba(22,163,74,.16);border:1px solid rgba(22,163,74,.28);">'
                'Activo</span>'
            )
        return format_html(
            '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
            'font-weight:700;font-size:12px;color:#dc2626;'
            'background:rgba(220,38,38,.16);border:1px solid rgba(220,38,38,.28);">'
            'Inactivo</span>'
        )


# =========================================================
# EVIDENCIA DE LOGIN
# =========================================================
@admin.register(LoginEvidencia)
class LoginEvidenciaAdmin(admin.ModelAdmin):
    list_display = (
        "fecha_hora_servidor",
        "usuario",
        "username_intentado",
        "exito_badge",
        "estado_geo_badge",
        "permiso_geo_badge",
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
    list_per_page = 20
    list_select_related = ("usuario",)
    show_full_result_count = False
    empty_value_display = "—"

    fieldsets = (
        (
            "Acceso",
            {
                "fields": (
                    "usuario",
                    "username_intentado",
                    "exito",
                    "fecha_hora_servidor",
                    "fecha_hora_cliente",
                )
            },
        ),
        (
            "Geolocalización",
            {
                "fields": (
                    "estado_geo",
                    "permiso_geo",
                    "latitud",
                    "longitud",
                    "precision_m",
                    "ver_mapa_google",
                    "ver_mapa_osm",
                    "mapa_embed_html",
                )
            },
        ),
        (
            "Dispositivo / Red",
            {
                "fields": (
                    "ip",
                    "device_info",
                )
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("usuario")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def _coords_ok(self, obj):
        return obj.latitud is not None and obj.longitud is not None

    @admin.display(description="Éxito", ordering="exito")
    def exito_badge(self, obj):
        if obj.exito:
            return format_html(
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'font-weight:700;font-size:12px;color:#16a34a;'
                'background:rgba(22,163,74,.16);border:1px solid rgba(22,163,74,.28);">'
                'Correcto</span>'
            )
        return format_html(
            '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
            'font-weight:700;font-size:12px;color:#dc2626;'
            'background:rgba(220,38,38,.16);border:1px solid rgba(220,38,38,.28);">'
            'Fallido</span>'
        )

    @admin.display(description="Estado geo", ordering="estado_geo")
    def estado_geo_badge(self, obj):
        valor = (obj.estado_geo or "").strip()
        if not valor:
            return "—"

        color = "#2563eb"
        bg = "rgba(37,99,235,.16)"
        border = "rgba(37,99,235,.28)"

        if valor.lower() == "ok":
            color = "#16a34a"
            bg = "rgba(22,163,74,.16)"
            border = "rgba(22,163,74,.28)"
        elif "error" in valor.lower():
            color = "#dc2626"
            bg = "rgba(220,38,38,.16)"
            border = "rgba(220,38,38,.28)"

        return format_html(
            '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
            'font-weight:700;font-size:12px;color:{};background:{};border:1px solid {};">'
            '{}'
            "</span>",
            color,
            bg,
            border,
            valor,
        )

    @admin.display(description="Permiso geo", ordering="permiso_geo")
    def permiso_geo_badge(self, obj):
        valor = (obj.permiso_geo or "").strip()
        if not valor:
            return "—"

        color = "#2563eb"
        bg = "rgba(37,99,235,.16)"
        border = "rgba(37,99,235,.28)"

        if "granted" in valor.lower() or "permit" in valor.lower():
            color = "#16a34a"
            bg = "rgba(22,163,74,.16)"
            border = "rgba(22,163,74,.28)"
        elif "denied" in valor.lower() or "deneg" in valor.lower():
            color = "#dc2626"
            bg = "rgba(220,38,38,.16)"
            border = "rgba(220,38,38,.28)"

        return format_html(
            '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
            'font-weight:700;font-size:12px;color:{};background:{};border:1px solid {};">'
            '{}'
            "</span>",
            color,
            bg,
            border,
            valor,
        )

    @admin.display(description="Mapa (Google)")
    def ver_mapa_google(self, obj):
        if not self._coords_ok(obj):
            return "—"
        url = f"https://www.google.com/maps?q={obj.latitud},{obj.longitud}"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener" '
            'style="display:inline-block;padding:6px 12px;border-radius:10px;'
            'background:linear-gradient(135deg,#7b1e2b,#9a2534);color:#fff;'
            'text-decoration:none;font-weight:700;">🗺️ Google Maps</a>',
            url,
        )

    @admin.display(description="Mapa (OSM)")
    def ver_mapa_osm(self, obj):
        if not self._coords_ok(obj):
            return "—"
        url = (
            f"https://www.openstreetmap.org/?mlat={obj.latitud}&mlon={obj.longitud}"
            f"#map=18/{obj.latitud}/{obj.longitud}"
        )
        return format_html(
            '<a href="{}" target="_blank" rel="noopener" '
            'style="display:inline-block;padding:6px 12px;border-radius:10px;'
            'background:linear-gradient(135deg,#0f4c81,#2563eb);color:#fff;'
            'text-decoration:none;font-weight:700;">🧭 OpenStreetMap</a>',
            url,
        )

    @admin.display(description="Vista previa del mapa")
    def mapa_embed_html(self, obj):
        if not self._coords_ok(obj):
            return "—"

        lat = float(obj.latitud)
        lng = float(obj.longitud)
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
            'style="border:1px solid #d1d5db;border-radius:12px;background:#fff;" '
            'loading="lazy"></iframe>',
            src,
        )