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
        parser.add_argument("--to", type=str, default="", help="Enviar SOLO a este correo (para pruebas).")
        parser.add_argument("--force-empty", action="store_true", help="Enviar aunque no haya registros (manda 0).")

    def _rango_lun_vie(self):
        """
        Reporte de LUNES 00:00 hasta VIERNES 23:59:59 (hora local America/Lima).
        Ideal para ejecutarse el sábado 00:00 (cuando termina el viernes).
        """
        now_local = timezone.localtime(timezone.now())

        # lunes 00:00 de la semana actual (local)
        lunes = (now_local - timedelta(days=now_local.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # viernes 23:59:59.999999 (lunes + 4 días)
        viernes_fin = (lunes + timedelta(days=4)).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        return now_local, lunes, viernes_fin

    def handle(self, *args, **options):
        limite = int(options["limite"])
        dry_run = bool(options["dry_run"])
        only_to = (options["to"] or "").strip()
        force_empty = bool(options["force_empty"])

        now, desde, hasta = self._rango_lun_vie()

        self.stdout.write(
            f"[INFO] Ejecutando reporte (hora local): now={now:%Y-%m-%d %H:%M} "
            f"desde={desde:%Y-%m-%d %H:%M} hasta={hasta:%Y-%m-%d %H:%M}"
        )

        profesores = Profesor.objects.all().order_by("apellidos", "nombres")

        enviados = 0
        errores = 0
        saltados_sin_email = 0
        sin_registros = 0

        for prof in profesores:
            email = (getattr(prof, "email", "") or "").strip()

            if not email:
                saltados_sin_email += 1
                self.stdout.write(f"[SKIP] {prof} -> sin email")
                continue

            # Si estás probando con un solo correo:
            if only_to and email.lower() != only_to.lower():
                continue

            qs = (
                Asistencia.objects
                .filter(profesor=prof, fecha_hora__gte=desde, fecha_hora__lte=hasta)
                .order_by("-fecha_hora")
            )

            total = qs.count()
            if total == 0 and not force_empty:
                sin_registros += 1
                self.stdout.write(f"[SKIP] {email} -> sin registros en el rango")
                continue

            entradas = qs.filter(tipo="E").count()
            salidas = qs.filter(tipo="S").count()

            nombre = f"{(prof.apellidos or '').strip()} {(prof.nombres or '').strip()}".strip()
            subject = f"Reporte Asistencia (Lun-Vie) - {desde:%d/%m} al {hasta:%d/%m/%Y}"

            body_lines = [
                f"Hola {nombre},",
                "",
                "Reporte de asistencias (Lunes a Viernes)",
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

            from_email = (
                getattr(settings, "DEFAULT_FROM_EMAIL", "") or
                getattr(settings, "EMAIL_HOST_USER", "")
            )

            # Log de destinatario (para que lo veas en tu endpoint)
            self.stdout.write(f"[SEND] to={email} total={total} E={entradas} S={salidas} dry_run={dry_run}")

            if dry_run:
                enviados += 1
                continue

            msg = EmailMessage(subject=subject, body=body, from_email=from_email, to=[email])

            try:
                msg.send(fail_silently=False)
                enviados += 1
                self.stdout.write(self.style.SUCCESS(f"[OK] Enviado a {email}"))
            except Exception as e:
                errores += 1
                self.stderr.write(self.style.ERROR(f"[ERROR] Enviando a {email}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"[DONE] Enviados: {enviados}. Errores: {errores}. "
            f"Saltados (sin email): {saltados_sin_email}. Sin registros: {sin_registros}."
        ))
