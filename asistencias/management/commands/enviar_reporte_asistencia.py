from datetime import timedelta
import requests

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings

from asistencias.models import Profesor, Asistencia


class Command(BaseCommand):
    help = "Envía por email un reporte de asistencias (Lun-Vie) a cada profesor SOLO si tiene registros (Brevo API)."

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=50, help="Máximo de registros listados (default 50).")
        parser.add_argument("--max-emails", type=int, default=40, help="Máximo de correos a enviar por ejecución (default 40).")
        parser.add_argument("--dry-run", action="store_true", help="No envía correos, solo imprime en consola.")

    def _rango_lun_vie(self):
        """
        Reporte de LUNES 00:00 hasta VIERNES 23:59:59 (semana actual, hora local).
        Ideal si lo ejecutas el sábado 00:00.
        """
        now = timezone.localtime(timezone.now())

        lunes = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        viernes_fin = (lunes + timedelta(days=4)).replace(hour=23, minute=59, second=59, microsecond=999999)

        return now, lunes, viernes_fin

    def _brevo_send_email(self, to_email: str, subject: str, body_text: str):
        api_key = (getattr(settings, "BREVO_API_KEY", "") or "").strip()
        sender_email = (getattr(settings, "BREVO_SENDER_EMAIL", "") or "").strip()
        sender_name = (getattr(settings, "BREVO_SENDER_NAME", "Proyecto Manhattan") or "").strip()
        timeout = int(getattr(settings, "EMAIL_TIMEOUT", 20))

        if not api_key:
            raise RuntimeError("Falta BREVO_API_KEY en settings/env.")
        if not sender_email:
            raise RuntimeError("Falta BREVO_SENDER_EMAIL en settings/env (debe ser un remitente verificado en Brevo).")

        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        }
        payload = {
            "sender": {"name": sender_name, "email": sender_email},
            "to": [{"email": to_email}],
            "subject": subject,
            "textContent": body_text,
        }

        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Brevo error {r.status_code}: {r.text}")

        return True

    def handle(self, *args, **options):
        limite = int(options["limite"])
        max_emails = int(options["max_emails"])
        dry_run = bool(options["dry_run"])

        now, desde, hasta = self._rango_lun_vie()

        self.stdout.write(
            f"[INFO] Ejecutando reporte (hora local): now={now:%Y-%m-%d %H:%M} "
            f"desde={desde:%Y-%m-%d %H:%M} hasta={hasta:%Y-%m-%d %H:%M}"
        )

        profesores = Profesor.objects.all().order_by("apellidos", "nombres")

        enviados = 0
        errores = 0
        saltados_sin_email = 0
        saltados_sin_registros = 0

        for prof in profesores:
            if enviados >= max_emails:
                self.stdout.write(self.style.WARNING(f"[STOP] Alcanzado max-emails={max_emails}."))
                break

            email = (getattr(prof, "email", "") or "").strip()
            if not email:
                saltados_sin_email += 1
                continue

            qs = (
                Asistencia.objects
                .filter(profesor=prof, fecha_hora__gte=desde, fecha_hora__lte=hasta)
                .order_by("-fecha_hora")
            )

            total = qs.count()
            if total == 0:
                saltados_sin_registros += 1
                # ✅ SOLO envía si tiene registros
                self.stdout.write(f"[SKIP] {email} -> sin registros en el rango")
                continue

            # ✅ En tu sistema:
            # E = ENTRADA
            # S = JUSTIFICACIÓN (NO "SALIDA")
            entradas = qs.filter(tipo="E").count()
            justificaciones = qs.filter(tipo="S").count()

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
                f"- Justificaciones: {justificaciones}",
                "",
                f"Últimos {min(limite, total)} registros:",
                "----------------------------------------",
            ]

            for a in qs[:limite]:
                dt = timezone.localtime(a.fecha_hora).strftime("%d/%m/%Y %H:%M")

                if a.tipo == "E":
                    tipo_txt = "ENTRADA"
                elif a.tipo == "S":
                    tipo_txt = "JUSTIFICACIÓN"
                else:
                    # Por si en el futuro agregas más tipos
                    tipo_txt = str(a.tipo)

                body_lines.append(f"{dt} | {tipo_txt}")

            body_lines += ["", "Saludos."]

            body = "\n".join(body_lines)

            if dry_run:
                enviados += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"[DRY-RUN] to={email} total={total} E={entradas} JUST={justificaciones}"
                    )
                )
                continue

            try:
                self._brevo_send_email(email, subject, body)
                enviados += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[SEND] to={email} total={total} E={entradas} JUST={justificaciones}"
                    )
                )
            except Exception as e:
                errores += 1
                self.stderr.write(self.style.ERROR(f"[ERROR] Enviando a {email}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"[DONE] Enviados: {enviados}. Errores: {errores}. "
            f"Saltados (sin email): {saltados_sin_email}. Saltados (sin registros): {saltados_sin_registros}."
        ))

