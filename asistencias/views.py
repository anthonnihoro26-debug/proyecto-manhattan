import re
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
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
# REGISTRO DE ASISTENCIA (BUSCAR -> ACEPTAR) (tu código)
# =========================================================
@login_required
def registrar_asistencia(request):
    profesor = None
    fecha_hora_str = ""

    if request.method == "POST":
        dni = request.POST.get("dni", "").strip()
        accion = request.POST.get("accion", "buscar").strip().lower()

        ahora = timezone.localtime(timezone.now())
        fecha_hora_str = ahora.strftime("%d/%m/%Y %H:%M")

        if accion == "buscar":
            try:
                profesor = Profesor.objects.get(dni=dni)
            except Profesor.DoesNotExist:
                messages.error(request, "❌ Profesor no encontrado")
                return redirect("registrar_asistencia")

            return render(request, "asistencias/registro.html", {
                "profesor": profesor,
                "fecha_hora_str": fecha_hora_str,
            })

        elif accion == "aceptar":
            try:
                profesor = Profesor.objects.get(dni=dni)
            except Profesor.DoesNotExist:
                messages.error(request, "❌ Profesor no encontrado")
                return redirect("registrar_asistencia")

            hoy = timezone.localdate()

            ya_existe = Asistencia.objects.filter(
                profesor=profesor,
                fecha_hora__date=hoy
            ).exists()

            if ya_existe:
                messages.warning(request, "⚠️ Ya registraste tu asistencia hoy.")
                return redirect("registrar_asistencia")

            Asistencia.objects.create(profesor=profesor)

            messages.success(request, "✅ Asistencia registrada correctamente")
            return redirect("registrar_asistencia")

    return render(request, "asistencias/registro.html", {
        "profesor": None,
        "fecha_hora_str": "",
    })


# =========================================================
# AJAX (opcional) (tu código)
# =========================================================
@login_required
def buscar_profesor(request):
    dni = request.GET.get("dni", "").strip()

    try:
        profesor = Profesor.objects.get(dni=dni)
        data = {
            "existe": True,
            "codigo": profesor.codigo,
            "nombres": profesor.nombres,
            "apellidos": profesor.apellidos,
            "condicion": profesor.condicion,
        }
    except Profesor.DoesNotExist:
        data = {"existe": False}

    return JsonResponse(data)


# =========================================================
# HISTORIAL (tu código)
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
# EXCEL (tu código)
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
# ✅ ESCÁNER CON CÁMARA - CÓDIGO DE BARRAS = DNI
# =========================================================
@ensure_csrf_cookie
@login_required
def scan_page(request):
    # Página que abre la cámara (no se escribe nada)
    return render(request, "asistencias/scan.html")


@require_POST
@login_required
def api_scan_asistencia(request):
    """
    Recibe POST (FormData) con dni=...
    Registra asistencia del profesor según DNI (8 dígitos)
    """
    raw = (request.POST.get("dni") or "").strip()

    # extraer dni de 8 digitos aunque venga con ruido
    m = re.search(r"\b(\d{8})\b", raw)
    dni = m.group(1) if m else re.sub(r"\D", "", raw)

    if not dni.isdigit() or len(dni) != 8:
        return JsonResponse({"ok": False, "msg": "DNI inválido (8 dígitos)."}, status=400)

    try:
        profesor = Profesor.objects.get(dni=dni)
    except Profesor.DoesNotExist:
        return JsonResponse({"ok": False, "msg": "Profesor no encontrado."}, status=404)

    hoy = timezone.localdate()
    if Asistencia.objects.filter(profesor=profesor, fecha_hora__date=hoy).exists():
        return JsonResponse({
            "ok": True,
            "duplicado": True,
            "msg": f"⚠️ {profesor.apellidos} {profesor.nombres} ya registró hoy."
        })

    Asistencia.objects.create(profesor=profesor)

    return JsonResponse({
        "ok": True,
        "duplicado": False,
        "dni": dni,
        "msg": f"✅ Asistencia registrada: {profesor.apellidos} {profesor.nombres}"
    })
def logout_view(request):
    logout(request)
    return redirect("login")  # o a donde quieras




