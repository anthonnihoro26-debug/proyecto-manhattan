"""Despacho institucional: autorización aparte, 1 envío general por semana.
La operación marca una reserva en PostgreSQL ANTES de usar Brevo. Una excepción
no provoca automáticamente reintentos: previene duplicados accidentales.
"""
import re
from datetime import timedelta
from io import StringIO
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.conf import settings
from django.db.models import Count
from django.db.models.functions import Lower
from django.utils import timezone
from .models import Profesor, ReporteEnvio


class EnvioNoPermitido(Exception):
    pass


def semana_actual():
    hoy = timezone.localdate()
    return hoy - timedelta(days=hoy.weekday())


def preparar_envio(origen="manual", usuario=None):
    if not getattr(settings, "BREVO_API_KEY", "") or not getattr(settings, "BREVO_SENDER_EMAIL", ""):
        raise EnvioNoPermitido("Falta configurar Brevo. No se envió ningún mensaje.")
    elegibles = Profesor.objects.filter(activo=True, email__isnull=False).exclude(email="")
    total = elegibles.count()
    repetidos = (elegibles.annotate(email_normalizado=Lower("email"))
                 .values("email_normalizado").annotate(cantidad=Count("pk"))
                 .filter(cantidad__gt=1).exists())
    if repetidos:
        raise EnvioNoPermitido("Hay correos repetidos entre profesores activos. Corrígelos antes del envío general.")
    if total == 0:
        raise EnvioNoPermitido("No hay profesores activos con correo registrado.")
    if total > 40:
        raise EnvioNoPermitido(
            f"Hay {total} docentes activos con correo, pero el envío sincrónico admite como máximo 40. "
            "No se envió ningún mensaje; se requiere envío por lotes antes de continuar."
        )
    lunes = semana_actual()
    try:
        with transaction.atomic():
            lote = ReporteEnvio.objects.create(
                semana_inicio=lunes, origen=origen, usuario=usuario, estado="iniciado"
            )
    except IntegrityError:
        raise EnvioNoPermitido(
            "Ya existe un envío iniciado o realizado para esta semana. "
            "Revisa la sección Envíos semanales antes de decidir un reenvío."
        )

    salida = StringIO()
    try:
        call_command("enviar_reporte_asistencia", max_emails=40, dry_run=False, stdout=salida)
        resultado = salida.getvalue()
        match = re.search(r"\[DONE\]\s+Enviados:\s*(\d+)\.\s+Bloqueados:\s*(\d+)\.\s+Errores:\s*(\d+)", resultado)
        enviados = int(match.group(1)) if match else 0
        errores = int(match.group(3)) if match else 1
        # Un lote es completo SOLO si Brevo aceptó un correo por cada docente
        # elegible. Un total inferior debe revisarse, no darse por terminado.
        if match and enviados != total and errores == 0:
            errores = total - enviados
        lote.enviados = enviados
        lote.errores = errores
        lote.estado = "completado" if match and enviados == total and not errores else "parcial"
        lote.resumen = resultado[-12000:]
    except Exception as exc:
        lote.estado = "error"
        lote.errores = 1
        lote.resumen = (salida.getvalue() + "\nError: " + str(exc))[-12000:]
    finally:
        lote.finalizado_en = timezone.now()
        lote.save(update_fields=["enviados", "errores", "estado", "resumen", "finalizado_en"])
    return lote
