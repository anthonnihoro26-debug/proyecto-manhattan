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
    help = (
        "Envía por email un reporte profesional de asistencia (Lun-Vie) a cada profesor "
        "con evaluación diaria: ENTRADA / JUSTIFICACIÓN / FALTA (Brevo API)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=50, help="Máximo de registros detallados listados (default 50).")
        parser.add_argument("--max-emails", type=int, default=40, help="Máximo de correos a enviar por ejecución (default 40).")
        parser.add_argument("--dry-run", action="store_true", help="No envía correos, solo imprime en consola.")
        parser.add_argument(
            "--solo-con-registros",
            action="store_true",
            help="Si se activa, solo envía a profesores con al menos un registro E/J en el rango (comportamiento anterior).",
        )

    def _rango_lun_vie(self):
        now = timezone.localtime(timezone.now())
        lunes = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        viernes_fin = (lunes + timedelta(days=4)).replace(hour=23, minute=59, second=59, microsecond=999999)
        return now, lunes, viernes_fin

    def _dias_lun_vie(self, lunes_dt):
        """
        Devuelve lista de datetimes (inicio del día) de lunes a viernes.
        """
        base = lunes_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return [base + timedelta(days=i) for i in range(5)]

    # =========================
    # Logo desde static (base64) - fallback
    # =========================
    def _logo_data_uri(self) -> str:
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
    # =========================
    def _logo_public_url(self) -> str:
        base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
        if not base:
            return ""
        rel = static("asistencias/img/uni_logo.png")
        return f"{base}{rel}"

    def _tipo_label(self, a: Asistencia) -> str:
        """
        Label detallado por registro individual.
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

    def _tipo_badge_html(self, tipo: str) -> str:
        """
        Badge visual para el estado diario o tipo resumido.
        """
        t = (tipo or "").strip().upper()

        if t == "ENTRADA":
            return (
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;'
                'font-size:12px;font-weight:700;">ENTRADA</span>'
            )

        if t == "JUSTIFICACIÓN":
            return (
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'background:#f5f3ff;border:1px solid #ddd6fe;color:#5b21b6;'
                'font-size:12px;font-weight:700;">JUSTIFICACIÓN</span>'
            )

        if t == "FALTA":
            return (
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'background:#fef2f2;border:1px solid #fecaca;color:#991b1b;'
                'font-size:12px;font-weight:700;">FALTA</span>'
            )

        return (
            '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
            'background:#f3f4f6;border:1px solid #e5e7eb;color:#374151;'
            'font-size:12px;font-weight:700;">REGISTRO</span>'
        )

    def _estado_diario_profesional(self, prof, lunes, viernes_fin):
        """
        Evalúa los 5 días (Lun-Vie) y devuelve:
        - resumen diario por día (ENTRADA / JUSTIFICACIÓN / FALTA)
        - conteos
        - registros detallados E/J del rango

        Regla por día:
        - si hay E => ENTRADA
        - elif hay J => JUSTIFICACIÓN
        - else => FALTA
        """
        # Registros relevantes para el rango
        qs = (
            Asistencia.objects
            .filter(
                profesor=prof,
                fecha_hora__gte=lunes,
                fecha_hora__lte=viernes_fin,
                tipo__in=["E", "J"],  # se ignora S
            )
            .order_by("fecha_hora")
        )

        # Mapear por fecha local
        por_fecha = {}
        for a in qs:
            dt_local = timezone.localtime(a.fecha_hora)
            key = dt_local.date()
            por_fecha.setdefault(key, []).append((a, dt_local))

        dias = self._dias_lun_vie(lunes)
        dias_eval = []

        entradas = 0
        justificaciones = 0
        faltas = 0

        nombres_dia = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]

        for idx, d in enumerate(dias):
            fecha_date = d.date()
            regs = por_fecha.get(fecha_date, [])

            estado = "FALTA"
            detalle = "Sin registro de entrada ni justificación"
            hora_ref = "-"
            motivo_ref = "-"

            if regs:
                # Prioridad: ENTRADA > JUSTIFICACIÓN
                tiene_e = False
                tiene_j = False
                primer_e = None
                primer_j = None

                for a, dt_local in regs:
                    tipo = (a.tipo or "").strip().upper()
                    if tipo == "E" and not tiene_e:
                        tiene_e = True
                        primer_e = (a, dt_local)
                    elif tipo == "J" and not tiene_j:
                        tiene_j = True
                        primer_j = (a, dt_local)

                if tiene_e and primer_e:
                    a, dt_local = primer_e
                    estado = "ENTRADA"
                    entradas += 1
                    hora_ref = dt_local.strftime("%H:%M")
                    detalle = "Registro de entrada detectado"
                    # Si además hubo J, lo mencionamos como observación adicional
                    if tiene_j:
                        detalle += " (también existe justificación registrada ese día)"
                elif tiene_j and primer_j:
                    a, dt_local = primer_j
                    estado = "JUSTIFICACIÓN"
                    justificaciones += 1
                    hora_ref = dt_local.strftime("%H:%M")
                    try:
                        motivo_ref = a.get_motivo_display()
                    except Exception:
                        motivo_ref = (getattr(a, "motivo", "") or "").strip() or "-"
                    detalle_j = (getattr(a, "detalle", "") or "").strip()
                    detalle = f"Justificación registrada ({motivo_ref})"
                    if detalle_j:
                        detalle += f" - {detalle_j}"
            else:
                faltas += 1

            dias_eval.append({
                "fecha": fecha_date.strftime("%d/%m/%Y"),
                "dia_nombre": nombres_dia[idx],
                "estado": estado,
                "badge_html": self._tipo_badge_html(estado),
                "hora_ref": hora_ref,
                "motivo_ref": motivo_ref,
                "detalle": detalle,
            })

        total_dias = 5
        return {
            "qs_detalle": qs.order_by("-fecha_hora"),  # detalle descendente para listar recientes
            "dias_eval": dias_eval,
            "total_registros_eyj": qs.count(),
            "entradas": entradas,
            "justificaciones": justificaciones,
            "faltas": faltas,
            "total_dias": total_dias,
        }

    def _brevo_send_email(self, to_email: str, subject: str, body_text: str, body_html: str):
        api_key = (getattr(settings, "BREVO_API_KEY", "") or "").strip()
        sender_email = (getattr(settings, "BREVO_SENDER_EMAIL", "") or "").strip()
        sender_name = (getattr(settings, "BREVO_SENDER_NAME", "Proyecto Manhattan") or "").strip()
        timeout = int(getattr(settings, "EMAIL_TIMEOUT", 20))

        if not api_key:
            raise RuntimeError("Falta BREVO_API_KEY en settings/env.")
        if not sender_email:
            raise RuntimeError("Falta BREVO_SENDER_EMAIL en settings/env (remitente verificado en Brevo).")

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
        solo_con_registros = bool(options["solo_con_registros"])

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

        logo_uri = self._logo_data_uri()
        logo_url = self._logo_public_url()

        for prof in profesores:
            if enviados >= max_emails:
                self.stdout.write(self.style.WARNING(f"[STOP] Alcanzado max-emails={max_emails}."))
                break

            email_prof = (getattr(prof, "email", "") or "").strip()
            if not email_prof:
                saltados_sin_email += 1
                continue

            # =========================
            # Evaluación diaria profesional (Lun-Vie)
            # =========================
            resultado = self._estado_diario_profesional(prof, desde, hasta)

            qs_detalle = resultado["qs_detalle"]
            dias_eval = resultado["dias_eval"]
            total_registros_eyj = resultado["total_registros_eyj"]

            entradas = resultado["entradas"]
            justificaciones = resultado["justificaciones"]
            faltas = resultado["faltas"]
            total_dias = resultado["total_dias"]

            # Modo opcional para mantener comportamiento anterior (solo si hubo E/J)
            if solo_con_registros and total_registros_eyj == 0:
                saltados_sin_registros += 1
                self.stdout.write(f"[SKIP] {email_prof} -> sin registros (E/J) en el rango (--solo-con-registros)")
                continue

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
                f"Estimado(a) {nombre},",
                "",
                "Se remite su reporte de asistencia docente (Lunes a Viernes).",
                f"Periodo evaluado: {desde:%d/%m/%Y %H:%M} a {hasta:%d/%m/%Y %H:%M}",
                "",
                "Resumen semanal (evaluación por día):",
                f"- Total de días evaluados: {total_dias}",
                f"- Entradas: {entradas}",
                f"- Justificaciones: {justificaciones}",
                f"- Faltas: {faltas}",
                "",
                "Detalle por día:",
                "----------------------------------------",
            ]

            # Filas HTML evaluación diaria
            rows_dias_html = []
            for d in dias_eval:
                body_lines.append(
                    f"{d['dia_nombre']} {d['fecha']} | {d['estado']} | Hora ref: {d['hora_ref']} | {d['detalle']}"
                )

                rows_dias_html.append(
                    f"""
                    <tr>
                      <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;color:#111827;font-weight:700;">{html.escape(d['dia_nombre'])}</td>
                      <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;color:#111827;">{html.escape(d['fecha'])}</td>
                      <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;">{d['badge_html']}</td>
                      <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;color:#111827;">{html.escape(d['hora_ref'])}</td>
                      <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;color:#374151;">{html.escape(d['detalle'])}</td>
                    </tr>
                    """.strip()
                )

            # Detalle de registros reales E/J (opcional, últimos N)
            body_lines += [
                "",
                f"Registros reales (E/J) - últimos {min(limite, total_registros_eyj)}:",
                "----------------------------------------",
            ]

            rows_registros_html = []
            for a in qs_detalle[:limite]:
                dt = timezone.localtime(a.fecha_hora)
                fecha = dt.strftime("%d/%m/%Y")
                hora = dt.strftime("%H:%M")

                label = self._tipo_label(a)
                tipo_simple = "ENTRADA" if (a.tipo or "").strip().upper() == "E" else "JUSTIFICACIÓN"

                body_lines.append(f"{fecha} {hora} | {label}")

                rows_registros_html.append(
                    f"""
                    <tr>
                      <td style="padding:10px 12px;border-bottom:1px solid #eef2f7;color:#111827;">{html.escape(fecha)}</td>
                      <td style="padding:10px 12px;border-bottom:1px solid #eef2f7;color:#111827;">{html.escape(hora)}</td>
                      <td style="padding:10px 12px;border-bottom:1px solid #eef2f7;">{self._tipo_badge_html(tipo_simple)}</td>
                      <td style="padding:10px 12px;border-bottom:1px solid #eef2f7;color:#374151;">{html.escape(label)}</td>
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
            # HTML Profesional (institucional)
            # =========================
            nombre_html = html.escape(nombre)
            rango_html = html.escape(f"{desde:%d/%m/%Y %H:%M} a {hasta:%d/%m/%Y %H:%M}")

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
              <div style="max-width:820px;margin:0 auto;padding:28px 14px;font-family:Arial,Helvetica,sans-serif;">

                <!-- Card principal -->
                <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;overflow:hidden;box-shadow:0 8px 24px rgba(0,0,0,.05);">

                  <!-- Header -->
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
                      Se presenta el <b>reporte semanal de asistencia</b> correspondiente al periodo indicado.
                      La evaluación se realiza por día hábil (lunes a viernes), clasificando cada fecha como
                      <b>Entrada</b>, <b>Justificación</b> o <b>Falta</b> cuando no existe registro.
                    </div>

                    <!-- KPI -->
                    <div style="margin-top:18px;display:flex;gap:12px;flex-wrap:wrap;">
                      <div style="flex:1;min-width:150px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#6b7280;">Días evaluados</div>
                        <div style="font-size:24px;font-weight:900;color:#111827;line-height:1.1;margin-top:4px;">{total_dias}</div>
                      </div>

                      <div style="flex:1;min-width:150px;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#065f46;">Entradas</div>
                        <div style="font-size:24px;font-weight:900;color:#065f46;line-height:1.1;margin-top:4px;">{entradas}</div>
                      </div>

                      <div style="flex:1;min-width:150px;background:#f5f3ff;border:1px solid #ddd6fe;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#5b21b6;">Justificaciones</div>
                        <div style="font-size:24px;font-weight:900;color:#5b21b6;line-height:1.1;margin-top:4px;">{justificaciones}</div>
                      </div>

                      <div style="flex:1;min-width:150px;background:#fef2f2;border:1px solid #fecaca;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#991b1b;">Faltas</div>
                        <div style="font-size:24px;font-weight:900;color:#991b1b;line-height:1.1;margin-top:4px;">{faltas}</div>
                      </div>
                    </div>

                    <!-- Resumen semanal por día -->
                    <div style="margin-top:18px;">
                      <div style="font-size:14px;font-weight:800;color:#111827;margin-bottom:10px;">
                        Evaluación diaria (Lunes a Viernes)
                      </div>

                      <div style="border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;">
                        <table style="width:100%;border-collapse:collapse;font-size:13px;">
                          <thead>
                            <tr style="background:#f9fafb;color:#374151;text-align:left;">
                              <th style="padding:11px 12px;border-bottom:1px solid #e5e7eb;">Día</th>
                              <th style="padding:11px 12px;border-bottom:1px solid #e5e7eb;">Fecha</th>
                              <th style="padding:11px 12px;border-bottom:1px solid #e5e7eb;">Estado</th>
                              <th style="padding:11px 12px;border-bottom:1px solid #e5e7eb;">Hora referencia</th>
                              <th style="padding:11px 12px;border-bottom:1px solid #e5e7eb;">Detalle</th>
                            </tr>
                          </thead>
                          <tbody>
                            {''.join(rows_dias_html)}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    <!-- Registros E/J -->
                    <div style="margin-top:18px;background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:12px 14px;">
                      <div style="font-size:12px;font-weight:700;color:#9a3412;">Detalle de registros reales (E/J)</div>
                      <div style="font-size:12px;color:#9a3412;line-height:1.5;margin-top:4px;">
                        Se muestran los <b>últimos {min(limite, total_registros_eyj)}</b> registros encontrados en el periodo.
                        Total de registros E/J detectados: <b>{total_registros_eyj}</b>.
                      </div>
                    </div>

                    <div style="margin-top:12px;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;">
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
                          {''.join(rows_registros_html) if rows_registros_html else '<tr><td colspan="4" style="padding:12px;color:#6b7280;">No se encontraron registros E/J en el periodo.</td></tr>'}
                        </tbody>
                      </table>
                    </div>

                    <!-- Nota -->
                    <div style="margin-top:16px;color:#6b7280;font-size:12px;line-height:1.5;">
                      Si identifica alguna inconsistencia en la información mostrada, por favor comuníquese con el área administradora del sistema para su validación.
                    </div>

                  </div>
                </div>

                <!-- Footer -->
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
                    f"[DRY-RUN] to={email_prof} dias={total_dias} E={entradas} J={justificaciones} F={faltas} "
                    f"registros_EJ={total_registros_eyj} logo_url={'ok' if logo_url else 'no'}"
                ))
                continue

            try:
                self._brevo_send_email(email_prof, subject, body_text, body_html)
                enviados += 1
                self.stdout.write(self.style.SUCCESS(
                    f"[SEND] to={email_prof} dias={total_dias} E={entradas} J={justificaciones} F={faltas} "
                    f"registros_EJ={total_registros_eyj} logo_url={'ok' if logo_url else 'no'}"
                ))
            except Exception as e:
                errores += 1
                self.stderr.write(self.style.ERROR(f"[ERROR] Enviando a {email_prof}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"[DONE] Enviados: {enviados}. Errores: {errores}. "
            f"Saltados (sin email): {saltados_sin_email}. Saltados (sin registros): {saltados_sin_registros}."
        ))