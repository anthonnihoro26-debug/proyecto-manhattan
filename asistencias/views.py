import os
import json
import re
import logging
from io import BytesIO
from PIL import Image as PILImage

from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import logout
from django.utils import timezone
from django.db.models import Q, Min
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django.core.paginator import Paginator
from django.contrib.staticfiles import finders
from django.db import transaction

from openpyxl.worksheet.worksheet import Worksheet
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.drawing.image import Image as XLImage

from .models import Profesor, Asistencia


logger = logging.getLogger(__name__)


# =========================================================
# ✅ HELPERS DE ROLES (GRUPOS)
# =========================================================
def _in_group(group_name: str):
    def check(user):
        return user.is_authenticated and user.groups.filter(name=group_name).exists()
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
    """
    ✅ Redirección según grupo:
    - SCANNER   -> /asistencia/scan/
    - HISTORIAL -> /asistencia/historial/
    """
    if request.user.groups.filter(name="SCANNER").exists():
        return redirect("scan_page")

    if request.user.groups.filter(name="HISTORIAL").exists():
        return redirect("historial_asistencias")

    logout(request)
    return redirect("login")


# =========================================================
# HISTORIAL (solo grupo HISTORIAL) ✅ KPIs + PAGINACIÓN
# =========================================================
@user_passes_test(_in_group("HISTORIAL"), login_url="login")
def historial_asistencias(request):
    qs = Asistencia.objects.select_related("profesor").order_by("-fecha_hora")

    q = request.GET.get("q", "").strip()
    desde = request.GET.get("desde", "").strip()
    hasta = request.GET.get("hasta", "").strip()
    condicion = request.GET.get("condicion", "").strip()

    ps = request.GET.get("ps", "25").strip()
    if ps not in ("25", "50", "100"):
        ps = "25"
    ps = int(ps)

    if q:
        qs = qs.filter(
            Q(profesor__dni__icontains=q) |
            Q(profesor__codigo__icontains=q) |
            Q(profesor__apellidos__icontains=q) |
            Q(profesor__nombres__icontains=q)
        )

    if condicion:
        qs = qs.filter(profesor__condicion__iexact=condicion)

    if desde:
        # ahora también funciona con "fecha" si existe
        qs = qs.filter(fecha_hora__date__gte=desde)
    if hasta:
        qs = qs.filter(fecha_hora__date__lte=hasta)

    total_registros = qs.count()
    docentes_unicos = qs.values("profesor_id").distinct().count()
    registros_n = qs.filter(profesor__condicion__iexact="N").count()
    registros_c = qs.filter(profesor__condicion__iexact="C").count()

    paginator = Paginator(qs, ps)
    page_number = request.GET.get("page", "1")
    page_obj = paginator.get_page(page_number)

    return render(request, "asistencias/historial.html", {
        "asistencias": page_obj.object_list,
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
    })


# =========================================================
# ✅ EXCEL (solo grupo HISTORIAL) ✅ RESTAURADO (Mejorado)
# =========================================================
@user_passes_test(_in_group("HISTORIAL"), login_url="login")
def exportar_reporte_excel(request):
    q = (request.GET.get("q") or "").strip()
    condicion = (request.GET.get("condicion") or "").strip()
    desde = (request.GET.get("desde") or "").strip()
    hasta = (request.GET.get("hasta") or "").strip()

    fecha_eval = parse_date(desde) if desde else None
    if not fecha_eval:
        fecha_eval = timezone.localdate()

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

    # ✅ Tomamos SOLO ENTRADA del día (más correcto)
    asistencias_del_dia = (
        Asistencia.objects
        .filter(fecha=fecha_eval, tipo="E")
        .values("profesor_id")
        .annotate(primera_hora=Min("fecha_hora"))
    )
    asistio_map = {x["profesor_id"]: x["primera_hora"] for x in asistencias_del_dia}

    wb = Workbook()
    ws: Worksheet = wb.active
    ws.title = "Reporte"

    navy = "0B1F3B"
    blue = "2563EB"
    gray_bg = "F3F4F6"
    ok_bg = "DCFCE7"
    bad_bg = "FEE2E2"
    text_dark = "0F172A"

    thin = Side(style="thin", color="CBD5E1")
    border_all = Border(left=thin, right=thin, top=thin, bottom=thin)

    for r in (1, 2):
        for c in range(1, 8):
            ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=gray_bg)

    ws.row_dimensions[1].height = 34
    ws.row_dimensions[2].height = 20
    ws.row_dimensions[3].height = 10
    ws.column_dimensions["A"].width = 16

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

    titulo = f"REPORTE DE ASISTENCIA — {fecha_eval.strftime('%d/%m/%Y')}"
    ws["B1"] = titulo
    ws.merge_cells("B1:G1")
    ws["B1"].font = Font(bold=True, size=16, color=navy)
    ws["B1"].alignment = Alignment(vertical="center")

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

    headers = ["DNI", "Código", "Docente", "Condición", "Estado", "Hora"]
    header_row = 5
    ws.append([])
    ws.append(headers)

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

    for p in profesores:
        dt = asistio_map.get(p.id)

        if dt:
            dt_local = timezone.localtime(dt)
            estado = "ASISTIÓ"
            hora = dt_local.strftime("%H:%M")
        else:
            estado = "FALTÓ"
            hora = ""

        docente = f"{(p.apellidos or '').strip()}, {(p.nombres or '').strip()}".strip().strip(",")

        row = [p.dni, p.codigo, docente, (p.condicion or "").upper(), estado, hora]
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
        estado_cell.fill = PatternFill("solid", fgColor=ok_bg if estado == "ASISTIÓ" else bad_bg)

        ws.cell(row=r, column=6).alignment = Alignment(horizontal="center", vertical="center")

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

    ws.freeze_panes = f"A{data_start}"

    widths = {"A": 14, "B": 14, "C": 40, "D": 12, "E": 12, "F": 10}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

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
# ✅ API SCAN PRO (solo grupo SCANNER) ✅ ENTRADA/SALIDA + BLOQUEO
# =========================================================
@csrf_protect
@require_POST
@user_passes_test(_in_group("SCANNER"), login_url="login")
def api_scan_asistencia(request):
    # 1) leer code
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

    # 2) extraer dni
    dni = _extract_dni(raw)
    if not (dni.isdigit() and len(dni) == 8):
        return JsonResponse({"ok": False, "msg": "DNI inválido (debe ser 8 dígitos)"}, status=400)

    # 3) buscar profesor
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

    # 4) transacción anti doble-scan
    with transaction.atomic():
        # bloquea registros de ese profesor/día mientras decide
        qs = (Asistencia.objects
              .select_for_update()
              .filter(profesor=profesor, fecha=hoy)
              .order_by("fecha_hora"))

        tipos_hoy = set(qs.values_list("tipo", flat=True))  # {"E","S"}

        if "E" not in tipos_hoy:
            tipo = "E"
            accion = "entrada"
        elif "S" not in tipos_hoy:
            tipo = "S"
            accion = "salida"
        else:
            logger.info("DUPLICADO dni=%s hoy=%s user=%s ip=%s", dni, hoy, request.user.username, ip)
            return JsonResponse({
                "ok": True,
                "duplicado": True,
                "accion": "ninguna",
                "msg": f"⚠️ Ya registró ENTRADA y SALIDA hoy: {profesor.apellidos} {profesor.nombres}",
                "profesor": payload_prof,
            }, status=200)

        # crea registro
        a = Asistencia.objects.create(
            profesor=profesor,
            fecha=hoy,
            fecha_hora=now,
            tipo=tipo,
            registrado_por=request.user,
            ip=ip,
            user_agent=ua,
        )

    logger.info("OK %s dni=%s hoy=%s user=%s ip=%s", accion, dni, hoy, request.user.username, ip)

    return JsonResponse({
        "ok": True,
        "duplicado": False,
        "accion": accion,  # "entrada" o "salida"
        "msg": f"✅ {accion.upper()} registrada: {profesor.apellidos} {profesor.nombres}",
        "profesor": payload_prof,
        "asistencia": {
            "id": a.id,
            "tipo": a.tipo,
            "fecha": str(a.fecha),
            "fecha_hora": a.fecha_hora.isoformat(),
        }
    }, status=201)
