from datetime import timedelta
import requests
import html
import base64
import os

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from django.contrib.staticfiles import finders

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
    # ✅ Logo desde static (base64)
    # =========================
    def _logo_data_uri(self) -> str:
        """
        Devuelve data URI base64 para embeber en el email.
        Si no encuentra el archivo, devuelve "" (sin logo).
        """
        # Cambia aquí si tu logo se llama distinto
        static_path = "asistencias/img/uni_logo.png"

        try:
            abs_path = finders.find(static_path)
            if not abs_path or not os.path.exists(abs_path):
                return ""

            with open(abs_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            # PNG
            return f"data:image/png;base64,{b64}"
        except Exception:
            return ""

    def _tipo_label(self, a: Asistencia) -> str:
        """
        ✅ Solo para el reporte. Aquí:
        - E => ENTRADA
        - J => JUSTIFICACIÓN (con motivo + detalle si hay)
        - S => (se ignora, no debería entrar)
        """
        if a.tipo == "E":
            return "ENTRADA"

        if a.tipo == "J":
            # motivo por display (DM->Descanso médico, etc.)
            try:
                motivo = a.get_motivo_display()
            except Exception:
                motivo = (a.motivo or "").strip() or "Sin motivo"

            detalle = (a.detalle or "").strip()
            if detalle:
                return f"JUSTIFICACIÓN ({motivo}) - {detalle}"
            return f"JUSTIFICACIÓN ({motivo})"

        return str(a.tipo or "").strip() or "REGISTRO"

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

        # ✅ logo embebido
        logo_uri = self._logo_data_uri()

        for prof in profesores:
            if enviados >= max_emails:
                self.stdout.write(self.style.WARNING(f"[STOP] Alcanzado max-emails={max_emails}."))
                break

            email_prof = (getattr(prof, "email", "") or "").strip()
            if not email_prof:
                saltados_sin_email += 1
                continue

            # ✅ IMPORTANTE:
            # Solo consideramos Entradas (E) y Justificaciones (J)
            qs = (
                Asistencia.objects
                .filter(
                    profesor=prof,
                    fecha_hora__gte=desde,
                    fecha_hora__lte=hasta,
                    tipo__in=["E", "J"],   # 🚫 ignora S
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

            nombre = getattr(prof, "nombre_completo", None) or f"{(prof.apellidos or '').strip()} {(prof.nombres or '').strip()}".strip()
            nombre = nombre or "Profesor(a)"

            subject = f"Reporte de Asistencia (Lun–Vie) | {desde:%d/%m} al {hasta:%d/%m/%Y}"

            # =========================
            # ✅ TEXTO (fallback)
            # =========================
            body_lines = [
                f"Hola {nombre},",
                "",
                "Reporte de asistencia (Lunes a Viernes)",
                f"Rango: {desde:%d/%m/%Y %H:%M}  a  {hasta:%d/%m/%Y %H:%M}",
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
                body_lines.append(f"{fecha} {hora} | {label}")

                rows_for_html.append(
                    f"""
                    <tr>
                      <td style="padding:10px 12px;border-bottom:1px solid #eaeaea;">{html.escape(fecha)}</td>
                      <td style="padding:10px 12px;border-bottom:1px solid #eaeaea;">{html.escape(hora)}</td>
                      <td style="padding:10px 12px;border-bottom:1px solid #eaeaea;font-weight:700;">{html.escape(label)}</td>
                    </tr>
                    """.strip()
                )

            body_lines += ["", "Saludos.", "Proyecto Manhattan"]
            body_text = "\n".join(body_lines)

            # =========================
            # ✅ HTML (profesional + logo)
            # =========================
            nombre_html = html.escape(nombre)
            rango_html = html.escape(f"{desde:%d/%m/%Y %H:%M} a {hasta:%d/%m/%Y %H:%M}")

            # ✅ por defecto: NO mostrar Justificaciones si es 0
            mostrar_just_linea = False

            just_html_line = ""
            if mostrar_just_linea or justificaciones > 0:
                just_html_line = f"""
                  <div style="flex:1;background:#f6f7fb;border:1px solid #ececf3;border-radius:14px;padding:14px;min-width:180px;">
                    <div style="font-size:12px;color:#6b7280;">Justificaciones</div>
                    <div style="font-size:22px;font-weight:900;color:#111827;line-height:1.1;">{justificaciones}</div>
                  </div>
                """.strip()

            logo_html = ""
            if logo_uri:
                logo_html = f"""
                  <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">
                    <img src="{logo_uri}" alt="Logo" style="height:52px;width:52px;object-fit:contain;border-radius:12px;background:rgba(255,255,255,.92);padding:6px;" />
                    <div>
                      <div style="font-size:14px;opacity:.92;font-weight:800;">Universidad Nacional de Ingeniería</div>
                      <div style="font-size:12px;opacity:.88;">Proyecto Manhattan • Control de Asistencia</div>
                    </div>
                  </div>
                """.strip()
            else:
                # fallback si no hay logo
                logo_html = """
                  <div style="font-size:14px;opacity:.92;font-weight:800;">Proyecto Manhattan</div>
                """.strip()

            body_html = f"""
            <div style="margin:0;padding:0;background:#f3f4f6;">
              <div style="max-width:740px;margin:0 auto;padding:26px 14px;font-family:Arial,Helvetica,sans-serif;">
                <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;overflow:hidden;">
                  <div style="padding:18px 20px;background:linear-gradient(135deg,#111827,#2563eb);color:#fff;">
                    {logo_html}
                    <div style="font-size:22px;font-weight:900;margin-top:6px;">Reporte de Asistencia (Lun–Vie)</div>
                    <div style="font-size:13px;opacity:.92;margin-top:6px;">Rango: {rango_html}</div>
                  </div>

                  <div style="padding:18px 20px;color:#111827;">
                    <div style="font-size:15px;margin-bottom:14px;">
                      Hola <b>{nombre_html}</b>,
                      <div style="color:#6b7280;margin-top:6px;">
                        A continuación se muestra el resumen de tus registros en el rango indicado.
                      </div>
                    </div>

                    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
                      <div style="flex:1;background:#f6f7fb;border:1px solid #ececf3;border-radius:14px;padding:14px;min-width:180px;">
                        <div style="font-size:12px;color:#6b7280;">Total de registros</div>
                        <div style="font-size:22px;font-weight:900;color:#111827;line-height:1.1;">{total}</div>
                      </div>

                      <div style="flex:1;background:#f6f7fb;border:1px solid #ececf3;border-radius:14px;padding:14px;min-width:180px;">
                        <div style="font-size:12px;color:#6b7280;">Entradas</div>
                        <div style="font-size:22px;font-weight:900;color:#111827;line-height:1.1;">{entradas}</div>
                      </div>

                      {just_html_line}
                    </div>

                    <div style="margin-top:6px;margin-bottom:10px;font-size:14px;font-weight:900;color:#111827;">
                      Últimos {min(limite, total)} registros
                    </div>

                    <div style="border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;">
                      <table style="width:100%;border-collapse:collapse;font-size:14px;">
                        <thead>
                          <tr style="background:#f9fafb;color:#374151;text-align:left;">
                            <th style="padding:10px 12px;border-bottom:1px solid #eaeaea;">Fecha</th>
                            <th style="padding:10px 12px;border-bottom:1px solid #eaeaea;">Hora</th>
                            <th style="padding:10px 12px;border-bottom:1px solid #eaeaea;">Registro</th>
                          </tr>
                        </thead>
                        <tbody>
                          {''.join(rows_for_html)}
                        </tbody>
                      </table>
                    </div>

                    <div style="margin-top:16px;color:#6b7280;font-size:12px;line-height:1.45;">
                      Este correo fue generado automáticamente. Si encuentras algún dato incorrecto, comunícate con el administrador del sistema.
                    </div>
                  </div>
                </div>

                <div style="text-align:center;color:#9ca3af;font-size:12px;margin-top:10px;">
                  © {timezone.localtime(timezone.now()).strftime("%Y")} Proyecto Manhattan
                </div>
              </div>
            </div>
            """.strip()

            if dry_run:
                enviados += 1
                self.stdout.write(self.style.WARNING(
                    f"[DRY-RUN] to={email_prof} total={total} E={entradas} J={justificaciones}"
                ))
                continue

            try:
                self._brevo_send_email(email_prof, subject, body_text, body_html)
                enviados += 1
                self.stdout.write(self.style.SUCCESS(
                    f"[SEND] to={email_prof} total={total} E={entradas} J={justificaciones}"
                ))
            except Exception as e:
                errores += 1
                self.stderr.write(self.style.ERROR(f"[ERROR] Enviando a {email_prof}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"[DONE] Enviados: {enviados}. Errores: {errores}. "
            f"Saltados (sin email): {saltados_sin_email}. Saltados (sin registros): {saltados_sin_registros}."
        ))
