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

from asistencias.models import Profesor, Asistencia, JustificacionAsistencia, DiaEspecial


class Command(BaseCommand):
    help = (
        "Envía por email un reporte profesional de asistencia (Lun-Vie) a cada profesor "
        "con evaluación diaria: ASISTIÓ / JUSTIFICACIÓN / FALTA / DÍA ESPECIAL (Brevo API)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--max-emails", type=int, default=40, help="Máximo de correos a procesar por ejecución (default 40).")
        parser.add_argument("--dry-run", action="store_true", help="No envía correos, solo imprime en consola.")
        parser.add_argument(
            "--solo-con-registros",
            action="store_true",
            help="Si se activa, solo procesa profesores con al menos un registro E/J en el rango.",
        )

    def _rango_lun_vie(self):
        now = timezone.localtime(timezone.now())
        lunes = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        viernes_fin = (lunes + timedelta(days=4)).replace(hour=23, minute=59, second=59, microsecond=999999)
        return now, lunes, viernes_fin

    def _dias_lun_vie(self, lunes_dt):
        base = lunes_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return [base + timedelta(days=i) for i in range(5)]

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

    def _logo_public_url(self) -> str:
        base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
        if not base:
            return ""
        rel = static("asistencias/img/uni_logo.png")
        return f"{base}{rel}"

    def _tipo_badge_html(self, tipo: str) -> str:
        t = (tipo or "").strip().upper()

        if t == "ASISTIÓ":
            return (
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;'
                'font-size:12px;font-weight:700;">ASISTIÓ</span>'
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

        if t == "FERIADO":
            return (
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'background:#fff7ed;border:1px solid #fdba74;color:#9a3412;'
                'font-size:12px;font-weight:700;">FERIADO</span>'
            )

        if t == "HUELGA":
            return (
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'background:#fff7ed;border:1px solid #fdba74;color:#7c2d12;'
                'font-size:12px;font-weight:700;">HUELGA</span>'
            )

        if t == "PARO":
            return (
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'background:#fff7ed;border:1px solid #fdba74;color:#9a3412;'
                'font-size:12px;font-weight:700;">PARO DE TRANSPORTISTAS</span>'
            )

        if t == "SUSPENSIÓN":
            return (
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'background:#fffbeb;border:1px solid #fcd34d;color:#92400e;'
                'font-size:12px;font-weight:700;">SUSPENSIÓN</span>'
            )

        if t == "REMOTO":
            return (
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'background:#eff6ff;border:1px solid #93c5fd;color:#1d4ed8;'
                'font-size:12px;font-weight:700;">JORNADA REMOTA</span>'
            )

        if t == "NO LABORABLE":
            return (
                '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
                'background:#f8fafc;border:1px solid #cbd5e1;color:#475569;'
                'font-size:12px;font-weight:700;">NO LABORABLE</span>'
            )

        return (
            '<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
            'background:#f3f4f6;border:1px solid #e5e7eb;color:#374151;'
            'font-size:12px;font-weight:700;">REGISTRO</span>'
        )

    def _obtener_dia_especial(self, fecha_date):
        return DiaEspecial.objects.filter(fecha=fecha_date, activo=True).first()

    def _estado_dia_especial(self, dia_especial):
        tipo = (dia_especial.tipo or "").strip().upper()
        detalle = (dia_especial.descripcion or "").strip()

        if tipo == "FERIADO":
            return {
                "estado": "FERIADO",
                "hora_registrada": "-",
                "observacion": detalle or "No hubo actividades académicas por feriado.",
            }

        if tipo == "HUELGA":
            return {
                "estado": "HUELGA",
                "hora_registrada": "-",
                "observacion": detalle or "No se considera falta por huelga o medida de fuerza.",
            }

        if tipo == "PARO":
            return {
                "estado": "PARO",
                "hora_registrada": "-",
                "observacion": detalle or "No se considera falta por paro de transportistas o dificultades de traslado.",
            }

        if tipo == "SUSPENSION":
            return {
                "estado": "SUSPENSIÓN",
                "hora_registrada": "-",
                "observacion": detalle or "Se suspendieron las actividades académicas o institucionales.",
            }

        if tipo == "REMOTO":
            return {
                "estado": "REMOTO",
                "hora_registrada": "-",
                "observacion": detalle or "La jornada fue desarrollada en modalidad remota institucional.",
            }

        if tipo == "NO_LABORABLE":
            return {
                "estado": "NO LABORABLE",
                "hora_registrada": "-",
                "observacion": detalle or "No corresponde registrar asistencia ni falta en esta fecha.",
            }

        return {
            "estado": "DÍA ESPECIAL",
            "hora_registrada": "-",
            "observacion": detalle or "No corresponde registrar falta en esta fecha.",
        }

    def _estado_diario_profesional(self, prof, lunes, viernes_fin):
        """
        Evalúa los 5 días (Lun-Vie) y devuelve estado por día:
        - FERIADO / HUELGA / PARO / SUSPENSIÓN / REMOTO / NO LABORABLE (si existe DíaEspecial activo)
        - ASISTIÓ (si hay E)
        - JUSTIFICACIÓN (si no hay E pero sí J)
        - FALTA (si no hay E ni J ni día especial)
        """
        qs = (
            Asistencia.objects
            .filter(
                profesor=prof,
                fecha_hora__gte=lunes,
                fecha_hora__lte=viernes_fin,
                tipo__in=["E", "J"],
            )
            .order_by("fecha_hora")
        )

        por_fecha = {}
        for a in qs:
            dt_local = timezone.localtime(a.fecha_hora)
            key = dt_local.date()
            por_fecha.setdefault(key, []).append((a, dt_local))

        justis_qs = (
            JustificacionAsistencia.objects
            .filter(
                profesor=prof,
                fecha__gte=lunes.date(),
                fecha__lte=viernes_fin.date(),
            )
            .order_by("fecha", "creado_en")
        )

        justis_por_fecha = {}
        for j in justis_qs:
            justis_por_fecha.setdefault(j.fecha, []).append(j)

        dias = self._dias_lun_vie(lunes)
        dias_eval = []

        asistio = 0
        justificaciones = 0
        faltas = 0
        dias_especiales = 0

        nombres_dia = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]

        for idx, d in enumerate(dias):
            fecha_date = d.date()
            regs = por_fecha.get(fecha_date, [])
            justis = justis_por_fecha.get(fecha_date, [])
            dia_especial = self._obtener_dia_especial(fecha_date)

            estado = "FALTA"
            observacion = "No se registró asistencia ni justificación en la fecha evaluada."
            hora_registrada = "-"

            if dia_especial:
                info_especial = self._estado_dia_especial(dia_especial)
                estado = info_especial["estado"]
                observacion = info_especial["observacion"]
                hora_registrada = info_especial["hora_registrada"]
                dias_especiales += 1

            else:
                if regs:
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
                        _, dt_local = primer_e
                        estado = "ASISTIÓ"
                        asistio += 1
                        hora_registrada = dt_local.strftime("%H:%M")
                        observacion = "Se registró asistencia en la fecha evaluada."
                        if tiene_j or justis:
                            observacion = "Se registró asistencia en la fecha evaluada (existe además una justificación en la fecha)."

                    elif tiene_j and primer_j:
                        a, dt_local = primer_j
                        estado = "JUSTIFICACIÓN"
                        justificaciones += 1
                        hora_registrada = dt_local.strftime("%H:%M")
                        try:
                            motivo = a.get_motivo_display()
                        except Exception:
                            motivo = (getattr(a, "motivo", "") or "").strip() or "Sin motivo"

                        detalle = (getattr(a, "detalle", "") or "").strip()
                        observacion = f"Justificación registrada ({motivo})."
                        if detalle:
                            observacion = f"Justificación registrada ({motivo}): {detalle}"

                    elif justis:
                        j = justis[0]
                        estado = "JUSTIFICACIÓN"
                        justificaciones += 1
                        hora_registrada = "-"
                        try:
                            motivo = j.get_tipo_display()
                        except Exception:
                            motivo = (getattr(j, "tipo", "") or "").strip() or "Sin motivo"

                        detalle = (getattr(j, "detalle", "") or "").strip()
                        observacion = f"Justificación registrada ({motivo})."
                        if detalle:
                            observacion = f"Justificación registrada ({motivo}): {detalle}"

                    else:
                        faltas += 1

                else:
                    if justis:
                        j = justis[0]
                        estado = "JUSTIFICACIÓN"
                        justificaciones += 1
                        hora_registrada = "-"
                        try:
                            motivo = j.get_tipo_display()
                        except Exception:
                            motivo = (getattr(j, "tipo", "") or "").strip() or "Sin motivo"

                        detalle = (getattr(j, "detalle", "") or "").strip()
                        observacion = f"Justificación registrada ({motivo})."
                        if detalle:
                            observacion = f"Justificación registrada ({motivo}): {detalle}"
                    else:
                        faltas += 1

            dias_eval.append({
                "dia_nombre": nombres_dia[idx],
                "fecha": fecha_date.strftime("%d/%m/%Y"),
                "estado": estado,
                "badge_html": self._tipo_badge_html(estado),
                "hora_registrada": hora_registrada,
                "observacion": observacion,
            })

        total_dias = 5
        cumplimiento_base = asistio + justificaciones + dias_especiales
        cumplimiento = round(cumplimiento_base * 100 / total_dias, 1) if total_dias else 0

        return {
            "dias_eval": dias_eval,
            "asistio": asistio,
            "justificaciones": justificaciones,
            "faltas": faltas,
            "dias_especiales": dias_especiales,
            "total_dias": total_dias,
            "cumplimiento": cumplimiento,
            "total_registros_eyj": qs.count(),
        }

    def _bloque_plazo_html(self, now, faltas):
        if now.weekday() != 4 or faltas <= 0:
            return ""

        fecha_viernes = now.strftime("%d/%m/%Y")
        fecha_lunes = (now + timedelta(days=3)).strftime("%d/%m/%Y")

        return f"""
        <div style="margin-top:18px;background:#fff8eb;border:1px solid #f59e0b;border-radius:12px;padding:14px 16px;">
          <div style="font-size:14px;font-weight:800;color:#92400e;margin-bottom:8px;">
            📌 Plazo para presentación de justificaciones
          </div>
          <div style="font-size:13px;color:#5b3b00;line-height:1.7;">
            El presente reporte ha sido remitido el día <b>viernes {fecha_viernes}</b>.
            En caso de registrarse alguna inasistencia en condición de <b>FALTA</b>,
            el plazo máximo para presentar la justificación correspondiente será hasta el día
            <b>lunes {fecha_lunes}</b>.
          </div>
          <div style="margin-top:8px;font-size:12px;color:#6b4f1d;line-height:1.6;">
            Se recomienda regularizar oportunamente cualquier observación,
            a fin de mantener actualizado el control de asistencia institucional.
          </div>
        </div>
        """.strip()

    def _bloque_marcha_blanca_html(self):
        return """
        <div style="margin-top:18px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:14px 16px;">
          <div style="font-size:14px;font-weight:800;color:#1d4ed8;margin-bottom:8px;">
            ℹ️ Aviso importante
          </div>
          <div style="font-size:13px;color:#1e3a8a;line-height:1.7;">
            Recordar que nos encontramos en <b>proceso de marcha blanca</b>.
          </div>
        </div>
        """.strip()

    def _brevo_send_email(self, to_email: str, subject: str, body_text: str, body_html: str):
        api_key = (getattr(settings, "BREVO_API_KEY", "") or "").strip()
        sender_email = (getattr(settings, "BREVO_SENDER_EMAIL", "") or "").strip()
        sender_name = (getattr(settings, "BREVO_SENDER_NAME", "Proyecto Manhattan") or "").strip()
        reply_to_email = (getattr(settings, "BREVO_REPLY_TO_EMAIL", "") or "").strip()
        reply_to_name = (
            getattr(settings, "BREVO_REPLY_TO_NAME", "Departamento Académico de Ciencias Básicas")
            or "Departamento Académico de Ciencias Básicas"
        ).strip()
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
            "sender": {
                "name": sender_name,
                "email": sender_email,
            },
            "to": [
                {
                    "email": to_email,
                }
            ],
            "subject": subject,
            "textContent": body_text,
            "htmlContent": body_html,
        }

        if reply_to_email:
            payload["replyTo"] = {
                "email": reply_to_email,
                "name": reply_to_name,
            }

        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Brevo error {r.status_code}: {r.text}")

        return True

    def handle(self, *args, **options):
        max_emails = int(options["max_emails"])
        dry_run = bool(options["dry_run"])
        solo_con_registros = bool(options["solo_con_registros"])

        envio_habilitado = True

        now, desde, hasta = self._rango_lun_vie()

        self.stdout.write(
            f"[INFO] Ejecutando reporte (hora local): now={now:%Y-%m-%d %H:%M} "
            f"desde={desde:%Y-%m-%d %H:%M} hasta={hasta:%Y-%m-%d %H:%M}"
        )

        if envio_habilitado:
            self.stdout.write(self.style.SUCCESS(
                "[MODO ACTIVO] El envío de correos está HABILITADO en este comando."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "[MODO SEGURO] El envío de correos está COMPLETAMENTE BLOQUEADO en este comando."
            ))

        profesores = Profesor.objects.all().order_by("apellidos", "nombres")

        enviados = 0
        errores = 0
        saltados_sin_email = 0
        saltados_sin_registros = 0
        bloqueados = 0

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

            resultado = self._estado_diario_profesional(prof, desde, hasta)

            dias_eval = resultado["dias_eval"]
            asistio = resultado["asistio"]
            justificaciones = resultado["justificaciones"]
            faltas = resultado["faltas"]
            dias_especiales = resultado["dias_especiales"]
            total_dias = resultado["total_dias"]
            cumplimiento = resultado["cumplimiento"]
            total_registros_eyj = resultado["total_registros_eyj"]

            if solo_con_registros and total_registros_eyj == 0 and dias_especiales == 0:
                saltados_sin_registros += 1
                self.stdout.write(f"[SKIP] {email_prof} -> sin registros (E/J) ni días especiales en el rango (--solo-con-registros)")
                continue

            nombre = (
                getattr(prof, "nombre_completo", None)
                or f"{(getattr(prof, 'apellidos', '') or '').strip()} {(getattr(prof, 'nombres', '') or '').strip()}".strip()
            )
            nombre = nombre or "Profesor(a)"

            subject = (
                f"UNI | Reporte Semanal de Asistencia Docente | "
                f"{desde:%d/%m/%Y} - {hasta:%d/%m/%Y}"
            )

            body_lines = [
                f"Estimado(a) {nombre},",
                "",
                "Reciba un cordial saludo.",
                "",
                "Se remite su reporte semanal de asistencia docente correspondiente al periodo indicado.",
                f"Periodo evaluado: {desde:%d/%m/%Y %H:%M} a {hasta:%d/%m/%Y %H:%M}",
                "",
                "Resumen semanal (evaluación por día hábil):",
                f"- Días evaluados: {total_dias}",
                f"- Asistió: {asistio}",
                f"- Justificaciones: {justificaciones}",
                f"- Días especiales: {dias_especiales}",
                f"- Faltas: {faltas}",
                f"- Cumplimiento: {cumplimiento}%",
                "",
                "Evaluación diaria (Lunes a Viernes):",
                "----------------------------------------",
            ]

            rows_dias_html = []
            for d in dias_eval:
                body_lines.append(
                    f"{d['dia_nombre']} {d['fecha']} | {d['estado']} | Hora: {d['hora_registrada']} | {d['observacion']}"
                )

                rows_dias_html.append(
                    f"""
                    <tr>
                      <td style="padding:12px 12px;border-bottom:1px solid #eef2f7;color:#111827;font-weight:700;">{html.escape(d['dia_nombre'])}</td>
                      <td style="padding:12px 12px;border-bottom:1px solid #eef2f7;color:#111827;">{html.escape(d['fecha'])}</td>
                      <td style="padding:12px 12px;border-bottom:1px solid #eef2f7;">{d['badge_html']}</td>
                      <td style="padding:12px 12px;border-bottom:1px solid #eef2f7;color:#111827;">{html.escape(d['hora_registrada'])}</td>
                      <td style="padding:12px 12px;border-bottom:1px solid #eef2f7;color:#374151;line-height:1.5;">{html.escape(d['observacion'])}</td>
                    </tr>
                    """.strip()
                )

            if now.weekday() == 4 and faltas > 0:
                fecha_viernes_txt = now.strftime("%d/%m/%Y")
                fecha_lunes_txt = (now + timedelta(days=3)).strftime("%d/%m/%Y")
                body_lines += [
                    "",
                    f"Plazo para justificación: Este reporte ha sido remitido el viernes {fecha_viernes_txt}.",
                    f"Si registra alguna FALTA, podrá presentar la justificación correspondiente hasta el lunes {fecha_lunes_txt}.",
                ]

            body_lines += [
                "",
                "Recordar que estamos en proceso de marcha blanca.",
                "",
                "Este reporte ha sido generado automáticamente por Proyecto Manhattan para fines de seguimiento y control institucional.",
                "Si identifica alguna inconsistencia, comuníquese con el área administradora del sistema.",
                "",
                "Atentamente,",
                "Proyecto Manhattan",
                "Sistema de Control de Asistencia Docente",
                "Universidad Nacional de Ingeniería",
            ]
            body_text = "\n".join(body_lines)

            nombre_html = html.escape(nombre)
            rango_html = html.escape(f"{desde:%d/%m/%Y %H:%M} a {hasta:%d/%m/%Y %H:%M}")
            cumplimiento_text = f"{cumplimiento:.1f}%".replace(".0%", "%")

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

            bloque_plazo_html = self._bloque_plazo_html(now, faltas)
            bloque_marcha_blanca_html = self._bloque_marcha_blanca_html()

            body_html = f"""
            <div style="margin:0;padding:0;background:#f3f4f6;">
              <div style="max-width:820px;margin:0 auto;padding:30px 14px;font-family:Arial,Helvetica,sans-serif;">

                <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:20px;overflow:hidden;box-shadow:0 10px 28px rgba(0,0,0,.06);">

                  <div style="padding:22px 24px;background:linear-gradient(135deg,#8b1118 0%, #b91c1c 55%, #111827 100%);color:#ffffff;">
                    {logo_html}
                    <div style="font-size:23px;font-weight:900;letter-spacing:.2px;margin-top:8px;">
                      Reporte Semanal de Asistencia Docente
                    </div>
                    <div style="font-size:13px;opacity:.95;margin-top:7px;line-height:1.5;">
                      Periodo evaluado: <b>{rango_html}</b>
                    </div>
                  </div>

                  <div style="padding:22px 24px;color:#111827;">

                    <div style="font-size:15px;line-height:1.6;color:#111827;">
                      Estimado(a) <b>{nombre_html}</b>:
                    </div>
                    <div style="font-size:14px;color:#4b5563;line-height:1.65;margin-top:10px;">
                      Reciba un cordial saludo. A continuación, se remite su <b>reporte semanal de asistencia docente</b>,
                      correspondiente al periodo indicado. La evaluación considera los días hábiles de <b>lunes a viernes</b>,
                      clasificando cada fecha como <b>Asistió</b>, <b>Justificación</b>, <b>Día especial</b> o <b>Falta</b> según los registros del sistema.
                    </div>
                    <div style="margin-top:10px;font-size:13px;color:#6b7280;line-height:1.55;">
                      Este reporte ha sido generado automáticamente por <b>Proyecto Manhattan</b> para fines de seguimiento y control institucional.
                    </div>

                    <div style="margin-top:20px;display:flex;gap:12px;flex-wrap:wrap;">
                      <div style="flex:1;min-width:140px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#64748b;">Días evaluados</div>
                        <div style="font-size:26px;font-weight:900;color:#0f172a;line-height:1.1;margin-top:4px;">{total_dias}</div>
                      </div>

                      <div style="flex:1;min-width:140px;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#065f46;">Asistió</div>
                        <div style="font-size:26px;font-weight:900;color:#065f46;line-height:1.1;margin-top:4px;">{asistio}</div>
                      </div>

                      <div style="flex:1;min-width:140px;background:#f5f3ff;border:1px solid #ddd6fe;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#5b21b6;">Justificaciones</div>
                        <div style="font-size:26px;font-weight:900;color:#5b21b6;line-height:1.1;margin-top:4px;">{justificaciones}</div>
                      </div>

                      <div style="flex:1;min-width:140px;background:#fff7ed;border:1px solid #fdba74;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#9a3412;">Días especiales</div>
                        <div style="font-size:26px;font-weight:900;color:#9a3412;line-height:1.1;margin-top:4px;">{dias_especiales}</div>
                      </div>

                      <div style="flex:1;min-width:140px;background:#fef2f2;border:1px solid #fecaca;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#991b1b;">Faltas</div>
                        <div style="font-size:26px;font-weight:900;color:#991b1b;line-height:1.1;margin-top:4px;">{faltas}</div>
                      </div>

                      <div style="flex:1;min-width:140px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:14px;padding:14px;">
                        <div style="font-size:12px;color:#1d4ed8;">Cumplimiento</div>
                        <div style="font-size:26px;font-weight:900;color:#1d4ed8;line-height:1.1;margin-top:4px;">{cumplimiento_text}</div>
                      </div>
                    </div>

                    <div style="margin-top:22px;">
                      <div style="font-size:15px;font-weight:800;color:#111827;margin-bottom:10px;">
                        Evaluación diaria (Lunes a Viernes)
                      </div>

                      <div style="border:1px solid #e5e7eb;border-radius:14px;overflow:hidden;">
                        <table style="width:100%;border-collapse:collapse;font-size:13px;">
                          <thead>
                            <tr style="background:#f8fafc;color:#374151;text-align:left;">
                              <th style="padding:12px 12px;border-bottom:1px solid #e5e7eb;">Día</th>
                              <th style="padding:12px 12px;border-bottom:1px solid #e5e7eb;">Fecha</th>
                              <th style="padding:12px 12px;border-bottom:1px solid #e5e7eb;">Estado</th>
                              <th style="padding:12px 12px;border-bottom:1px solid #e5e7eb;">Hora registrada</th>
                              <th style="padding:12px 12px;border-bottom:1px solid #e5e7eb;">Observación</th>
                            </tr>
                          </thead>
                          <tbody>
                            {''.join(rows_dias_html)}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    {bloque_plazo_html}
                    {bloque_marcha_blanca_html}

                    <div style="margin-top:18px;background:#f8fafc;border:1px solid #e5e7eb;border-radius:12px;padding:12px 14px;">
                      <div style="font-size:12px;color:#475569;line-height:1.6;">
                        Si identifica alguna observación o inconsistencia en la información mostrada, por favor comuníquese con el área administradora del sistema para su revisión y validación correspondiente.
                      </div>
                    </div>

                  </div>
                </div>

                <div style="text-align:center;color:#94a3b8;font-size:12px;line-height:1.6;margin-top:14px;">
                  <div><b style="color:#64748b;">Proyecto Manhattan</b> · Sistema de Control de Asistencia Docente</div>
                  <div>Departamento Académico de Ciencias Básicas · Facultad de Ingeniería Civil</div>
                  <div>Universidad Nacional de Ingeniería</div>
                  <div>Correo automático · No responder directamente a este mensaje</div>
                  <div style="margin-top:4px;">© {timezone.localtime(timezone.now()).strftime("%Y")}</div>
                </div>

              </div>
            </div>
            """.strip()

            if dry_run:
                bloqueados += 1
                self.stdout.write(self.style.WARNING(
                    f"[DRY-RUN] to={email_prof} A={asistio} J={justificaciones} DE={dias_especiales} F={faltas} "
                    f"cumpl={cumplimiento_text} registros_EJ={total_registros_eyj} logo_url={'ok' if logo_url else 'no'}"
                ))
                continue

            if not envio_habilitado:
                bloqueados += 1
                self.stdout.write(self.style.WARNING(
                    f"[BLOQUEADO] No se enviará correo a {email_prof}. "
                    f"A={asistio} J={justificaciones} DE={dias_especiales} F={faltas} "
                    f"cumpl={cumplimiento_text} registros_EJ={total_registros_eyj} "
                    f"logo_url={'ok' if logo_url else 'no'}"
                ))
                continue

            try:
                self._brevo_send_email(email_prof, subject, body_text, body_html)
                enviados += 1
                self.stdout.write(self.style.SUCCESS(
                    f"[SEND] to={email_prof} A={asistio} J={justificaciones} DE={dias_especiales} F={faltas} "
                    f"cumpl={cumplimiento_text} registros_EJ={total_registros_eyj} logo_url={'ok' if logo_url else 'no'}"
                ))
            except Exception as e:
                errores += 1
                self.stderr.write(self.style.ERROR(f"[ERROR] Enviando a {email_prof}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"[DONE] Enviados: {enviados}. Bloqueados: {bloqueados}. Errores: {errores}. "
            f"Saltados (sin email): {saltados_sin_email}. Saltados (sin registros): {saltados_sin_registros}."
        ))