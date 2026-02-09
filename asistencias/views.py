import json
import re

from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Q, Min
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo

from .models import Profesor, Asistencia


# =========================================================
# HISTORIAL
# =========================================================
@login_required
def historial_asistencias(request):
    qs = Asistencia.objects.select_related("profesor").order_by("-fecha_hora")

    q = request.GET.get("q", "").strip()
    desde = request.GET.get("desde", "").strip()
    hasta = request.GET.get("hasta", "").strip()
    condicion = request.GET.get("condicion", "").strip()

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
        qs = qs.filter(fecha_hora__date__gte=desde)
    if hasta:
        qs = qs.filter(fecha_hora__date__lte=hasta)

    return render(request, "asistencias/historial.html", {
        "asistencias": qs,
        "q": q,
        "desde": desde,
        "hasta": hasta,
        "condicion": condicion,
    })


# =========================================================
# EXCEL
# =========================================================
@login_required
def exportar_reporte_excel(request):
    desde = request.GET.get("desde", "").strip()
    fecha_eval = parse_date(desde) if desde else None
    if not fecha_eval:
        fecha_eval = timezone.localdate()

    profesores = Profesor.objects.all().order_by("apellidos", "nombres")

    q = request.GET.get("q", "").strip()
    condicion = request.GET.get("condicion", "").strip()

    if q:
        profesores = profesores.filter(
            Q(dni__icontains=q) |
            Q(codigo__icontains=q) |
            Q(apellidos__icontains=q) |
            Q(nombres__icontains=q)
        )

    if condicion:
        profesores = profesores.filter(condicion__iexact=condicion)

    asistencias_del_dia = (
        Asistencia.objects
        .filter(fecha_hora__date=fecha_eval)
        .values("profesor_id")
        .annotate(primera_hora=Min("fecha_hora"))
    )
    asistio_map = {x["profesor_id"]: x["primera_hora"] for x in asistencias_del_dia}

    wb = Workbook()
    ws = wb.active
    ws.title = "Reporte"

    titulo = f"REPORTE DE ASISTENCIA - {fecha_eval.strftime('%d/%m/%Y')}"
    ws["A1"] = titulo
    ws.merge_cells("A1:H1")
    ws["A1"].font = Font(bold=True, size=14)
    ws["A1"].alignment = Alignment(horizontal="center")

    headers = ["#", "DNI", "Código", "Apellidos", "Nombres", "Condición", "Estado", "Hora"]
    ws.append(headers)

    header_fill = PatternFill("solid", fgColor="1F6FEB")
    header_font = Font(bold=True, color="FFFFFF")
    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=2, column=col_idx)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center")

    fill_ok = PatternFill("solid", fgColor="D1FAE5")
    fill_falta = PatternFill("solid", fgColor="FEE2E2")

    for i, p in enumerate(profesores, start=1):
        dt = asistio_map.get(p.id)

        if dt:
            dt_local = timezone.localtime(dt)
            estado = "ASISTIÓ"
            hora = dt_local.strftime("%H:%M")
        else:
            estado = "FALTÓ"
            hora = ""

        ws.append([i, p.dni, p.codigo, p.apellidos, p.nombres, p.condicion, estado, hora])

        estado_cell = ws.cell(row=ws.max_row, column=7)
        estado_cell.alignment = Alignment(horizontal="center")
        estado_cell.font = Font(bold=True)
        estado_cell.fill = fill_ok if estado == "ASISTIÓ" else fill_falta

        ws.cell(row=ws.max_row, column=8).alignment = Alignment(horizontal="center")

    last_row = ws.max_row
    table = Table(displayName="TablaReporte", ref=f"A2:H{last_row}")
    style = TableStyleInfo(
        name="TableStyleMedium9",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False
    )
    table.tableStyleInfo = style
    ws.add_table(table)

    for col in range(1, len(headers) + 1):
        max_len = 0
        col_letter = get_column_letter(col)
        for cell in ws[col_letter]:
            if cell.value is not None:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max_len + 2, 40)

    filename = f"reporte_asistencia_{fecha_eval.strftime('%Y-%m-%d')}.xlsx"
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


# =========================================================
# ✅ SCAN PAGE
# =========================================================
@ensure_csrf_cookie
@login_required
def scan_page(request):
    return render(request, "asistencias/scan.html")


# =========================================================
# ✅ API SCAN (acepta JSON o form) + 1 vez por día
# =========================================================
@require_POST
@login_required
def api_scan_asistencia(request):
    """
    Soporta:
      - JSON: {"code": "..."} o {"dni": "..."}
      - FORM: code=... o dni=...
    Extrae 8 dígitos aunque venga: "DNI: 10041279"
    Responde SIEMPRE JSON.
    """

    # ✅ Si usas login_required en otra parte y te redirige,
    # mejor responder JSON 401 aquí para que el front no reviente.
    if not request.user.is_authenticated:
        return JsonResponse(
            {"ok": False, "msg": "No autenticado. Vuelve a iniciar sesión."},
            status=401
        )

    # 1) leer raw desde JSON o POST
    raw = ""
    ctype = (request.content_type or "").lower()

    if "application/json" in ctype:
        try:
            body = (request.body or b"").decode("utf-8").strip()
            if not body:
                return JsonResponse({"ok": False, "msg": "Body vacío (JSON)"},
                                    status=400)
            data = json.loads(body)
            raw = (data.get("code") or data.get("dni") or "").strip()
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "msg": "JSON inválido"}, status=400)
        except UnicodeDecodeError:
            return JsonResponse({"ok": False, "msg": "Encoding inválido (UTF-8)"}, status=400)
        except Exception:
            return JsonResponse({"ok": False, "msg": "Error leyendo JSON"}, status=400)
    else:
        raw = (request.POST.get("code") or request.POST.get("dni") or "").strip()

    if not raw:
        return JsonResponse({"ok": False, "msg": "No llegó ningún código/DNI"}, status=400)

    # 2) extraer DNI (8 dígitos) desde cualquier texto
    m = re.search(r"(\d{8})", raw)
    dni = m.group(1) if m else ""

    if not dni.isdigit() or len(dni) != 8:
        return JsonResponse({"ok": False, "msg": "DNI inválido (debe ser 8 dígitos)"}, status=400)

    # 3) buscar profesor
    try:
        profesor = Profesor.objects.get(dni=dni)
    except Profesor.DoesNotExist:
        return JsonResponse({"ok": False, "msg": "Profesor no encontrado"}, status=404)

    # 4) evitar doble registro por día
    hoy = timezone.localdate()
    ya_existe = Asistencia.objects.filter(
        profesor=profesor,
        fecha_hora__date=hoy
    ).exists()

    if ya_existe:
        return JsonResponse({
            "ok": True,
            "duplicado": True,
            "msg": f"⚠️ Ya registró hoy: {profesor.apellidos} {profesor.nombres}",
            "dni": dni
        })

    Asistencia.objects.create(profesor=profesor)

    return JsonResponse({
        "ok": True,
        "duplicado": False,
        "msg": f"✅ Asistencia registrada: {profesor.apellidos} {profesor.nombres}",
        "dni": dni
    })



