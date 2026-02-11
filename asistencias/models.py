from django.db import models
from django.utils import timezone
from django.conf import settings


class Profesor(models.Model):
    codigo = models.CharField(max_length=20, blank=True, null=True)
    dni = models.CharField(max_length=8, unique=True)
    apellidos = models.CharField(max_length=120)
    nombres = models.CharField(max_length=120)
    condicion = models.CharField(max_length=20)

    # ✅ correo para enviar reportes
    email = models.EmailField(blank=True, null=True)

    def __str__(self):
        return f"{self.apellidos} {self.nombres}"


class Asistencia(models.Model):
    TIPOS = (
        ("E", "Entrada"),
        ("S", "Salida"),
        ("J", "Justificación"),  # ✅ NUEVO
    )

    # ✅ mismos motivos que tu JustificacionAsistencia (2 letras)
    MOTIVOS = (
        ("DM", "Descanso médico"),
        ("C", "Comisión / Encargo"),
        ("P", "Permiso"),
        ("O", "Otro"),
    )

    profesor = models.ForeignKey(Profesor, on_delete=models.CASCADE)

    # ✅ Día “normalizado”
    fecha = models.DateField(db_index=True, default=timezone.localdate)

    # ✅ Fecha/hora exacta del registro (escaneo / registro manual / justificación)
    fecha_hora = models.DateTimeField(default=timezone.now, db_index=True)

    # ✅ Entrada / salida / justificación
    tipo = models.CharField(max_length=1, choices=TIPOS, default="E")

    # ✅ Solo si tipo="J"
    motivo = models.CharField(max_length=2, choices=MOTIVOS, blank=True, default="")
    detalle = models.CharField(max_length=255, blank=True, default="")

    # ✅ Auditoría
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            # ✅ NO permite 2 entradas/2 salidas/2 justificaciones el mismo día
            models.UniqueConstraint(fields=["profesor", "fecha", "tipo"], name="uniq_profesor_fecha_tipo"),
        ]
        indexes = [
            models.Index(fields=["profesor", "fecha"]),
        ]

    def __str__(self):
        if self.tipo == "J":
            return f"{self.profesor} - JUSTIFICADO({self.motivo}) - {self.fecha:%d/%m/%Y}"
        tipo = "ENTRADA" if self.tipo == "E" else "SALIDA"
        return f"{self.profesor} - {tipo} - {self.fecha_hora:%d/%m/%Y %H:%M}"


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

    profesor = models.ForeignKey(Profesor, on_delete=models.CASCADE, related_name="justificaciones")
    fecha = models.DateField(db_index=True)

    tipo = models.CharField(max_length=2, choices=TIPO_CHOICES, default="DM")
    detalle = models.CharField(max_length=255, blank=True, default="")

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="justificaciones_creadas"
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="justificaciones_actualizadas"
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profesor", "fecha"], name="uniq_justificacion_profesor_fecha")
        ]
        indexes = [
            models.Index(fields=["fecha", "profesor"]),
        ]
        ordering = ["-fecha", "profesor__apellidos", "profesor__nombres"]

    def __str__(self):
        return f"{self.profesor} - {self.fecha} ({self.tipo})"
