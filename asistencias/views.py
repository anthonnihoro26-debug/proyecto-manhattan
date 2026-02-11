import os
import json
import re
import logging
from datetime import timedelta
from io import BytesIO, StringIO

from PIL import Image as PILImage
from datetime import datetime, time
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required, user_passes_test 
from django.contrib.auth import logout
from django.contrib import messages

from django.utils import timezone
from django.db.models import Q, Min
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect, csrf_exempt
from django.core.paginator import Paginator
from django.contrib.staticfiles import finders
from django.db import transaction
from django.core.management import call_command
from types import SimpleNamespace

from openpyxl.worksheet.worksheet import Worksheet
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.drawing.image import Image as XLImage

from .models import Profesor, Asistencia, JustificacionAsistencia


logger = logging.getLogger(__name__)


# =========================================================
# ✅ HELPERS DE ROLES (GRUPOS)
# =========================================================
def _in_group(group_name: str):
    def check(user):
        return user.is_authenticated and user.groups.filter(name=group_name).exists()
    return check


def _in_any_group(*group_names: str):
    def check(user):
        return user.is_authenticated and user.groups.filter(name__in=list(group_names)).exists()
    return check




def _get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _extract_dni(raw: str) -> str:
    raw = (raw or "").strip()

    m = re.search(r"(\d{8})", raw)
    if m:
        return m.group(1)

    digits = re.sub(r"\D+", "", raw)
    if len(digits) == 7:
        return digits.zfill(8)
    if len(digits) >= 8:
        return digits[-8:]
    return ""


def _read_code_from_request(request) -> str:
    ctype = (request.content_type or "").lower()

    if "application/json" in ctype:
        body = (request.body or b"").decode("utf-8").strip()
        if not body:
            return ""
        data = json.loads(body)
        return (data.get("code") or data.get("dni") or "").strip()

    return (request.POST.get("code") or request.POST.get("dni") or "").strip()


# =========================================================
# ✅ POST LOGIN REDIRECT
# =========================================================
@login_required
def post_login_redirect(request):
    user = request.user

    if user.groups.filter(name="SCANNER").exists():
        return redirect("scan_page")

    if user.groups.filter(name="HISTORIAL").exists():
        return redirect("historial_asistencias")

    if user.groups.filter(name="JUSTIFICACIONES").exists():
        return redirect("panel_justificaciones")

    logout(request)
    return redirect("login")


# =========================================================
# HISTORIAL (solo grupo HISTORIAL) ✅ KPIs + PAGINACIÓN
# =========================================================
def historial_asistencias(request):
    q = request.GET.get("q", "").strip()
    desde = request.GET.get("desde", "").strip()
    hasta = request.GET.get("hasta", "").strip()
    condicion = request.GET.get("condicion", "").strip()

    ps = request.GET.get("ps", "25").strip()
    if ps not in ("25", "50", "100"):
        ps = "25"
    ps = int(ps)

    # ✅ Fecha para regresar a justificaciones (si vienes desde ese panel)
    fecha_just = request.session.get("just_fecha")
    if not fecha_just:
        fecha_just = (timezone.localdate() - timezone.timedelta(days=1)).strftime("%Y-%m-%d")

    # ✅ Mostrar botón "Ir a justificaciones" solo a usuarios que pertenecen al grupo
    puede_volver_just = request.user.is_authenticated and request.user.groups.filter(name="JUSTIFICACIONES").exists()

    # =========================
    # 1) ASISTENCIAS (solo ENTRADA)
    # =========================
    asist_qs = (
        Asistencia.objects
        .select_related("profesor")
        .filter(tipo="E")   # ✅ NO salida
    )

    if q:
        asist_qs = asist_qs.filter(
            Q(profesor__dni__icontains=q) |
            Q(profesor__codigo__icontains=q) |
            Q(profesor__apellidos__icontains=q) |
            Q(profesor__nombres__icontains=q)
        )
    if condicion:
        asist_qs = asist_qs.filter(profesor__condicion__iexact=condicion)
    if desde:
        asist_qs = asist_qs.filter(fecha_hora__date__gte=desde)
    if hasta:
        asist_qs = asist_qs.filter(fecha_hora__date__lte=hasta)

    # =========================
    # 2) JUSTIFICACIONES
    # =========================
    just_qs = (
        JustificacionAsistencia.objects
        .select_related("profesor")
        .all()
    )

    if q:
        just_qs = just_qs.filter(
            Q(profesor__dni__icontains=q) |
            Q(profesor__codigo__icontains=q) |
            Q(profesor__apellidos__icontains=q) |
            Q(profesor__nombres__icontains=q)
        )
    if condicion:
        just_qs = just_qs.filter(profesor__condicion__iexact=condicion)
    if desde:
        just_qs = just_qs.filter(fecha__gte=desde)
    if hasta:
        just_qs = just_qs.filter(fecha__lte=hasta)

    # =========================
    # 3) UNIR EN UNA LISTA "EVENTOS"
    # =========================
    events = []

    # asistencias => evento ASISTIÓ
    for a in asist_qs:
        events.append({
            "kind": "A",
            "profesor": a.profesor,
            "estado": "ASISTIÓ",
            "fecha_hora": a.fecha_hora,
            "codigo": a.profesor.codigo,
            "condicion": a.profesor.condicion,
            "detalle": "",
        })

    # justificaciones => evento JUSTIFICADO (DM/C/P/O)
    for j in just_qs:
        dt = datetime.combine(j.fecha, time(0, 0, 0))
        dt = timezone.make_aware(dt, timezone.get_current_timezone())

        events.append({
            "kind": "J",
            "profesor": j.profesor,
            "estado": f"JUSTIFICADO ({j.tipo})",
            "fecha_hora": dt,
            "codigo": j.profesor.codigo,
            "condicion": j.profesor.condicion,
            "detalle": j.detalle or "",
        })

    # ordenar por fecha/hora desc
    events.sort(key=lambda x: x["fecha_hora"], reverse=True)

    # =========================
    # 4) KPIs + PAGINACIÓN
    # =========================
    total_registros = len(events)
    docentes_unicos = len({e["profesor"].id for e in events})
    registros_n = sum(1 for e in events if (e.get("condicion") or "").upper() == "N")
    registros_c = sum(1 for e in events if (e.get("condicion") or "").upper() == "C")

    paginator = Paginator(events, ps)
    page_number = request.GET.get("page", "1")
    page_obj = paginator.get_page(page_number)

    return render(request, "asistencias/historial.html", {
        "items": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,

        "q": q,
        "desde": desde,
        "hasta": hasta,
        "condicion": condicion,
        "ps": ps,

        "total_registros": total_registros,
        "docentes_unicos": docentes_unicos,
        "registros_n": registros_n,
        "registros_c": registros_c,

        # ✅ para que el botón del HTML funcione
        "puede_volver_just": puede_volver_just,
        "fecha_just": fecha_just,
    })



# =========================================================
# ✅ EXCEL (solo grupo HISTORIAL)
# ✅ AHORA: ASISTIÓ / JUSTIFICADO (DM) / FALTÓ
# =========================================================
@user_passes_test(_in_any_group("HISTORIAL", "JUSTIFICACIONES"), login_url="login")


def exportar_reporte_excel(request):
    q = (request.GET.get("q") or "").strip()
    condicion = (request.GET.get("condicion") or "").strip()
    desde = (request.GET.get("desde") or "").strip()
    hasta = (request.GET.get("hasta") or "").strip()

    # ✅ Fecha evaluada (si mandan "desde", usa esa; si no, hoy)
    fecha_eval = parse_date(desde) if desde else None
    if not fecha_eval:
        fecha_eval = timezone.localdate()

    # ✅ Profesores filtrados
    profesores = Profesor.objects.all().order_by("apellidos", "nombres")

    if q:
        profesores = profesores.filter(
            Q(dni__icontains=q) |
            Q(codigo__icontains=q) |
            Q(apellidos__icontains=q) |
            Q(nombres__icontains=q)
        )

    if condicion:
        profesores = profesores.filter(condicion__iexact=condicion)

    # ✅ Asistencias del día: SOLO ENTRADA (tipo="E")
    asistencias_del_dia = (
        Asistencia.objects
        .filter(fecha=fecha_eval, tipo="E")
        .values("profesor_id")
        .annotate(primera_hora=Min("fecha_hora"))
    )
    asistio_map = {x["profesor_id"]: x["primera_hora"] for x in asistencias_del_dia}

    # ✅ Justificaciones del día
    justificados_del_dia = (
        JustificacionAsistencia.objects
        .filter(fecha=fecha_eval)
        .values("profesor_id", "tipo")
    )
    just_map = {x["profesor_id"]: x["tipo"] for x in justificados_del_dia}

    # =========================
    # ✅ EXCEL SETUP
    # =========================
    wb = Workbook()
    ws: Worksheet = wb.active
    ws.title = "Reporte"

    navy = "0B1F3B"
    blue = "2563EB"
    gray_bg = "F3F4F6"
    ok_bg = "DCFCE7"
    bad_bg = "FEE2E2"
    info_bg = "E0E7FF"
    text_dark = "0F172A"

    thin = Side(style="thin", color="CBD5E1")
    border_all = Border(left=thin, right=thin, top=thin, bottom=thin)

    # fondo header
    for r in (1, 2):
        for c in range(1, 8):
            ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=gray_bg)

    ws.row_dimensions[1].height = 34
    ws.row_dimensions[2].height = 20
    ws.row_dimensions[3].height = 10
    ws.column_dimensions["A"].width = 16

    # Logo
    logo_path = finders.find("asistencias/img/uni_logo.png")
    if logo_path:
        with PILImage.open(logo_path) as im:
            ow, oh = im.size

        target_h = 95
        target_w = int(ow * (target_h / oh))
        img = XLImage(logo_path)
        img.height = target_h
        img.width = target_w
        img.anchor = "A1"
        ws.add_image(img)

        ws.row_dimensions[1].height = 44
        ws.row_dimensions[2].height = 18
        ws.row_dimensions[3].height = 10
        ws.column_dimensions["A"].width = 18

    # Título
    titulo = f"REPORTE DE ASISTENCIA — {fecha_eval.strftime('%d/%m/%Y')}"
    ws["B1"] = titulo
    ws.merge_cells("B1:G1")
    ws["B1"].font = Font(bold=True, size=16, color=navy)
    ws["B1"].alignment = Alignment(vertical="center")

    # Filtros (info)
    filtros_txt = []
    if q:
        filtros_txt.append(f"Búsqueda: {q}")
    if condicion:
        filtros_txt.append(f"Condición: {condicion.upper()}")
    if desde:
        filtros_txt.append(f"Desde: {desde}")
    if hasta:
        filtros_txt.append(f"Hasta: {hasta}")

    ws["B2"] = " | ".join(filtros_txt) if filtros_txt else "Filtros: (sin filtros)"
    ws.merge_cells("B2:G2")
    ws["B2"].font = Font(size=11, color="334155")
    ws["B2"].alignment = Alignment(vertical="center")

    # =========================
    # ✅ TABLA (HEADERS + DATA)  (FIX openpyxl warning)
    # =========================
    headers = ["DNI", "Código", "Docente", "Condición", "Estado", "Hora"]

    # fila de separación
    ws.append([])

    # escribimos headers y guardamos la fila real
    ws.append([str(h) for h in headers])
    header_row = ws.max_row

    header_fill = PatternFill("solid", fgColor=blue)
    header_font = Font(bold=True, color="FFFFFF")

    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=header_row, column=col_idx)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = border_all

    ws.row_dimensions[header_row].height = 22
    data_start = header_row + 1

    # datos
    for p in profesores:
        dt = asistio_map.get(p.id)
        jt = just_map.get(p.id)  # DM/C/P/O

        if dt:
            dt_local = timezone.localtime(dt)
            estado = "ASISTIÓ"
            hora = dt_local.strftime("%H:%M")
        elif jt:
            estado = f"JUSTIFICADO ({jt})"
            hora = ""
        else:
            estado = "FALTÓ"
            hora = ""

        docente = f"{(p.apellidos or '').strip()}, {(p.nombres or '').strip()}".strip().strip(",")

        # ✅ todo string para evitar warnings
        row = [
            str(p.dni),
            str(p.codigo or ""),
            str(docente),
            str((p.condicion or "").upper()),
            str(estado),
            str(hora),
        ]
        ws.append(row)
        r = ws.max_row

        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=r, column=col)
            cell.border = border_all
            cell.alignment = Alignment(vertical="center")

        ws.cell(row=r, column=4).alignment = Alignment(horizontal="center", vertical="center")

        estado_cell = ws.cell(row=r, column=5)
        estado_cell.font = Font(bold=True, color=text_dark)
        estado_cell.alignment = Alignment(horizontal="center", vertical="center")

        if estado.startswith("ASISTIÓ"):
            estado_cell.fill = PatternFill("solid", fgColor=ok_bg)
        elif estado.startswith("JUSTIFICADO"):
            estado_cell.fill = PatternFill("solid", fgColor=info_bg)
        else:
            estado_cell.fill = PatternFill("solid", fgColor=bad_bg)

        ws.cell(row=r, column=6).alignment = Alignment(horizontal="center", vertical="center")

    # Tabla estilo Excel
    last_row = ws.max_row
    if last_row >= data_start:
        table_ref = f"A{header_row}:F{last_row}"
        table = Table(displayName="TablaReporte", ref=table_ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium9",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False
        )
        ws.add_table(table)

    # Freeze
    ws.freeze_panes = f"A{data_start}"

    # Anchos
    widths = {"A": 14, "B": 14, "C": 40, "D": 12, "E": 22, "F": 10}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    # Respuesta
    filename = f"reporte_asistencia_{fecha_eval.strftime('%Y-%m-%d')}.xlsx"
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    response = HttpResponse(
        bio.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# =========================================================
# ✅ SCAN PAGE (solo grupo SCANNER)
# =========================================================
@ensure_csrf_cookie
@user_passes_test(_in_group("SCANNER"), login_url="login")
def scan_page(request):
    return render(request, "asistencias/scan.html")


# =========================================================
# ✅ API SCAN PRO (solo grupo SCANNER) ✅ SOLO ENTRADA + BLOQUEO
# =========================================================
@csrf_protect
@require_POST
@user_passes_test(_in_group("SCANNER"), login_url="login")
def api_scan_asistencia(request):
    try:
        raw = _read_code_from_request(request)
    except UnicodeDecodeError:
        return JsonResponse({"ok": False, "msg": "Encoding inválido (UTF-8)"}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "msg": "JSON inválido"}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "msg": "Error leyendo el request"}, status=400)

    if not raw:
        return JsonResponse({"ok": False, "msg": "No llegó ningún código/DNI"}, status=400)

    dni = _extract_dni(raw)
    if not (dni.isdigit() and len(dni) == 8):
        return JsonResponse({"ok": False, "msg": "DNI inválido (debe ser 8 dígitos)"}, status=400)

    try:
        profesor = Profesor.objects.get(dni=dni)
    except Profesor.DoesNotExist:
        return JsonResponse({"ok": False, "msg": "Profesor no encontrado", "dni": dni}, status=404)

    hoy = timezone.localdate()
    now = timezone.now()

    payload_prof = {
        "dni": profesor.dni,
        "codigo": profesor.codigo,
        "apellidos": profesor.apellidos,
        "nombres": profesor.nombres,
        "condicion": profesor.condicion,
    }

    ip = _get_client_ip(request)
    ua = (request.META.get("HTTP_USER_AGENT") or "")[:255]

    with transaction.atomic():
        qs = (Asistencia.objects
              .select_for_update()
              .filter(profesor=profesor, fecha=hoy, tipo="E")
              .order_by("fecha_hora"))

        if qs.exists():
            logger.info("DUPLICADO entrada dni=%s hoy=%s user=%s ip=%s",
                        dni, hoy, request.user.username, ip)
            return JsonResponse({
                "ok": True,
                "duplicado": True,
                "accion": "ninguna",
                "msg": f"⚠️ Ya registró ENTRADA hoy: {profesor.apellidos} {profesor.nombres}",
                "profesor": payload_prof,
            }, status=200)

        a = Asistencia.objects.create(
            profesor=profesor,
            fecha=hoy,
            fecha_hora=now,
            tipo="E",
            registrado_por=request.user,
            ip=ip,
            user_agent=ua,
        )

    logger.info("OK entrada dni=%s hoy=%s user=%s ip=%s", dni, hoy, request.user.username, ip)

    return JsonResponse({
        "ok": True,
        "duplicado": False,
        "accion": "entrada",
        "msg": f"✅ ENTRADA registrada: {profesor.apellidos} {profesor.nombres}",
        "profesor": payload_prof,
        "asistencia": {
            "id": a.id,
            "tipo": a.tipo,
            "fecha": str(a.fecha),
            "fecha_hora": a.fecha_hora.isoformat(),
        }
    }, status=201)


# =========================================================
# ✅ CRON PRIVADO (Render Free + cron-job.org)
# =========================================================
@csrf_exempt
@require_GET
def trigger_reporte_asistencia(request):
    token = (request.GET.get("token") or "").strip()
    secret = (getattr(settings, "REPORT_TRIGGER_TOKEN", "") or "").strip()

    if not secret or token != secret:
        return HttpResponseForbidden("Forbidden")

    out = StringIO()
    call_command("enviar_reporte_asistencia", stdout=out, stderr=out)

    texto = out.getvalue()

    return JsonResponse({
        "ok": True,
        "msg": "Reporte ejecutado",
        "output": texto,
    })


# =========================================================
# ✅ REGISTRO MANUAL (solo grupo HISTORIAL)
# Buscar DNI -> Mostrar profesor -> Confirmar y registrar
# =========================================================
@user_passes_test(_in_group("HISTORIAL"), login_url="login")


def registro_manual(request):
    profesor = None
    fecha_hora_str = timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M:%S")

    if request.method == "POST":
        accion = (request.POST.get("accion") or "").strip().lower()
        raw_dni = (request.POST.get("dni") or "").strip()

        dni = _extract_dni(raw_dni)
        if not (dni.isdigit() and len(dni) == 8):
            messages.error(request, "DNI inválido (debe ser 8 dígitos).")
            return render(request, "asistencias/registro_manual.html", {
                "profesor": None,
                "fecha_hora_str": fecha_hora_str,
            })

        if accion == "buscar":
            try:
                profesor = Profesor.objects.get(dni=dni)
                messages.info(request, "Docente encontrado. Verifica y confirma para registrar.")
            except Profesor.DoesNotExist:
                messages.error(request, f"No se encontró docente con DNI {dni}.")
                profesor = None

        elif accion == "aceptar":
            try:
                profesor = Profesor.objects.get(dni=dni)
            except Profesor.DoesNotExist:
                messages.error(request, f"No se encontró docente con DNI {dni}.")
                profesor = None
            else:
                hoy = timezone.localdate()
                now = timezone.now()

                ip = _get_client_ip(request)
                ua = (request.META.get("HTTP_USER_AGENT") or "")[:255]

                with transaction.atomic():
                    qs = (Asistencia.objects
                          .select_for_update()
                          .filter(profesor=profesor, fecha=hoy, tipo="E")
                          .order_by("fecha_hora"))

                    if qs.exists():
                        ya = qs.first()
                        ya_local = timezone.localtime(ya.fecha_hora).strftime("%H:%M")
                        messages.warning(
                            request,
                            f"⚠️ Ya registró ENTRADA hoy ({ya_local}): {profesor.apellidos} {profesor.nombres}"
                        )
                    else:
                        Asistencia.objects.create(
                            profesor=profesor,
                            fecha=hoy,
                            fecha_hora=now,
                            tipo="E",
                            registrado_por=request.user,
                            ip=ip,
                            user_agent=ua,
                        )
                        messages.success(
                            request,
                            f"✅ ENTRADA registrada: {profesor.apellidos} {profesor.nombres}"
                        )

                fecha_hora_str = timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M:%S")

        else:
            messages.error(request, "Acción inválida.")
            profesor = None

    return render(request, "asistencias/registro_manual.html", {
        "profesor": profesor,
        "fecha_hora_str": fecha_hora_str,
    })


# =========================================================
# ✅ PANEL JUSTIFICACIONES (solo grupo JUSTIFICACIONES)
# Por defecto muestra AYER (para justificar al día siguiente)
# =========================================================
@user_passes_test(_in_group("JUSTIFICACIONES"), login_url="login")
def panel_justificaciones(request):
    fecha_str = (request.GET.get("fecha") or "").strip()
    fecha = parse_date(fecha_str) if fecha_str else (timezone.localdate() - timedelta(days=1))

    # ✅ guardamos la fecha para que al ir a Historial, pueda regresar a esta misma fecha
    request.session["just_fecha"] = fecha.strftime("%Y-%m-%d")

    q = (request.GET.get("q") or "").strip()

    profesores = Profesor.objects.all().order_by("apellidos", "nombres")
    if q:
        profesores = profesores.filter(
            Q(dni__icontains=q) |
            Q(codigo__icontains=q) |
            Q(apellidos__icontains=q) |
            Q(nombres__icontains=q)
        )

    asistio_ids = set(
        Asistencia.objects
        .filter(fecha=fecha, tipo="E")  # ✅ solo ENTRADA
        .values_list("profesor_id", flat=True)
    )

    just_qs = JustificacionAsistencia.objects.filter(fecha=fecha).select_related("profesor")
    just_map = {j.profesor_id: j for j in just_qs}

    rows = []
    for p in profesores:
        j = just_map.get(p.id)
        if p.id in asistio_ids:
            estado = "ASISTIÓ"
        elif j:
            estado = f"JUSTIFICADO ({j.tipo})"
        else:
            estado = "FALTÓ"

        rows.append({
            "profesor": p,
            "estado": estado,
            "justificacion": j
        })

    return render(request, "asistencias/justificaciones.html", {
        "fecha": fecha,
        "q": q,
        "rows": rows,
    })


# =========================================================
# ✅ SET / CLEAR JUSTIFICACIÓN (solo JUSTIFICACIONES)
# =========================================================
@require_POST
@user_passes_test(_in_group("JUSTIFICACIONES"), login_url="login")
def set_justificacion(request):
    accion = (request.POST.get("accion") or "").strip().lower()
    profesor_id = (request.POST.get("profesor_id") or "").strip()
    fecha_str = (request.POST.get("fecha") or "").strip()
    tipo = (request.POST.get("tipo") or "DM").strip().upper()
    detalle = (request.POST.get("detalle") or "").strip()

    fecha = parse_date(fecha_str)
    if not fecha:
        messages.error(request, "Fecha inválida.")
        return redirect(f"/asistencia/justificaciones/?fecha={fecha_str}" if fecha_str else "/asistencia/justificaciones/")

    try:
        profesor = Profesor.objects.get(id=profesor_id)
    except Profesor.DoesNotExist:
        messages.error(request, "Profesor no encontrado.")
        return redirect(f"/asistencia/justificaciones/?fecha={fecha_str}")

    tipo_ok = tipo if tipo in ("DM", "C", "P", "O") else "DM"

    ip = _get_client_ip(request)
    ua = (request.META.get("HTTP_USER_AGENT") or "")[:255]

    # ✅ Si ya asistió ese día, no tiene sentido justificarlo
    if Asistencia.objects.filter(profesor=profesor, fecha=fecha, tipo="E").exists():
        messages.warning(request, f"⚠️ {profesor.apellidos} {profesor.nombres} ya tiene ASISTENCIA ese día. No se registró justificación.")
        return redirect(f"/asistencia/justificaciones/?fecha={fecha_str}")

    if accion == "set":
        with transaction.atomic():
            # 1) ✅ guarda/actualiza en tu tabla JustificacionAsistencia (como ya hacías)
            obj, created = JustificacionAsistencia.objects.update_or_create(
                profesor=profesor,
                fecha=fecha,
                defaults={
                    "tipo": tipo_ok,
                    "detalle": detalle,
                    "actualizado_por": request.user,
                    "creado_por": request.user,
                }
            )

            # 2) ✅ NUEVO: también registra en Asistencia tipo="J" para que salga en el historial
            Asistencia.objects.update_or_create(
                profesor=profesor,
                fecha=fecha,
                tipo="J",
                defaults={
                    "fecha_hora": timezone.now(),
                    "motivo": tipo_ok,
                    "detalle": detalle,
                    "registrado_por": request.user,
                    "ip": ip,
                    "user_agent": ua,
                }
            )

        if created:
            messages.success(request, f"✅ Justificación registrada para {profesor.apellidos} {profesor.nombres}.")
        else:
            messages.success(request, f"✅ Justificación actualizada para {profesor.apellidos} {profesor.nombres}.")

    elif accion == "clear":
        with transaction.atomic():
            JustificacionAsistencia.objects.filter(profesor=profesor, fecha=fecha).delete()
            # ✅ NUEVO: borra también del historial (Asistencia tipo J)
            Asistencia.objects.filter(profesor=profesor, fecha=fecha, tipo="J").delete()

        messages.warning(request, f"🗑️ Justificación eliminada para {profesor.apellidos} {profesor.nombres}.")

    else:
        messages.error(request, "Acción inválida.")

    return redirect(f"/asistencia/justificaciones/?fecha={fecha_str}")