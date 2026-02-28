from datetime import timedelta
import requests
import html
import base64
import os

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static

from asistencias.models import Profesor, Asistencia


class Command(BaseCommand):
    help = "Envía por email un reporte de asistencias (Lun-Vie) a cada profesor SOLO si tiene registros (Brevo API)."

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=50, help="Máximo de registros listados (default 50).")
        parser.add_argument("--max-emails", type=int, default=40, help="Máximo de correos a enviar por ejecución (default 40).")
        parser.add_argument("--dry-run", action="store_true", help="No envía correos, solo imprime en consola.")

    def _rango_lun_vie(self):
        now = timezone.localtime(timezone.now())
        lunes = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        viernes_fin = (lunes + timedelta(days=4)).replace(hour=23, minute=59, second=59, microsecond=999999)
        return now, lunes, viernes_fin

    # =========================
    # Logo desde static (base64) - fallback
    # =========================
    def _logo_data_uri(self) -> str:
        """
        Devuelve data URI base64 para embeber en el email.
        Si no encuentra el archivo, devuelve "" (sin logo).
        """
        static_path = "asistencias/img/uni_logo.png"

        try:
            abs_path = finders.find(static_path)
            if not abs_path or not os.path.exists(abs_path):
                return ""

            with open(abs_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            return f"data:image/png;base64,{b64}"
        except Exception:
            return ""

    # =========================
    # Logo por URL público (Gmail-friendly)
    # Requiere settings.PUBLIC_BASE_URL
    # =========================
    def _logo_public_url(self) -> str:
        """
        Devuelve un URL ABSOLUTO al logo en /static/... usando settings.PUBLIC_BASE_URL.
        Esto evita el problema de Gmail con data:image/base64.
        """
        base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
        if not base:
            return ""

        rel = static("asistencias/img/uni_logo.png")  # -> /static/asistencias/img/uni_logo.png
        return f"{base}{rel}"

    def _tipo_label(self, a: Asistencia) -> str:
        """
        Solo para el reporte:
        - E => ENTRADA
        - J => JUSTIFICACIÓN (con motivo + detalle si hay)
        - S => (se ignora, no debería entrar)
        """
        tipo = (a.tipo or "").strip().upper()

        if tipo == "E":
            return "ENTRADA"

        if tipo == "J":
            try:
                motivo = a.get_motivo_display()
            except Exception:
                motivo = (getattr(a, "motivo", "") or "").strip() or "Sin motivo"

            detalle = (getattr(a, "detalle", "") or "").strip()
            if detalle:
                return f"JUSTIFICACIÓN ({motivo}) - {detalle}"
            return f"JUSTIFICACIÓN ({motivo})"

        return tipo or "REGISTRO"

    def _tipo_badge_html(self, a: Asistencia) -> str:
        """
        Badge visual para el HTML del reporte.
        """
        tipo = (a.tipo or "").strip().upper()

        if tipo == "E":
            return (
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;'
                'font-size:12px;font-weight:700;">ENTRADA</span>'
            )

        if tipo == "J":
            return (
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'background:#f5f3ff;border:1px solid #ddd6fe;color:#5b21b6;'
                'font-size:12px;font-weight:700;">JUSTIFICACIÓN</span>'
            )

        return (
            '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
            'background:#f3f4f6;border:1px solid #e5e7eb;color:#374151;'
            'font-size:12px;font-weight:700;">REGISTRO</span>'
        )

    def _brevo_send_email(self, to_email: str, subject: str, body_text: str, body_html: str):
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
            "htmlContent": body_html,
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

        # Logo embebido (fallback)
        logo_uri = self._logo_data_uri()

        # Logo por URL público (recomendado para Gmail)
        logo_url = self._logo_public_url()

        for prof in profesores:
            if enviados >= max_emails:
                self.stdout.write(self.style.WARNING(f"[STOP] Alcanzado max-emails={max_emails}."))
                break

            email_prof = (getattr(prof, "email", "") or "").strip()
            if not email_prof:
                saltados_sin_email += 1
                continue

            qs = (
                Asistencia.objects
                .filter(
                    profesor=prof,
                    fecha_hora__gte=desde,
                    fecha_hora__lte=hasta,
                    tipo__in=["E", "J"],   # envía a quienes tienen ENTRADA o JUSTIFICACIÓN
                )
                .order_by("-fecha_hora")
            )

            total = qs.count()
            if total == 0:
                saltados_sin_registros += 1
                self.stdout.write(f"[SKIP] {email_prof} -> sin registros (E/J) en el rango")
                continue

            entradas = qs.filter(tipo="E").count()
            justificaciones = qs.filter(tipo="J").count()

            nombre = (
                getattr(prof, "nombre_completo", None)
                or f"{(getattr(prof, 'apellidos', '') or '').strip()} {(getattr(prof, 'nombres', '') or '').strip()}".strip()
            )
            nombre = nombre or "Profesor(a)"

            subject = (
                f"Proyecto Manhattan | Reporte de Asistencia Docente | "
                f"{desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"
            )

            # =========================
            # TEXTO (fallback)
            # =========================
            body_lines = [
                f"Hola {nombre},",
                "",
                "Reporte de asistencia docente (Lunes a Viernes)",
                f"Rango: {desde:%d/%m/%Y %H:%M} a {hasta:%d/%m/%Y %H:%M}",
                "",
                f"Total de registros: {total}",
                f"Entradas: {entradas}",
                f"Justificaciones: {justificaciones}",
                "",
                f"Últimos {min(limite, total)} registros:",
                "----------------------------------------",
            ]

            rows_for_html = []
            for a in qs[:limite]:
                dt = timezone.localtime(a.fecha_hora)
                fecha = dt.strftime("%d/%m/%Y")
                hora = dt.strftime("%H:%M")

                label = self._tipo_label(a)
                badge_html = self._tipo_badge_html(a)

                body_lines.append(f"{fecha} {hora} | {label}")

                rows_for_html.append(
                    f"""
                    <tr>
                      <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;color:#111827;">{html.escape(fecha)}</td>
                      <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;color:#111827;">{html.escape(hora)}</td>
                      <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;">{badge_html}</td>
                      <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;color:#374151;">
                        {html.escape(label)}
                      </td>
                    </tr>
                    """.strip()
                )

            body_lines += [
                "",
                "Este correo fue generado automáticamente por Proyecto Manhattan.",
                "Si identifica alguna inconsistencia, comuníquese con el administrador del sistema.",
                "",
                "Saludos cordiales,",
                "Proyecto Manhattan",
            ]
            body_text = "\n".join(body_lines)

            # =========================
            # HTML (profesional + logo)
            # =========================
            nombre_html = html.escape(nombre)
            rango_html = html.escape(f"{desde:%d/%m/%Y %H:%M} a {hasta:%d/%m/%Y %H:%M}")

            # Prioriza URL público; fallback base64
            img_src = (logo_url or "").strip() or (logo_uri or "").strip()

            if img_src:
                logo_html = f"""
                  <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px;">
                    <div style="height:56px;width:56px;border-radius:14px;background:rgba(255,255,255,.15);padding:6px;border:1px solid rgba(255,255,255,.35);box-sizing:border-box;">
                      <img src="{html.escape(img_src)}" alt="UNI"
                           style="height:100%;width:100%;object-fit:contain;display:block;" />
                    </div>
                    <div>
                      <div style="font-size:14px;font-weight:900;opacity:.95;">Universidad Nacional de Ingeniería</div>
                      <div style="font-size:12px;opacity:.9;">Proyecto Manhattan · Control de Asistencia Docente</div>
                    </div>
                  </div>
                """.strip()
            else:
                logo_html = """
                  <div style="font-size:14px;font-weight:900;opacity:.95;">
                    Proyecto Manhattan · Control de Asistencia Docente
                  </div>
                """.strip()

            body_html = f"""
            <div style="margin:0;padding:0;background:#f3f4f6;">
              <div style="max-width:760px;margin:0 auto;padding:28px 14px;font-family:Arial,Helvetica,sans-serif;">

                <!-- Card principal -->
                <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;overflow:hidden;box-shadow:0 8px 24px rgba(0,0,0,.05);">

                  <!-- Header institucional -->
                  <div style="padding:20px 22px;background:linear-gradient(135deg,#8b1118 0%, #b91c1c 55%, #111827 100%);color:#ffffff;">
                    {logo_html}
                    <div style="font-size:22px;font-weight:900;letter-spacing:.2px;margin-top:8px;">
                      Reporte de Asistencia Docente
                    </div>
                    <div style="font-size:13px;opacity:.95;margin-top:6px;line-height:1.45;">
                      Periodo evaluado: <b>{rango_html}</b>
                    </div>
                  </div>

                  <!-- Cuerpo -->
                  <div style="padding:20px 22px;color:#111827;">

                    <!-- Saludo -->
                    <div style="font-size:15px;line-height:1.5;">
                      Estimado(a) <b>{nombre_html}</b>:
                    </div>
                    <div style="font-size:14px;color:#6b7280;line-height:1.55;margin-top:8px;">
                      A continuación, se presenta el resumen de sus registros de asistencia correspondientes al periodo indicado.
                      Este reporte ha sido generado automáticamente por el sistema <b>Proyecto Manhattan</b>.
                    </div>

                    <!-- KPI cards -->
                    <div style="margin-top:18px;display:flex;gap:12px;flex-wrap:wrap;">
                      <div style="flex:1;min-width:180px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#6b7280;">Total de registros</div>
                        <div style="font-size:24px;font-weight:900;color:#111827;line-height:1.1;margin-top:4px;">{total}</div>
                      </div>

                      <div style="flex:1;min-width:180px;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#065f46;">Entradas</div>
                        <div style="font-size:24px;font-weight:900;color:#065f46;line-height:1.1;margin-top:4px;">{entradas}</div>
                      </div>

                      <div style="flex:1;min-width:180px;background:#f5f3ff;border:1px solid #ddd6fe;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#5b21b6;">Justificaciones</div>
                        <div style="font-size:24px;font-weight:900;color:#5b21b6;line-height:1.1;margin-top:4px;">{justificaciones}</div>
                      </div>
                    </div>

                    <!-- Bloque informativo -->
                    <div style="margin-top:16px;background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:12px 14px;">
                      <div style="font-size:12px;font-weight:700;color:#9a3412;">Resumen informativo</div>
                      <div style="font-size:12px;color:#9a3412;line-height:1.5;margin-top:4px;">
                        Se muestran los <b>últimos {min(limite, total)} registros</b> del periodo seleccionado.
                      </div>
                    </div>

                    <!-- Tabla -->
                    <div style="margin-top:18px;">
                      <div style="font-size:14px;font-weight:800;color:#111827;margin-bottom:10px;">
                        Detalle de registros
                      </div>

                      <div style="border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;">
                        <table style="width:100%;border-collapse:collapse;font-size:13px;">
                          <thead>
                            <tr style="background:#f9fafb;color:#374151;text-align:left;">
                              <th style="padding:11px 12px;border-bottom:1px solid #e5e7eb;">Fecha</th>
                              <th style="padding:11px 12px;border-bottom:1px solid #e5e7eb;">Hora</th>
                              <th style="padding:11px 12px;border-bottom:1px solid #e5e7eb;">Tipo</th>
                              <th style="padding:11px 12px;border-bottom:1px solid #e5e7eb;">Detalle</th>
                            </tr>
                          </thead>
                          <tbody>
                            {''.join(rows_for_html)}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    <!-- Nota -->
                    <div style="margin-top:16px;color:#6b7280;font-size:12px;line-height:1.5;">
                      Si identifica alguna inconsistencia en la información mostrada, por favor comuníquese con el área administradora del sistema para su validación.
                    </div>

                  </div>
                </div>

                <!-- Footer institucional -->
                <div style="text-align:center;color:#9ca3af;font-size:12px;line-height:1.55;margin-top:12px;">
                  <div><b style="color:#6b7280;">Proyecto Manhattan</b> · Sistema de Control de Asistencia Docente</div>
                  <div>Universidad Nacional de Ingeniería · Facultad de Ingeniería Civil</div>
                  <div>Correo automático · No responder directamente a este mensaje</div>
                  <div style="margin-top:4px;">© {timezone.localtime(timezone.now()).strftime("%Y")}</div>
                </div>

              </div>
            </div>
            """.strip()

            if dry_run:
                enviados += 1
                self.stdout.write(self.style.WARNING(
                    f"[DRY-RUN] to={email_prof} total={total} E={entradas} J={justificaciones} "
                    f"logo_url={'ok' if logo_url else 'no'}"
                ))
                continue

            try:
                self._brevo_send_email(email_prof, subject, body_text, body_html)
                enviados += 1
                self.stdout.write(self.style.SUCCESS(
                    f"[SEND] to={email_prof} total={total} E={entradas} J={justificaciones} "
                    f"logo_url={'ok' if logo_url else 'no'}"
                ))
            except Exception as e:
                errores += 1
                self.stderr.write(self.style.ERROR(f"[ERROR] Enviando a {email_prof}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"[DONE] Enviados: {enviados}. Errores: {errores}. "
            f"Saltados (sin email): {saltados_sin_email}. Saltados (sin registros): {saltados_sin_registros}."
        ))