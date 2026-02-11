from datetime import timedelta
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.utils import timezone
from django.conf import settings

from asistencias.models import Profesor, Asistencia  # <-- si tus modelos se llaman distinto, cámbialos


class Command(BaseCommand):
    help = "Envía por email un reporte de asistencias a cada profesor."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=7, help="Rango en días hacia atrás (default 7).")
        parser.add_argument("--limite", type=int, default=30, help="Máximo de registros listados (default 30).")
        parser.add_argument("--dry-run", action="store_true", help="No envía correos, solo imprime en consola.")

    def _get_prof_email(self, prof: Profesor) -> str:
        # Intenta email directo en Profesor, si no, intenta prof.user.email
        email = getattr(prof, "email", "") or ""
        if not email and hasattr(prof, "user") and prof.user:
            email = getattr(prof.user, "email", "") or ""
        return email.strip()

    def _get_dt_field_name(self) -> str:
        # En tu JSON se ve "fecha" y "fecha_hora".
        # Priorizamos fecha_hora si existe, si no fecha.
        fields = {f.name for f in Asistencia._meta.get_fields() if hasattr(f, "name")}
        if "fecha_hora" in fields:
            return "fecha_hora"
        if "fecha" in fields:
            return "fecha"
        # fallback (por si tu campo se llama distinto)
        return "created_at" if "created_at" in fields else ""

    def handle(self, *args, **options):
        dias = options["dias"]
        limite = options["limite"]
        dry_run = options["dry_run"]

        ahora = timezone.localtime(timezone.now())
        desde = ahora - timedelta(days=dias)

        dt_field = self._get_dt_field_name()
        if not dt_field:
            self.stderr.write(self.style.ERROR(
                "No encontré campo de fecha en Asistencia. Esperaba 'fecha_hora' o 'fecha'."
            ))
            return

        profesores = Profesor.objects.all().order_by("apellidos", "nombres")

        enviados = 0
        saltados = 0

        for prof in profesores:
            email = self._get_prof_email(prof)
            if not email:
                saltados += 1
                continue

            filtros = {f"{dt_field}__gte": desde, f"{dt_field}__lte": ahora, "profesor": prof}
            qs = Asistencia.objects.filter(**filtros).order_by(f"-{dt_field}")

            total = qs.count()
            if total == 0:
                saltados += 1
                continue

            # Contadores típicos en tu proyecto: tipo = entrada/salida
            presentes_entrada = qs.filter(tipo="entrada").count() if hasattr(Asistencia, "tipo") else 0
            salidas = qs.filter(tipo="salida").count() if hasattr(Asistencia, "tipo") else 0

            nombre = f"{getattr(prof, 'apellidos', '')} {getattr(prof, 'nombres', '')}".strip() or "Profesor(a)"

            subject = f"Reporte de asistencias ({dias} días) - {ahora:%d/%m/%Y}"
            body_lines = [
                f"Hola {nombre},",
                "",
                f"Reporte desde {desde:%d/%m/%Y %H:%M} hasta {ahora:%d/%m/%Y %H:%M}",
                f"- Total registros: {total}",
            ]
            if presentes_entrada or salidas:
                body_lines.append(f"- Entradas: {presentes_entrada}")
                body_lines.append(f"- Salidas: {salidas}")

            body_lines += [
                "",
                f"Últimos {min(limite, total)} registros:",
                "----------------------------------------",
            ]

            for a in qs[:limite]:
                dt_val = getattr(a, dt_field)
                dt_txt = timezone.localtime(dt_val).strftime("%d/%m/%Y %H:%M") if hasattr(dt_val, "strftime") else str(dt_val)
                tipo = getattr(a, "tipo", "-")
                body_lines.append(f"{dt_txt}  |  {tipo}")

            body_lines += ["", "Saludos."]

            body = "\n".join(body_lines)

            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")

            if dry_run:
                self.stdout.write(self.style.WARNING(f"[DRY-RUN] Enviaría a: {email}\n{body}\n"))
                enviados += 1
                continue

            msg = EmailMessage(subject=subject, body=body, from_email=from_email, to=[email])

            try:
                msg.send(fail_silently=False)
                enviados += 1
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error enviando a {email}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Listo. Enviados: {enviados}. Saltados: {saltados}."))
