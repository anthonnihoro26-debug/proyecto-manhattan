from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q, Min
from django.utils.dateparse import parse_date

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo

from .models import Profesor, Asistencia


# =========================================================
# REGISTRO DE ASISTENCIA (BUSCAR -> ACEPTAR)
# =========================================================
@login_required
def registrar_asistencia(request):
    profesor = None
    fecha_hora_str = ""

    if request.method == "POST":
        dni = request.POST.get("dni", "").strip()
        accion = request.POST.get("accion", "buscar").strip().lower()

        # Hora actual con zona horaria (Lima)
        ahora = timezone.localtime(timezone.now())
        fecha_hora_str = ahora.strftime("%d/%m/%Y %H:%M")

        # 1) BUSCAR: solo muestra datos del profesor (NO guarda)
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

        # 2) ACEPTAR: registra asistencia (evita doble por día)
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

            # ✅ Tu modelo guarda fecha_hora automáticamente (default=timezone.now)
            Asistencia.objects.create(profesor=profesor)

            messages.success(request, "✅ Asistencia registrada correctamente")
            return redirect("registrar_asistencia")

    # GET normal
    return render(request, "asistencias/registro.html", {
        "profesor": None,
        "fecha_hora_str": "",
    })


# =========================================================
# AJAX (opcional)
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
# HISTORIAL (tabla con filtros)
# =========================================================
@login_required
def historial_asistencias(request):
    qs = Asistencia.objects.select_related("profesor").order_by("-fecha_hora")

    q = request.GET.get("q", "").strip()
    desde = request.GET.get("desde", "").strip()   # yyyy-mm-dd
    hasta = request.GET.get("hasta", "").strip()   # yyyy-mm-dd
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
# EXCEL ÚNICO: TODOS LOS PROFESORES + ASISTIÓ/FALTÓ + HORA
# =========================================================
@login_required
def exportar_reporte_excel(request):
    """
    Exporta a Excel:
    - TODOS los profesores (filtrados por q/condicion si se usa)
    - Evalúa asistencia de UNA FECHA:
        * Usa "desde" como fecha (yyyy-mm-dd)
        * Si no hay "desde", usa HOY
    - Estado:
        * ASISTIÓ -> muestra hora HH:MM (primer registro del día)
        * FALTÓ   -> hora vacía
    """

    # 1) Fecha evaluada (desde o hoy)
    desde = request.GET.get("desde", "").strip()
    fecha_eval = parse_date(desde) if desde else None
    if not fecha_eval:
        fecha_eval = timezone.localdate()

    # 2) Profesores con filtros (mismos del historial)
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

    # 3) Mapa de asistencias del día: profesor_id -> primera fecha_hora
    asistencias_del_dia = (
        Asistencia.objects
        .filter(fecha_hora__date=fecha_eval)
        .values("profesor_id")
        .annotate(primera_hora=Min("fecha_hora"))
    )
    asistio_map = {x["profesor_id"]: x["primera_hora"] for x in asistencias_del_dia}

    # 4) Excel
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

    # Estilo headers
    header_fill = PatternFill("solid", fgColor="1F6FEB")
    header_font = Font(bold=True, color="FFFFFF")
    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=2, column=col_idx)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center")

    # Estilos estado
    fill_ok = PatternFill("solid", fgColor="D1FAE5")    # verde suave
    fill_falta = PatternFill("solid", fgColor="FEE2E2") # rojo suave

    # Filas
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

        # Pintar la celda "Estado"
        estado_cell = ws.cell(row=ws.max_row, column=7)
        estado_cell.alignment = Alignment(horizontal="center")
        estado_cell.font = Font(bold=True)
        estado_cell.fill = fill_ok if estado == "ASISTIÓ" else fill_falta

        # Centrar hora
        ws.cell(row=ws.max_row, column=8).alignment = Alignment(horizontal="center")

    # Tabla bonita
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

    # Ajuste columnas
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



