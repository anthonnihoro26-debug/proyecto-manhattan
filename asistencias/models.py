from django.db import models
from django.utils import timezone
from django.conf import settings


class Profesor(models.Model):
    codigo = models.CharField(max_length=20, blank=True, null=True)
    dni = models.CharField(max_length=8, unique=True)
    apellidos = models.CharField(max_length=120)
    nombres = models.CharField(max_length=120)
    condicion = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.apellidos} {self.nombres}"


class Asistencia(models.Model):
    TIPOS = (
        ("E", "Entrada"),
        ("S", "Salida"),
    )

    profesor = models.ForeignKey(Profesor, on_delete=models.CASCADE)

    # ✅ Día “normalizado” para buscar rápido y controlar duplicados por día
    fecha = models.DateField(db_index=True, default=timezone.localdate)

    # ✅ Fecha/hora exacta del escaneo
    fecha_hora = models.DateTimeField(default=timezone.now, db_index=True)

    # ✅ Entrada o salida
    tipo = models.CharField(max_length=1, choices=TIPOS, default="E")

    # ✅ Auditoría (opcional, pero pro)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            # ✅ NO permite 2 entradas el mismo día ni 2 salidas el mismo día
            models.UniqueConstraint(fields=["profesor", "fecha", "tipo"], name="uniq_profesor_fecha_tipo"),
        ]
        indexes = [
            models.Index(fields=["profesor", "fecha"]),
        ]

    def __str__(self):
        tipo = "ENTRADA" if self.tipo == "E" else "SALIDA"
        return f"{self.profesor} - {tipo} - {self.fecha_hora:%d/%m/%Y %H:%M}"
