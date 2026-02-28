from django.db import models
from django.utils import timezone
from django.conf import settings


class Profesor(models.Model):
    codigo = models.CharField("Código", max_length=20, blank=True, null=True)
    dni = models.CharField("DNI", max_length=8, unique=True)
    apellidos = models.CharField("Apellidos", max_length=120)
    nombres = models.CharField("Nombres", max_length=120)
    condicion = models.CharField("Condición", max_length=20)

    # ✅ correo para enviar reportes
    email = models.EmailField("Correo", blank=True, null=True)

    @property
    def nombre_completo(self):
        ap = (self.apellidos or "").strip()
        nom = (self.nombres or "").strip()
        return f"{ap} {nom}".strip() or "Profesor(a)"

    def __str__(self):
        return f"{self.apellidos} {self.nombres}"

    class Meta:
        verbose_name = "Profesor"
        verbose_name_plural = "Profesores"
        ordering = ["apellidos", "nombres"]


class Asistencia(models.Model):
    TIPOS = (
        ("E", "Entrada"),
        ("J", "Justificación"),  # ✅ SOLO ENTRADA Y JUSTIFICACIÓN
    )

    # ✅ mismos motivos que tu JustificacionAsistencia (2 letras)
    MOTIVOS = (
        ("DM", "Descanso médico"),
        ("C", "Comisión / Encargo"),
        ("P", "Permiso"),
        ("O", "Otro"),
    )

    profesor = models.ForeignKey("Profesor", on_delete=models.CASCADE, verbose_name="Profesor")

    # ✅ Día “normalizado”
    fecha = models.DateField("Fecha", db_index=True, default=timezone.localdate)

    # ✅ Fecha/hora exacta del registro (escaneo / registro manual / justificación)
    fecha_hora = models.DateTimeField("Fecha y hora", default=timezone.now, db_index=True)

    # ✅ Entrada / justificación
    tipo = models.CharField("Tipo", max_length=1, choices=TIPOS, default="E")

    # ✅ Solo si tipo="J"
    motivo = models.CharField("Motivo", max_length=2, choices=MOTIVOS, blank=True, default="")
    detalle = models.CharField("Detalle", max_length=255, blank=True, default="")

    # ✅ Auditoría
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        verbose_name="Registrado por"
    )
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("User agent", max_length=255, blank=True, default="")

    class Meta:
        verbose_name = "Asistencia"
        verbose_name_plural = "Asistencias"
        constraints = [
            # ✅ NO permite 2 entradas/2 justificaciones el mismo día
            models.UniqueConstraint(fields=["profesor", "fecha", "tipo"], name="uniq_profesor_fecha_tipo"),
        ]
        indexes = [
            models.Index(fields=["profesor", "fecha"]),
        ]
        ordering = ["-fecha_hora"]

    # =========================
    # ✅ Helpers (profesional)
    # =========================
    @property
    def es_justificacion(self) -> bool:
        return self.tipo == "J"

    @property
    def tipo_label_pro(self) -> str:
        if self.tipo == "E":
            return "ENTRADA"
        if self.tipo == "J":
            return "JUSTIFICACIÓN"
        return str(self.tipo or "").strip() or "REGISTRO"

    @property
    def motivo_label(self) -> str:
        try:
            return self.get_motivo_display()
        except Exception:
            return (self.motivo or "").strip()

    def resumen_pro(self) -> str:
        """
        ✅ Texto profesional para reportes:
        - ENTRADA
        - JUSTIFICACIÓN (Descanso médico) - detalle...
        """
        if self.tipo == "E":
            return "ENTRADA"

        if self.tipo == "J":
            mot = self.motivo_label or "Sin motivo"
            det = (self.detalle or "").strip()
            if det:
                return f"JUSTIFICACIÓN ({mot}) - {det}"
            return f"JUSTIFICACIÓN ({mot})"

        return self.tipo_label_pro

    def __str__(self):
        if self.tipo == "J":
            return f"{self.profesor} - JUSTIFICADO({self.motivo}) - {self.fecha:%d/%m/%Y}"
        return f"{self.profesor} - ENTRADA - {self.fecha_hora:%d/%m/%Y %H:%M}"


# =========================================================
# ✅ JUSTIFICACIONES (Descanso Médico / Permiso / etc.)
# Marcan AUSENCIA como "JUSTIFICADO" para una fecha
# =========================================================
class JustificacionAsistencia(models.Model):
    TIPO_CHOICES = [
        ("DM", "Descanso médico"),
        ("C", "Comisión / Encargo"),
        ("P", "Permiso"),
        ("O", "Otro"),
    ]

    profesor = models.ForeignKey(
        "Profesor",
        on_delete=models.CASCADE,
        related_name="justificaciones",
        verbose_name="Profesor"
    )
    fecha = models.DateField("Fecha", db_index=True)

    tipo = models.CharField("Tipo", max_length=2, choices=TIPO_CHOICES, default="DM")
    detalle = models.CharField("Detalle", max_length=255, blank=True, default="")

    # ✅ PDF de sustento (descanso médico, permiso, etc.)
    archivo = models.FileField(
        "Archivo (PDF)",
        upload_to="justificaciones/%Y/%m/",
        null=True,
        blank=True,
        max_length=500,  # ✅ importante (evita varchar(100) cuando la ruta es larga)
    )

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="justificaciones_creadas",
        verbose_name="Creado por"
    )
    creado_en = models.DateTimeField("Creado en", auto_now_add=True)

    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="justificaciones_actualizadas",
        verbose_name="Actualizado por"
    )
    actualizado_en = models.DateTimeField("Actualizado en", auto_now=True)

    class Meta:
        verbose_name = "Justificación"
        verbose_name_plural = "Justificaciones"
        constraints = [
            models.UniqueConstraint(
                fields=["profesor", "fecha"],
                name="uniq_justificacion_profesor_fecha"
            )
        ]
        indexes = [
            models.Index(fields=["fecha", "profesor"]),
        ]
        ordering = ["-fecha", "profesor__apellidos", "profesor__nombres"]

    # =========================
    # ✅ Helpers (profesional)
    # =========================
    @property
    def tipo_label(self) -> str:
        try:
            return self.get_tipo_display()
        except Exception:
            return (self.tipo or "").strip()

    @property
    def archivo_url(self) -> str:
        """
        Devuelve una URL utilizable del archivo de justificación (PDF), soportando:
        - Cloudinary raw/upload
        - Cloudinary image/upload (corrige a raw/upload si el archivo es PDF)
        - URLs locales /media/...
        - URLs absolutas http(s)
        """
        try:
            if not self.archivo:
                return ""

            # nombre guardado en DB (ej: justificaciones/2026/02/archivo.pdf)
            nombre = str(getattr(self.archivo, "name", "") or "").strip()
            nombre_lower = nombre.lower()

            # url que genera el storage
            url = str(getattr(self.archivo, "url", "") or "").strip()
            if not url:
                return ""

            # 1) Si ya es URL absoluta http/https, la usamos (con corrección Cloudinary si aplica)
            if url.startswith("http://") or url.startswith("https://"):
                if (
                    nombre_lower.endswith(".pdf")
                    and "res.cloudinary.com" in url
                    and "/image/upload/" in url
                ):
                    url = url.replace("/image/upload/", "/raw/upload/")
                return url

            # 2) Si es local (/media/...) o ruta relativa, devolver tal cual
            #    Django normalmente resuelve self.archivo.url como /media/...
            if url.startswith("/"):
                return url

            # 3) Si por alguna razón vino una ruta relativa sin slash, la normalizamos
            #    (ej: media/justificaciones/... -> /media/justificaciones/...)
            return f"/{url.lstrip('/')}"

        except Exception:
            return ""

    @property
    def tiene_pdf(self) -> bool:
        try:
            if not self.archivo:
                return False
            nombre = str(getattr(self.archivo, "name", "") or "").lower()
            return nombre.endswith(".pdf")
        except Exception:
            return False

    def __str__(self):
        return f"{self.profesor} - {self.fecha} ({self.tipo})"

class LoginEvidencia(models.Model):
    """
    Auditoría de intentos de login y logins exitosos.
    Guarda geolocalización (si el navegador la envía), precisión, dispositivo y estado.
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="login_evidencias",
    )
    username_intentado = models.CharField(max_length=150, blank=True, default="")
    exito = models.BooleanField(default=False)

    fecha_hora_servidor = models.DateTimeField(auto_now_add=True)
    fecha_hora_cliente = models.CharField(max_length=60, blank=True, default="")

    latitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitud = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    precision_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    estado_geo = models.CharField(max_length=50, blank=True, default="")   # ok/denegado/timeout/etc
    permiso_geo = models.CharField(max_length=20, blank=True, default="")   # granted/denied/prompt
    device_info = models.TextField(blank=True, default="")

    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "Evidencia de login"
        verbose_name_plural = "Evidencias de login"
        ordering = ["-fecha_hora_servidor"]

    def __str__(self):
        nombre = self.usuario.username if self.usuario_id else (self.username_intentado or "sin_usuario")
        estado = "OK" if self.exito else "FAIL"
        return f"{nombre} - {estado} - {self.fecha_hora_servidor:%Y-%m-%d %H:%M:%S}"