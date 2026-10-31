from datetime import timedelta
import requests
import html
import unicodedata
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.conf import settings
from django.templatetags.static import static

from asistencias.models import Profesor, Asistencia, JustificacionAsistencia, DiaEspecial


class Command(BaseCommand):
    help = (
        "Envía por email un reporte profesional de asistencia (Lun-Vie) a cada profesor "
        "con evaluación diaria: ASISTIÓ / JUSTIFICACIÓN / FALTA / DÍA ESPECIAL (Brevo API)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-emails",
            type=int,
            default=40,
            help="Máximo de correos a procesar por ejecución (default 40).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="No envía correos, solo imprime en consola.",
        )
        parser.add_argument(
            "--email-profesor",
            type=str,
            default="",
            help="Enviar el reporte exclusivamente al profesor con este correo exacto (debe existir solo uno).",
        )
        parser.add_argument(
            "--solo-con-registros",
            action="store_true",
            help="Si se activa, solo procesa profesores con al menos un registro E o justificación oficial en el rango.",
        )

    def _rango_lun_vie(self):
        now = timezone.localtime(timezone.now())
        lunes = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        viernes_fin = (lunes + timedelta(days=4)).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        return now, lunes, viernes_fin

    def _dias_lun_vie(self, lunes_dt):
        base = lunes_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return [base + timedelta(days=i) for i in range(5)]

    def _logo_public_url(self) -> str:
        base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
        if not base:
            return ""
        rel = static("asistencias/img/uni_logo.png")
        return f"{base}{rel}"

    def _normalize_text(self, value: str) -> str:
        value = (value or "").strip().upper()
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = value.replace("-", "_").replace(" ", "_")
        while "__" in value:
            value = value.replace("__", "_")
        return value

    def _tipo_badge_html(self, tipo: str) -> str:
        t = (tipo or "").strip().upper()

        if t == "ASISTIÓ":
            return (
                '<span style="display:inline-block;padding:3px 7px;border-radius:8px;'
                'background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;'
                'font-size:10px;font-weight:700;">ASISTIÓ</span>'
            )

        if t == "JUSTIFICACIÓN":
            return (
                '<span style="display:inline-block;padding:3px 7px;border-radius:8px;'
                'background:#f5f3ff;border:1px solid #ddd6fe;color:#5b21b6;'
                'font-size:10px;font-weight:700;">JUSTIFICACIÓN</span>'
            )

        if t == "FALTA":
            return (
                '<span style="display:inline-block;padding:3px 7px;border-radius:8px;'
                'background:#fef2f2;border:1px solid #fecaca;color:#991b1b;'
                'font-size:10px;font-weight:700;">FALTA</span>'
            )

        if t == "FERIADO":
            return (
                '<span style="display:inline-block;padding:3px 7px;border-radius:8px;'
                'background:#fff7ed;border:1px solid #fdba74;color:#9a3412;'
                'font-size:10px;font-weight:700;">FERIADO</span>'
            )

        if t == "HUELGA":
            return (
                '<span style="display:inline-block;padding:3px 7px;border-radius:8px;'
                'background:#fff7ed;border:1px solid #fdba74;color:#7c2d12;'
                'font-size:10px;font-weight:700;">HUELGA</span>'
            )

        if t == "PARO":
            return (
                '<span style="display:inline-block;padding:3px 7px;border-radius:8px;'
                'background:#fff7ed;border:1px solid #fdba74;color:#9a3412;'
                'font-size:10px;font-weight:700;">PARO</span>'
            )

        if t == "SUSPENSIÓN":
            return (
                '<span style="display:inline-block;padding:3px 7px;border-radius:8px;'
                'background:#fffbeb;border:1px solid #fcd34d;color:#92400e;'
                'font-size:10px;font-weight:700;">SUSPENSIÓN</span>'
            )

        if t == "REMOTO":
            return (
                '<span style="display:inline-block;padding:3px 7px;border-radius:8px;'
                'background:#eff6ff;border:1px solid #93c5fd;color:#1d4ed8;'
                'font-size:10px;font-weight:700;">REMOTO</span>'
            )

        if t == "NO LABORABLE":
            return (
                '<span style="display:inline-block;padding:3px 7px;border-radius:8px;'
                'background:#f8fafc;border:1px solid #cbd5e1;color:#475569;'
                'font-size:10px;font-weight:700;">NO LABORABLE</span>'
            )

        if t == "DÍA ESPECIAL":
            return (
                '<span style="display:inline-block;padding:3px 7px;border-radius:8px;'
                'background:#f8fafc;border:1px solid #cbd5e1;color:#475569;'
                'font-size:10px;font-weight:700;">DÍA ESPECIAL</span>'
            )

        return (
            '<span style="display:inline-block;padding:3px 7px;border-radius:8px;'
            'background:#f3f4f6;border:1px solid #e5e7eb;color:#374151;'
            'font-size:10px;font-weight:700;">REGISTRO</span>'
        )

    def _obtener_dia_especial(self, fecha_date):
        return DiaEspecial.objects.filter(fecha=fecha_date, activo=True).first()

    def _estado_dia_especial(self, dia_especial):
        tipo_raw = (dia_especial.tipo or "").strip()
        tipo = self._normalize_text(tipo_raw)
        detalle = (dia_especial.descripcion or "").strip()

        if tipo == "FERIADO":
            return {
                "estado": "FERIADO",
                "hora_registrada": "-",
                "observacion": detalle or "No hubo actividades académicas por feriado.",
                "es_evaluable": False,
            }

        if tipo == "HUELGA":
            return {
                "estado": "HUELGA",
                "hora_registrada": "-",
                "observacion": detalle or "No se considera falta por huelga o medida de fuerza.",
                "es_evaluable": False,
            }

        if tipo in ("PARO", "PARO_DE_TRANSPORTISTAS"):
            return {
                "estado": "PARO",
                "hora_registrada": "-",
                "observacion": detalle or "No se considera falta por paro de transportistas o dificultades de traslado.",
                "es_evaluable": False,
            }

        if tipo in ("SUSPENSION", "SUSPENSION_DE_ACTIVIDADES"):
            return {
                "estado": "SUSPENSIÓN",
                "hora_registrada": "-",
                "observacion": detalle or "Se suspendieron las actividades académicas o institucionales.",
                "es_evaluable": False,
            }

        if tipo == "REMOTO":
            return {
                "estado": "REMOTO",
                "hora_registrada": "-",
                "observacion": detalle or "La jornada fue desarrollada en modalidad remota institucional.",
                "es_evaluable": False,
            }

        if tipo in ("NO_LABORABLE", "NO_LABORABLES", "NO_LABORABLE_DIA"):
            return {
                "estado": "NO LABORABLE",
                "hora_registrada": "-",
                "observacion": detalle or "No corresponde registrar asistencia ni falta en esta fecha.",
                "es_evaluable": False,
            }

        return {
            "estado": "DÍA ESPECIAL",
            "hora_registrada": "-",
            "observacion": detalle or "No corresponde registrar falta en esta fecha.",
            "es_evaluable": False,
        }

    def _estado_diario_profesional(self, prof, lunes, viernes_fin):
        """
        Evalúa los 5 días (Lun-Vie) y devuelve estado por día:
        - FERIADO / HUELGA / PARO / SUSPENSIÓN / REMOTO / NO LABORABLE (si existe DíaEspecial activo)
        - ASISTIÓ (si hay E)
        - JUSTIFICACIÓN (solo si existe JustificacionAsistencia oficial)
        - FALTA (si no hay E, ni justificación oficial, ni día especial)

        IMPORTANTE:
        - Usa Asistencia.fecha para ubicar cada registro en su día real
        - NO usa fecha_hora.date() para clasificar
        - Los días especiales NO cuentan como falta
        - Los días especiales NO se consideran días evaluables
        - El cumplimiento se calcula sobre días evaluables reales
        - Asistencia(tipo="J") ya NO convierte una falta en justificación
        """

        qs_entradas = (
            Asistencia.objects.filter(
                profesor=prof,
                fecha__gte=lunes.date(),
                fecha__lte=viernes_fin.date(),
                tipo="E",
            )
            .order_by("fecha", "fecha_hora", "id")
        )

        por_fecha_entradas = {}
        for a in qs_entradas:
            key = a.fecha
            dt_local = timezone.localtime(a.fecha_hora) if a.fecha_hora else None
            por_fecha_entradas.setdefault(key, []).append((a, dt_local))

        justis_qs = (
            JustificacionAsistencia.objects.filter(
                profesor=prof,
                fecha__gte=lunes.date(),
                fecha__lte=viernes_fin.date(),
            )
            .order_by("fecha", "creado_en", "id")
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
        dias_evaluables = 0

        nombres_dia = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]

        for idx, d in enumerate(dias):
            fecha_date = d.date()
            regs_e = por_fecha_entradas.get(fecha_date, [])
            justis = justis_por_fecha.get(fecha_date, [])
            dia_especial = self._obtener_dia_especial(fecha_date)

            estado = "FALTA"
            observacion = "No se registró asistencia ni justificación en la fecha evaluada."
            hora_registrada = "-"
            es_evaluable = True

            if dia_especial:
                info_especial = self._estado_dia_especial(dia_especial)
                estado = info_especial["estado"]
                observacion = info_especial["observacion"]
                hora_registrada = info_especial["hora_registrada"]
                es_evaluable = info_especial["es_evaluable"]
                dias_especiales += 1
            else:
                dias_evaluables += 1
                primer_e = regs_e[0] if regs_e else None

                if primer_e:
                    _, dt_local = primer_e
                    estado = "ASISTIÓ"
                    asistio += 1
                    hora_registrada = dt_local.strftime("%H:%M") if dt_local else "-"
                    observacion = "Se registró asistencia en la fecha evaluada."

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

            dias_eval.append(
                {
                    "dia_nombre": nombres_dia[idx],
                    "fecha": fecha_date.strftime("%d/%m/%Y"),
                    "estado": estado,
                    "badge_html": self._tipo_badge_html(estado),
                    "hora_registrada": hora_registrada,
                    "observacion": observacion,
                    "es_evaluable": es_evaluable,
                }
            )

        total_dias_semana = 5
        total_dias = dias_evaluables
        cumplimiento_base = asistio + justificaciones
        cumplimiento = round(cumplimiento_base * 100 / total_dias, 1) if total_dias else 0

        total_registros_eyj = qs_entradas.count()
        total_justificaciones_ext = justis_qs.count()
        total_registros_relevantes = total_registros_eyj + total_justificaciones_ext

        return {
            "dias_eval": dias_eval,
            "asistio": asistio,
            "justificaciones": justificaciones,
            "faltas": faltas,
            "dias_especiales": dias_especiales,
            "total_dias": total_dias,
            "total_dias_semana": total_dias_semana,
            "dias_evaluables": dias_evaluables,
            "cumplimiento": cumplimiento,
            "total_registros_eyj": total_registros_eyj,
            "total_justificaciones_ext": total_justificaciones_ext,
            "total_registros_relevantes": total_registros_relevantes,
        }

    def _bloque_plazo_html(self, now, faltas):
        if now.weekday() != 4 or faltas <= 0:
            return ""

        fecha_viernes = now.strftime("%d/%m/%Y")
        fecha_lunes = (now + timedelta(days=3)).strftime("%d/%m/%Y")

        return f"""
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
               style="margin-top:14px;border-collapse:separate;background-color:#fbf5eb;border:1px solid #ead9bf;border-radius:9px;">
          <tr><td style="padding:11px 13px;font-size:12px;line-height:1.6;color:#72552f;">
            <strong>Plazo de justificación:</strong> si registra una falta en el reporte
            remitido el viernes {fecha_viernes}, puede presentar su justificación
            hasta el lunes {fecha_lunes}.
          </td></tr>
        </table>
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
            self.stdout.write(
                self.style.SUCCESS(
                    "[MODO ACTIVO] El envío de correos está HABILITADO en este comando."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "[MODO SEGURO] El envío de correos está COMPLETAMENTE BLOQUEADO en este comando."
                )
            )

        profesores = Profesor.objects.filter(activo=True).order_by("apellidos", "nombres")

        # La selección por destinatario se aplica ANTES de generar o enviar reportes.
        # Nunca permite un correo ambiguo: cero o varios docentes => ningún envío.
        email_profesor = (options.get("email_profesor") or "").strip()
        if email_profesor:
            profesores = profesores.filter(email__iexact=email_profesor)
            coincidencias = profesores.count()
            if coincidencias != 1:
                raise CommandError(
                    "No se enviaron correos: el correo indicado debe pertenecer "
                    "a exactamente UN docente (coincidencias: %s)." % coincidencias
                )
            max_emails = 1
            self.stdout.write("[FILTRO] Modo docente único: se procesará exactamente un registro.")

        enviados = 0
        errores = 0
        saltados_sin_email = 0
        saltados_sin_registros = 0
        bloqueados = 0

        # Sin imágenes base64 incrustadas: evitan correos HTML enormes en Gmail.
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
            total_dias_semana = resultado["total_dias_semana"]
            dias_evaluables = resultado["dias_evaluables"]
            cumplimiento = resultado["cumplimiento"]
            total_registros_relevantes = resultado["total_registros_relevantes"]

            if solo_con_registros and total_registros_relevantes == 0 and dias_especiales == 0:
                saltados_sin_registros += 1
                self.stdout.write(
                    f"[SKIP] {email_prof} -> sin registros ni justificaciones ni días especiales en el rango (--solo-con-registros)"
                )
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
            # Gmail agrupa/oculta texto repetido cuando las pruebas llegan con el
            # mismo asunto durante la misma semana. Diferenciar solo las pruebas
            # individuales reduce el riesgo de que el detalle diario se repliegue.
            # El asunto de los envíos generales permanece idéntico.
            if email_profesor and not dry_run:
                codigo_prueba = uuid.uuid4().hex[:8].upper()
                subject = f"UNI | Prueba individual {codigo_prueba} | Reporte semanal | {desde:%d/%m/%Y} - {hasta:%d/%m/%Y}"

            body_lines = [
                f"Estimado(a) {nombre},",
                "",
                "Reciba un cordial saludo.",
                "",
                "Se remite su reporte semanal de asistencia docente correspondiente al periodo indicado.",
                f"Periodo evaluado: {desde:%d/%m/%Y %H:%M} a {hasta:%d/%m/%Y %H:%M}",
                "",
                "Resumen semanal (evaluación por día hábil):",
                f"- Días de la semana considerados: {total_dias_semana}",
                f"- Días evaluables reales: {dias_evaluables}",
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

                # El resumen conserva las observaciones especiales y justificaciones.
                # Para estados ordinarios se evita repetir frases largas en cada fila.
                if d["estado"] == "ASISTIÓ":
                    detalle = (
                        f"Entrada: {d['hora_registrada']}"
                        if d["hora_registrada"] != "-"
                        else "Asistencia registrada"
                    )
                elif d["estado"] == "FALTA":
                    detalle = "Sin marca ni justificación"
                else:
                    detalle = d["observacion"] or "—"

                rows_dias_html.append(
                    f"""
                    <tr>
                      <td valign="top" style="padding:10px 9px;border-bottom:1px solid #e9ecef;font-size:11px;line-height:1.5;color:#1f2937;">
                        <strong style="font-size:12px;">{html.escape(d['dia_nombre'])}</strong><br />
                        <span style="color:#64748b;">{html.escape(d['fecha'])}</span>
                      </td>
                      <td valign="top" style="padding:10px 6px;border-bottom:1px solid #e9ecef;">
                        {d['badge_html']}
                      </td>
                      <td valign="top" style="padding:10px 9px;border-bottom:1px solid #e9ecef;font-size:11px;line-height:1.55;color:#475569;word-break:break-word;">
                        {html.escape(detalle)}
                      </td>
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

            img_src = (logo_url or "").strip()

            if img_src:
                logo_html = (
                    f'<img src="{html.escape(img_src, quote=True)}" alt="UNI" width="42" height="42" '
                    'style="display:block;width:42px;height:42px;object-fit:contain;border:0;" />'
                )
            else:
                logo_html = (
                    '<span style="font-family:Arial,Helvetica,sans-serif;font-size:18px;'
                    'font-weight:800;color:#f1ddb0;">UNI</span>'
                )

            bloque_plazo_html = self._bloque_plazo_html(now, faltas)
            # La plantilla usa tablas de presentación para evitar que Gmail desborde
            # las tarjetas y para adaptarse a pantallas pequeñas.
            body_html = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Reporte semanal de asistencia docente</title>
</head>
<body style="margin:0;padding:0;background-color:#f3f2f0;font-family:Arial,Helvetica,sans-serif;color:#24303a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f3f2f0" style="width:100%;border-collapse:collapse;">
    <tr><td align="center" style="padding:20px 9px;">
      <table role="presentation" align="center" width="600" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff"
             style="width:100%;max-width:600px;border-collapse:separate;background-color:#ffffff;border:1px solid #e5e2df;border-radius:12px;overflow:hidden;">
        <tr><td bgcolor="#702f3c" style="padding:16px 20px;background-color:#702f3c;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
            <tr>
              <td width="48" valign="middle" style="width:48px;padding-right:10px;">{logo_html}</td>
              <td valign="middle" style="font-size:10px;line-height:1.5;color:#f5eadd;letter-spacing:.3px;">
                <strong style="font-size:12px;color:#ffffff;">Universidad Nacional de Ingeniería</strong><br />
                Departamento Académico de Ciencias Básicas
              </td>
            </tr>
          </table>
        </td></tr>
        <tr><td bgcolor="#c9ae7b" height="3" style="height:3px;line-height:3px;font-size:1px;background-color:#c9ae7b;">&nbsp;</td></tr>
        <tr><td style="padding:22px 20px 20px;">
          <div style="font-size:10px;font-weight:700;letter-spacing:1px;color:#956e53;text-transform:uppercase;">CONTROL DE ASISTENCIA DOCENTE</div>
          <div style="font-size:21px;font-weight:800;line-height:1.25;color:#333039;margin-top:6px;">Reporte semanal de asistencia</div>
          <div style="font-size:12px;line-height:1.6;color:#69717b;margin-top:6px;">Del <strong>{desde:%d/%m/%Y}</strong> al <strong>{hasta:%d/%m/%Y}</strong></div>
          <div style="height:1px;background:#ece8e5;margin:18px 0;"></div>

          <div style="font-size:13px;line-height:1.6;color:#303943;">Estimado(a) <strong>{nombre_html}</strong>:</div>
          <div style="font-size:12px;line-height:1.65;color:#53606e;margin-top:7px;">
            Compartimos su resumen de asistencia de la semana. A continuación encontrará
            el resultado general y el detalle de cada día hábil.
          </div>

          <div style="font-size:13px;font-weight:800;color:#38333a;margin:18px 0 8px;">Resumen de la semana</div>
          <!-- Solo dos indicadores discretos: información secundaria en texto para ahorrar espacio. -->
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;table-layout:fixed;border-collapse:collapse;">
            <tr>
              <td width="50%" valign="top" style="padding:0 5px 0 0;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #e4e7e6;border-collapse:separate;border-radius:7px;background:#fafbfa;">
                  <tr><td style="padding:9px 12px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
                      <td style="font-size:11px;line-height:1.45;color:#50635b;">Asistencias</td>
                      <td align="right" style="font-size:19px;line-height:1.35;font-weight:800;color:#286747;">{asistio}</td>
                    </tr></table>
                  </td></tr>
                </table>
              </td>
              <td width="50%" valign="top" style="padding:0 0 0 5px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #e6e1e2;border-collapse:separate;border-radius:7px;background:#faf9f9;">
                  <tr><td style="padding:9px 12px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
                      <td style="font-size:11px;line-height:1.45;color:#6b4c54;">Cumplimiento</td>
                      <td align="right" style="font-size:19px;line-height:1.35;font-weight:800;color:#702f3c;">{cumplimiento_text}</td>
                    </tr></table>
                  </td></tr>
                </table>
              </td>
            </tr>
          </table>
          <div style="font-size:10.5px;line-height:1.7;color:#5e6974;padding:8px 1px 0;">
            <strong>Días evaluables:</strong> {dias_evaluables}
            <span style="color:#b6b6b6;"> &nbsp;&middot;&nbsp; </span>
            <strong>Faltas:</strong> {faltas}
            <span style="color:#b6b6b6;"> &nbsp;&middot;&nbsp; </span>
            <strong>Justificaciones:</strong> {justificaciones}
            <span style="color:#b6b6b6;"> &nbsp;&middot;&nbsp; </span>
            <strong>Días especiales:</strong> {dias_especiales}
          </div>
          <div style="font-size:10px;line-height:1.55;color:#7a838c;padding:4px 1px 0;">
            El porcentaje considera asistencias y justificaciones; los días especiales no se cuentan como falta.
          </div>

          <div style="font-size:13px;font-weight:800;color:#38333a;margin:21px 0 9px;">Detalle diario</div>
          <table width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;table-layout:fixed;border-collapse:collapse;border:1px solid #e6e8eb;font-family:Arial,Helvetica,sans-serif;">
            <thead>
              <tr bgcolor="#f8f7f6" style="background-color:#f8f7f6;text-align:left;">
                <th width="25%" style="padding:10px 9px;border-bottom:1px solid #dfe3e7;font-size:11px;color:#5a626a;">Día / Fecha</th>
                <th width="28%" style="padding:10px 6px;border-bottom:1px solid #dfe3e7;font-size:11px;color:#5a626a;">Estado</th>
                <th width="47%" style="padding:10px 9px;border-bottom:1px solid #dfe3e7;font-size:11px;color:#5a626a;">Detalle</th>
              </tr>
            </thead>
            <tbody>
              {''.join(rows_dias_html)}
            </tbody>
          </table>

          {bloque_plazo_html}
          <div style="font-size:11px;line-height:1.6;color:#66717d;margin-top:16px;">
            Si encuentra una inconsistencia, contacte al área administradora del sistema
            para solicitar la revisión correspondiente.
          </div>
        </td></tr>
        <tr><td bgcolor="#f8f7f6" style="background-color:#f8f7f6;border-top:1px solid #ece8e5;padding:14px 20px;text-align:center;">
          <div style="font-size:11px;font-weight:700;color:#574d53;line-height:1.5;">Proyecto Manhattan · Control de Asistencia Docente</div>
          <div style="font-size:10px;line-height:1.55;color:#7a818a;">Universidad Nacional de Ingeniería · Facultad de Ingeniería Civil</div>
          <div style="font-size:10px;line-height:1.55;color:#8f959b;margin-top:3px;">Mensaje automático · Por favor, no responder</div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
            """.strip()

            if dry_run:
                bloqueados += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"[DRY-RUN] to={email_prof} A={asistio} J={justificaciones} DE={dias_especiales} "
                        f"F={faltas} evaluables={dias_evaluables} cumpl={cumplimiento_text} "
                        f"registros={total_registros_relevantes} logo_url={'ok' if logo_url else 'no'}"
                    )
                )
                continue

            if not envio_habilitado:
                bloqueados += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"[BLOQUEADO] No se enviará correo a {email_prof}. "
                        f"A={asistio} J={justificaciones} DE={dias_especiales} F={faltas} "
                        f"evaluables={dias_evaluables} cumpl={cumplimiento_text} "
                        f"registros={total_registros_relevantes} logo_url={'ok' if logo_url else 'no'}"
                    )
                )
                continue

            try:
                self._brevo_send_email(email_prof, subject, body_text, body_html)
                enviados += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[SEND] to={email_prof} A={asistio} J={justificaciones} DE={dias_especiales} "
                        f"F={faltas} evaluables={dias_evaluables} cumpl={cumplimiento_text} "
                        f"registros={total_registros_relevantes} logo_url={'ok' if logo_url else 'no'}"
                    )
                )
            except Exception as e:
                errores += 1
                self.stderr.write(self.style.ERROR(f"[ERROR] Enviando a {email_prof}: {e}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"[DONE] Enviados: {enviados}. Bloqueados: {bloqueados}. Errores: {errores}. "
                f"Saltados (sin email): {saltados_sin_email}. Saltados (sin registros): {saltados_sin_registros}."
            )
        )