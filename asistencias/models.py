from django.db import models
from django.utils import timezone

class Profesor(models.Model):
    codigo = models.CharField(max_length=20, blank=True, null=True)
    dni = models.CharField(max_length=8, unique=True)
    apellidos = models.CharField(max_length=120)
    nombres = models.CharField(max_length=120)
    condicion = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.apellidos} {self.nombres}"


class Asistencia(models.Model):
    profesor = models.ForeignKey('Profesor', on_delete=models.CASCADE)
    fecha_hora = models.DateTimeField(default=timezone.now)  # ✅ tiene default

    def __str__(self):
        return f"{self.profesor} - {self.fecha_hora:%d/%m/%Y %H:%M}"

