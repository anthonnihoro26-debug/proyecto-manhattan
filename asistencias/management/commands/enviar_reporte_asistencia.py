from datetime import timedelta
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.utils import timezone
from django.conf import settings

from asistencias.models import Profesor, Asistencia


class Command(BaseCommand):
    help = "Envía por email un reporte de asistencias (Lun-Vie) a cada profesor."

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=50, help="Máximo de registros listados (default 50).")
        parser.add_argument("--dry-run", action="store_true", help="No envía correos, solo imprime en consola.")

    def _rango_lun_vie(self):
        """
        Reporte de LUNES 00:00 hasta VIERNES 23:59:59 (semana actual, hora local).
        Si se ejecuta el viernes 00:00, el rango incluye Lun->Jue (y lo que haya del viernes).
        """
        now = timezone.localtime(timezone.now())

        # Lunes 00:00
        lunes = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

        # Viernes 23:59:59 (mismo lunes + 4 días)
        viernes_fin = (lunes + timedelta(days=4)).replace(hour=23, minute=59, second=59, microsecond=999999)

        return now, lunes, viernes_fin

    def handle(self, *args, **options):
        limite = options["limite"]
        dry_run = options["dry_run"]

        now, desde, hasta = self._rango_lun_vie()

        profesores = Profesor.objects.all().order_by("apellidos", "nombres")

        enviados = 0
        saltados = 0
        sin_registros = 0

        for prof in profesores:
            email = (prof.email or "").strip()
            if not email:
                saltados += 1
                continue

            qs = (
                Asistencia.objects
                .filter(profesor=prof, fecha_hora__gte=desde, fecha_hora__lte=hasta)
                .order_by("-fecha_hora")
            )

            total = qs.count()
            if total == 0:
                sin_registros += 1
                continue

            entradas = qs.filter(tipo="E").count()
            salidas = qs.filter(tipo="S").count()

            nombre = f"{prof.apellidos} {prof.nombres}".strip()
            subject = f"Reporte Asistencia (Lun-Vie) - {desde:%d/%m} al {hasta:%d/%m/%Y}"

            body_lines = [
                f"Hola {nombre},",
                "",
                f"Reporte de asistencias (Lunes a Viernes)",
                f"Desde: {desde:%d/%m/%Y %H:%M}",
                f"Hasta: {hasta:%d/%m/%Y %H:%M}",
                "",
                f"- Total registros: {total}",
                f"- Entradas (E): {entradas}",
                f"- Salidas (S): {salidas}",
                "",
                f"Últimos {min(limite, total)} registros:",
                "----------------------------------------",
            ]

            for a in qs[:limite]:
                dt = timezone.localtime(a.fecha_hora).strftime("%d/%m/%Y %H:%M")
                tipo = "ENTRADA" if a.tipo == "E" else "SALIDA"
                body_lines.append(f"{dt} | {tipo}")

            body_lines += ["", "Saludos."]

            body = "\n".join(body_lines)

            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")

            if dry_run:
                self.stdout.write(self.style.WARNING(f"[DRY-RUN] A: {email}\n{body}\n"))
                enviados += 1
                continue

            msg = EmailMessage(subject=subject, body=body, from_email=from_email, to=[email])

            try:
                msg.send(fail_silently=False)
                enviados += 1
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error enviando a {email}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Listo. Enviados: {enviados}. Saltados (sin email): {saltados}. Sin registros: {sin_registros}."
        ))
