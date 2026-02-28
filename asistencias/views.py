import os
import json
import re
import logging
import math
from decimal import Decimal, InvalidOperation

from django.contrib.auth import logout, login as auth_login
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm
from datetime import timedelta
from io import BytesIO, StringIO
from itertools import islice  # (no es obligatorio, pero lo dejo por si lo usas luego)
from datetime import datetime, time

from django.db import IntegrityError
from PIL import Image as PILImage
from openpyxl.utils import get_column_letter

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
# HELPERS DE ROLES (GRUPOS) ✅ FINAL
# - Permite superuser siempre
# - _in_any_group permite acceso si está en cualquiera de los grupos
# =============================
# 

# Cloudinary (si está instalado/configurado)
try:
    import cloudinary.uploader
    CLOUDINARY_AVAILABLE = True
except Exception:
    CLOUDINARY_AVAILABLE = False



def _in_group(group_name: str):
    def check(user):
        return (
            user.is_authenticated
            and (user.is_superuser or user.groups.filter(name=group_name).exists())
        )
    return check


def _in_any_group(*group_names: str):
    def check(user):
        return (
            user.is_authenticated
            and (
                user.is_superuser
                or user.groups.filter(name__in=list(group_names)).exists()
            )
        )
    return check


# =========================================================
# ✅ SELECTOR DE MÓDULO POR GRUPOS
# =========================================================
# Nombres EXACTOS de grupos -> URL names reales de tu proyecto
GROUP_DESTINATIONS = {
    "SCANNER": "scan_page",
    "HISTORIAL": "historial_asistencias",
    "JUSTIFICACIONES": "panel_justificaciones",
}


def get_user_allowed_groups(user):
    """
    Retorna grupos válidos del usuario según GROUP_DESTINATIONS.
    - Superuser: acceso a todos los módulos.
    """
    if not user.is_authenticated:
        return []

    if user.is_superuser:
        return list(GROUP_DESTINATIONS.keys())

    user_groups = list(user.groups.values_list("name", flat=True))
    return [g for g in user_groups if g in GROUP_DESTINATIONS]


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
# ✅ HELPERS GEOLOGIN (Geocerca solo para usuario "jorge")
# =========================================================
JORGE_GEOFENCE_USERNAME = "jorge"
JORGE_GEOFENCE_LAT = -12.0360672
JORGE_GEOFENCE_LNG = -77.0033333
JORGE_GEOFENCE_RADIUS_M = 30.0  # metros


def _to_float_maybe(v):
    """
    Convierte string a float aceptando coma o punto decimal.
    """
    try:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        s = s.replace(",", ".")
        return float(s)
    except (ValueError, TypeError):
        return None


def _haversine_m(lat1, lon1, lat2, lon2):
    """
    Distancia entre 2 puntos en metros.
    """
    R = 6371000.0  # metros
    p1 = math.radians(float(lat1))
    p2 = math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))

    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# =========================================================
# ✅ LOGIN PERSONALIZADO (con geocerca solo para "jorge")
# - usa tu template actual
# - mantiene signals (LoginEvidencia) porque usa auth_login()
# - bloquea a jorge si está fuera del área
# =========================================================
def login_view_geocerca(request):
    if request.user.is_authenticated:
        return redirect("post_login")

    form = AuthenticationForm(request=request, data=request.POST or None)

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        username_lc = username.lower()

        # Datos geo enviados desde tu login.html
        geo_status = (request.POST.get("geo_status") or "").strip().lower()
        geo_lat = _to_float_maybe(request.POST.get("geo_lat"))
        geo_lng = _to_float_maybe(request.POST.get("geo_lng"))
        geo_acc = _to_float_maybe(request.POST.get("geo_acc"))  # opcional

        # ✅ Regla especial SOLO para jorge
        if username_lc == JORGE_GEOFENCE_USERNAME:
            # Debe venir ubicación OK
            if geo_status != "ok" or geo_lat is None or geo_lng is None:
                messages.error(
                    request,
                    "Jorge: debes permitir la ubicación para iniciar sesión."
                )
                return render(request, "login.html", {"form": form})

            # Validar geocerca
            distancia_m = _haversine_m(
                geo_lat, geo_lng,
                JORGE_GEOFENCE_LAT, JORGE_GEOFENCE_LNG
            )

            if distancia_m > JORGE_GEOFENCE_RADIUS_M:
                msg = (
                    f"Jorge: fuera del área permitida. "
                    f"Distancia detectada: {distancia_m:.1f} m "
                    f"(máximo {JORGE_GEOFENCE_RADIUS_M:.0f} m)."
                )

                # (Opcional) agregar precisión al mensaje
                if geo_acc is not None:
                    msg += f" Precisión reportada: ±{geo_acc:.0f} m."

                messages.error(request, msg)
                return render(request, "login.html", {"form": form})

            # (Opcional) filtro por precisión:
            # if geo_acc is not None and geo_acc > 50:
            #     messages.error(request, f"Ubicación con baja precisión ({geo_acc:.0f} m). Intenta nuevamente con GPS activo.")
            #     return render(request, "login.html", {"form": form})

        # ✅ Autenticación normal Django (si pasa geocerca o no aplica)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)  # dispara signal user_logged_in
            return redirect(request.POST.get("next") or "post_login")

        # Si credenciales incorrectas, cae al render con form.errors (tu template ya lo muestra)

    return render(request, "login.html", {"form": form})


# =========================================================
# ✅ HELPERS DE HISTORIAL (OPTIMIZACIÓN REAL)
# =========================================================
def _aware_midnight(d):
    """Convierte una fecha a datetime aware a las 00:00:00 (zona local)."""
    dt = datetime.combine(d, time(0, 0, 0))
    tz = timezone.get_current_timezone()
    return timezone.make_aware(dt, tz)


def _event_from_asistencia(a):
    # Mantiene el shape que usas en tu template historial.html
    return {
        "kind": "A",
        "profesor": a.profesor,
        "estado": "ASISTIÓ",
        "fecha_hora": a.fecha_hora,
        "codigo": getattr(a.profesor, "codigo", ""),
        "condicion": getattr(a.profesor, "condicion", ""),
        "detalle": "",
    }


def _event_from_justificacion(j):
    dt = _aware_midnight(j.fecha)
    return {
        "kind": "J",
        "profesor": j.profesor,
        "estado": f"JUSTIFICADO ({j.tipo})",
        "fecha_hora": dt,
        "codigo": getattr(j.profesor, "codigo", ""),
        "condicion": getattr(j.profesor, "condicion", ""),
        "detalle": (j.detalle or ""),
    }


def _merge_top_n(asist_qs, just_qs, n):
    """
    Devuelve eventos ordenados desc por fecha_hora,
    trayendo solo lo necesario: top N de cada fuente y luego merge.
    """
    asist_list = list(asist_qs[:n])
    just_list = list(just_qs[:n])

    i = j = 0
    out = []

    while len(out) < n and (i < len(asist_list) or j < len(just_list)):
        if i >= len(asist_list):
            out.append(_event_from_justificacion(just_list[j])); j += 1
            continue
        if j >= len(just_list):
            out.append(_event_from_asistencia(asist_list[i])); i += 1
            continue

        a_dt = asist_list[i].fecha_hora
        j_dt = _aware_midnight(just_list[j].fecha)

        if a_dt >= j_dt:
            out.append(_event_from_asistencia(asist_list[i])); i += 1
        else:
            out.append(_event_from_justificacion(just_list[j])); j += 1

    return out


# =========================================================
# POST LOGIN REDIRECT ✅ FINAL (CON SELECTOR DE MÓDULO)
# - Si tiene 1 grupo: entra directo
# - Si tiene 2 o 3 grupos: muestra selector
# - Superuser: muestra selector
# =========================================================
@login_required
def post_login_redirect(request):
    allowed_groups = get_user_allowed_groups(request.user)

    if not allowed_groups:
        logout(request)
        messages.error(request, "Tu usuario no tiene módulos asignados.")
        return redirect("login")

    # Si tiene solo 1 grupo, entra directo
    if len(allowed_groups) == 1:
        selected_group = allowed_groups[0]
        request.session["selected_group"] = selected_group
        return redirect(GROUP_DESTINATIONS[selected_group])

    # Si tiene varios (2 o 3), mostrar selector
    return redirect("seleccionar_grupo")


# =========================================================
# SELECTOR DE GRUPO / MÓDULO ✅ FINAL
# - Solo aparece si tiene varios grupos
# - Guarda selección en session["selected_group"]
# =========================================================
@login_required
def seleccionar_grupo(request):
    allowed_groups = get_user_allowed_groups(request.user)

    if not allowed_groups:
        logout(request)
        messages.error(request, "Tu usuario no tiene módulos asignados.")
        return redirect("login")

    # Si solo tiene 1 grupo, entrar directo
    if len(allowed_groups) == 1:
        g = allowed_groups[0]
        request.session["selected_group"] = g
        return redirect(GROUP_DESTINATIONS[g])

    if request.method == "POST":
        grupo_elegido = (request.POST.get("grupo") or "").strip()

        if grupo_elegido not in allowed_groups:
            messages.error(request, "Grupo no válido.")
            return redirect("seleccionar_grupo")

        request.session["selected_group"] = grupo_elegido
        messages.success(request, f"Ingresaste al módulo: {grupo_elegido}")
        return redirect(GROUP_DESTINATIONS[grupo_elegido])

    return render(request, "asistencias/seleccionar_grupo.html", {
        "allowed_groups": allowed_groups
    })


# =========================================================
# HISTORIAL ✅ FINAL (OPTIMIZADO)
# ✅ ya NO arma una lista gigante con toda la BD
# ✅ trae solo lo necesario para la página (merge inteligente)
# =========================================================
@user_passes_test(_in_any_group("HISTORIAL", "JUSTIFICACIONES"), login_url="login")
def historial_asistencias(request):
    q = request.GET.get("q", "").strip()
    desde = request.GET.get("desde", "").strip()
    hasta = request.GET.get("hasta", "").strip()
    condicion = request.GET.get("condicion", "").strip()

    ps = request.GET.get("ps", "25").strip()
    if ps not in ("25", "50", "100"):
        ps = "25"
    ps = int(ps)

    # Fecha para regresar a justificaciones (si vienes desde ese panel)
    fecha_just = request.session.get("just_fecha")
    if not fecha_just:
        fecha_just = (timezone.localdate() - timedelta(days=1)).strftime("%Y-%m-%d")

    # mostrar botón solo si pertenece al grupo JUSTIFICACIONES (o superuser)
    puede_volver_just = (
        request.user.is_authenticated
        and (
            request.user.is_superuser
            or request.user.groups.filter(name="JUSTIFICACIONES").exists()
        )
    )

    # =========================
    # ✅ Querysets BASE (livianos)
    # =========================
    asist_qs = (
        Asistencia.objects
        .select_related("profesor")
        .only(
            "id", "fecha_hora", "tipo",
            "profesor__id", "profesor__codigo", "profesor__condicion",
            "profesor__apellidos", "profesor__nombres"
        )
        .filter(tipo="E")
        .order_by("-fecha_hora")
    )

    just_qs = (
        JustificacionAsistencia.objects
        .select_related("profesor")
        .only(
            "id", "fecha", "tipo", "detalle",
            "profesor__id", "profesor__codigo", "profesor__condicion",
            "profesor__apellidos", "profesor__nombres"
        )
        .all()
        .order_by("-fecha")
    )

    # =========================
    # ✅ Filtros (igual que tú)
    # =========================
    if q:
        filt = (
            Q(profesor__dni__icontains=q) |
            Q(profesor__codigo__icontains=q) |
            Q(profesor__apellidos__icontains=q) |
            Q(profesor__nombres__icontains=q)
        )
        asist_qs = asist_qs.filter(filt)
        just_qs = just_qs.filter(filt)

    if condicion:
        asist_qs = asist_qs.filter(profesor__condicion__iexact=condicion)
        just_qs = just_qs.filter(profesor__condicion__iexact=condicion)

    # Mantengo tu lógica con strings (no rompo nada)
    if desde:
        asist_qs = asist_qs.filter(fecha_hora__date__gte=desde)
        just_qs = just_qs.filter(fecha__gte=desde)

    if hasta:
        asist_qs = asist_qs.filter(fecha_hora__date__lte=hasta)
        just_qs = just_qs.filter(fecha__lte=hasta)

    # =========================
    # ✅ KPIs sin cargar todo
    # =========================
    total_asist = asist_qs.count()
    total_just = just_qs.count()
    total_registros = total_asist + total_just

    ids_a = set(asist_qs.values_list("profesor_id", flat=True).distinct())
    ids_j = set(just_qs.values_list("profesor_id", flat=True).distinct())
    docentes_unicos = len(ids_a | ids_j)

    registros_n = (
        asist_qs.filter(profesor__condicion__iexact="N").count()
        + just_qs.filter(profesor__condicion__iexact="N").count()
    )
    registros_c = (
        asist_qs.filter(profesor__condicion__iexact="C").count()
        + just_qs.filter(profesor__condicion__iexact="C").count()
    )

    # =========================
    # ✅ PAGINACIÓN REAL (sin lista gigante)
    # =========================
    page_number = request.GET.get("page", "1")
    try:
        page_number_int = int(page_number)
        if page_number_int < 1:
            page_number_int = 1
    except Exception:
        page_number_int = 1

    offset = (page_number_int - 1) * ps
    need_n = offset + ps

    merged = _merge_top_n(asist_qs, just_qs, need_n)
    page_items = merged[offset:offset + ps]

    # paginator "virtual" solo para que tu template siga funcionando
    paginator = Paginator(range(total_registros), ps)
    page_obj = paginator.get_page(page_number_int)
    page_obj.object_list = page_items

    return render(request, "asistencias/historial.html", {
        "items": page_items,
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

        "puede_volver_just": puede_volver_just,
        "fecha_just": fecha_just,
    })


# =========================================================
# EXCEL (HISTORIAL o JUSTIFICACIONES) ✅ FINAL
# =========================================================
@user_passes_test(_in_any_group("HISTORIAL", "JUSTIFICACIONES"), login_url="login")
def exportar_reporte_excel(request):
    q = (request.GET.get("q") or "").strip()
    condicion = (request.GET.get("condicion") or "").strip().upper()
    desde_str = (request.GET.get("desde") or "").strip()
    hasta_str = (request.GET.get("hasta") or "").strip()

    hoy = timezone.localdate()
    desde = parse_date(desde_str) if desde_str else None
    hasta = parse_date(hasta_str) if hasta_str else None

    # ✅ Defaults: si no mandan fechas, usa hoy
    if not desde:
        desde = hoy
    if not hasta:
        hasta = hoy

    # ✅ si vienen invertidas
    if desde > hasta:
        desde, hasta = hasta, desde

    # ✅ Generar lista de días
    days = []
    cur = desde
    while cur <= hasta:
        days.append(cur)
        cur += timedelta(days=1)

    # =========================
    # ✅ Filtrar profesores
    # =========================
    profesores = Profesor.objects.all().order_by("apellidos", "nombres")

    if q:
        profesores = profesores.filter(
            Q(dni__icontains=q) |
            Q(codigo__icontains=q) |
            Q(apellidos__icontains=q) |
            Q(nombres__icontains=q)
        )

    if condicion in ("N", "C"):
        profesores = profesores.filter(condicion__iexact=condicion)

    profesores = list(profesores)
    prof_ids = [p.id for p in profesores]

    # =========================
    # ✅ Traer ENTRADAS del rango (E) (primera hora por día)
    # =========================
    entradas = (
        Asistencia.objects
        .filter(profesor_id__in=prof_ids, fecha__range=(desde, hasta), tipo="E")
        .values("profesor_id", "fecha")
        .annotate(primera_hora=Min("fecha_hora"))
    )
    entrada_map = {(x["profesor_id"], x["fecha"]): x["primera_hora"] for x in entradas}

    # =========================
    # ✅ Justificaciones del rango (tabla JustificacionAsistencia)
    # =========================
    justificados = (
        JustificacionAsistencia.objects
        .filter(profesor_id__in=prof_ids, fecha__range=(desde, hasta))
        .values("profesor_id", "fecha", "tipo", "detalle")
    )

    MOTIVOS_LABEL = {
        "DM": "Descanso médico",
        "C": "Comisión / Encargo",
        "P": "Permiso",
        "O": "Otro",
    }
    just_map = {}
    for j in justificados:
        key = (j["profesor_id"], j["fecha"])
        t = (j.get("tipo") or "").strip()
        det = (j.get("detalle") or "").strip()
        label = MOTIVOS_LABEL.get(t, t or "Justificación")
        just_map[key] = f"JUSTIFICADO ({label})" + (f" - {det}" if det else "")

    # =========================
    # ✅ Si NO hay JustificacionAsistencia, puede existir Asistencia tipo="J"
    # (respaldo)
    # =========================
    asist_j = (
        Asistencia.objects
        .filter(profesor_id__in=prof_ids, fecha__range=(desde, hasta), tipo="J")
        .values("profesor_id", "fecha", "motivo", "detalle")
    )
    asist_j_map = {}
    for a in asist_j:
        key = (a["profesor_id"], a["fecha"])
        mot = (a.get("motivo") or "").strip()
        det = (a.get("detalle") or "").strip()
        label = {
            "DM": "Descanso médico",
            "C": "Comisión / Encargo",
            "P": "Permiso",
            "O": "Otro",
        }.get(mot, mot or "Justificación")
        asist_j_map[key] = f"JUSTIFICADO ({label})" + (f" - {det}" if det else "")

    # =========================
    # ✅ Crear Excel (MATRIZ POR DÍA)
    # =========================
    wb = Workbook()
    ws: Worksheet = wb.active
    ws.title = "Asistencia"

    navy = "0B1F3B"
    blue = "2563EB"
    gray_bg = "F3F4F6"
    ok_bg = "DCFCE7"
    bad_bg = "FEE2E2"
    info_bg = "E0E7FF"
    text_dark = "0F172A"

    thin = Side(style="thin", color="CBD5E1")
    border_all = Border(left=thin, right=thin, top=thin, bottom=thin)

    base_cols = 4
    n_days = len(days)
    total_cols = 3
    total_columns = base_cols + n_days + total_cols
    last_col_letter = get_column_letter(total_columns)

    for r in (1, 2):
        for c in range(1, total_columns + 1):
            ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=gray_bg)

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

    titulo = f"REPORTE DE ASISTENCIA — {desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}"
    ws["B1"] = titulo
    ws.merge_cells(f"B1:{last_col_letter}1")
    ws["B1"].font = Font(bold=True, size=16, color=navy)
    ws["B1"].alignment = Alignment(vertical="center")

    filtros_txt = []
    if q:
        filtros_txt.append(f"Búsqueda: {q}")
    if condicion:
        filtros_txt.append(f"Condición: {condicion.upper()}")
    filtros_txt.append(f"Desde: {desde.strftime('%Y-%m-%d')}")
    filtros_txt.append(f"Hasta: {hasta.strftime('%Y-%m-%d')}")
    filtros_txt.append(f"Docentes: {len(profesores)}")
    filtros_txt.append(f"Días: {n_days}")

    ws["B2"] = " | ".join(filtros_txt)
    ws.merge_cells(f"B2:{last_col_letter}2")
    ws["B2"].font = Font(size=11, color="334155")
    ws["B2"].alignment = Alignment(vertical="center")

    ws.append([])
    headers = ["DNI", "Código", "Docente", "Condición"]

    for d in days:
        headers.append(d.strftime("%d/%m"))

    headers += ["Asistió", "Just.", "Faltó"]

    ws.append([str(h) for h in headers])
    header_row = ws.max_row

    header_fill = PatternFill("solid", fgColor=blue)
    header_font = Font(bold=True, color="FFFFFF")

    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=header_row, column=col_idx)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border_all

    ws.row_dimensions[header_row].height = 22
    data_start = header_row + 1

    for p in profesores:
        asistio_count = 0
        just_count = 0
        falta_count = 0

        docente = f"{(p.apellidos or '').strip()}, {(p.nombres or '').strip()}".strip().strip(",")

        row = [
            str(p.dni),
            str(p.codigo or ""),
            str(docente),
            str((p.condicion or "").upper()),
        ]

        for d in days:
            key = (p.id, d)

            dt = entrada_map.get(key)
            if dt:
                dt_local = timezone.localtime(dt)
                val = f"ASISTIÓ ({dt_local.strftime('%H:%M')})"
                asistio_count += 1
            else:
                jtxt = just_map.get(key) or asist_j_map.get(key)
                if jtxt:
                    val = jtxt
                    just_count += 1
                else:
                    val = "FALTÓ"
                    falta_count += 1

            row.append(val)

        row += [asistio_count, just_count, falta_count]

        ws.append(row)
        r = ws.max_row

        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=r, column=col)
            cell.border = border_all
            cell.alignment = Alignment(vertical="center", wrap_text=True)

        ws.cell(row=r, column=4).alignment = Alignment(horizontal="center", vertical="center")

        day_start_col = 5
        day_end_col = 4 + n_days
        for col in range(day_start_col, day_end_col + 1):
            cell = ws.cell(row=r, column=col)
            txt = (cell.value or "")
            cell.font = Font(bold=True, color=text_dark)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

            if str(txt).startswith("ASISTIÓ"):
                cell.fill = PatternFill("solid", fgColor=ok_bg)
            elif str(txt).startswith("JUSTIFICADO"):
                cell.fill = PatternFill("solid", fgColor=info_bg)
            else:
                cell.fill = PatternFill("solid", fgColor=bad_bg)

        tot_start = 5 + n_days
        for col in range(tot_start, tot_start + 3):
            ws.cell(row=r, column=col).alignment = Alignment(horizontal="center", vertical="center")

    last_row = ws.max_row
    if last_row >= data_start:
        table_ref = f"A{header_row}:{last_col_letter}{last_row}"
        table = Table(displayName="TablaReporteAsistencia", ref=table_ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium9",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False
        )
        ws.add_table(table)

    ws.freeze_panes = f"E{data_start}"

    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 40
    ws.column_dimensions["D"].width = 12

    for i in range(n_days):
        ws.column_dimensions[get_column_letter(5 + i)].width = 16

    ws.column_dimensions[get_column_letter(5 + n_days)].width = 10
    ws.column_dimensions[get_column_letter(6 + n_days)].width = 10
    ws.column_dimensions[get_column_letter(7 + n_days)].width = 10

    ws2 = wb.create_sheet("Leyenda")
    ws2["A1"] = "Leyenda"
    ws2["A1"].font = Font(bold=True, size=14)
    ws2["A3"] = "ASISTIÓ (HH:MM) = entrada registrada"
    ws2["A4"] = "JUSTIFICADO (...) = ausencia justificada"
    ws2["A5"] = "FALTÓ = no hay entrada ni justificación"
    for r in range(3, 6):
        ws2[f"A{r}"].font = Font(size=11)

    filename = f"reporte_asistencia_{desde.strftime('%Y-%m-%d')}_a_{hasta.strftime('%Y-%m-%d')}.xlsx"
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
# SCAN PAGE (solo grupo SCANNER)
# =========================================================
@ensure_csrf_cookie
@user_passes_test(_in_group("SCANNER"), login_url="login")
def scan_page(request):
    return render(request, "asistencias/scan.html")


# =========================================================
# API SCAN (solo grupo SCANNER)  SOLO ENTRADA
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
        qs = (
            Asistencia.objects
            .select_for_update()
            .filter(profesor=profesor, fecha=hoy, tipo="E")
            .order_by("fecha_hora")
        )

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
# CRON PRIVADO (Render + cron-job)
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

    return JsonResponse({"ok": True, "msg": "Reporte ejecutado", "output": texto})


# =========================================================
# REGISTRO MANUAL (solo grupo HISTORIAL)
# =========================================================
@user_passes_test(_in_group("HISTORIAL"), login_url="login")
def registro_manual(request):
    """
    Template: asistencias/registro_manual.html
    - POST accion=buscar   -> busca por dni y muestra confirmación
    - POST accion=aceptar  -> registra ENTRADA y REDIRIGE al historial
    """

    if request.method == "GET":
        return render(request, "asistencias/registro_manual.html")

    accion = (request.POST.get("accion") or "").strip().lower()

    if accion == "buscar":
        dni = (request.POST.get("dni") or "").strip()

        if not (dni.isdigit() and len(dni) == 8):
            messages.error(request, "DNI inválido (debe tener 8 dígitos).")
            return render(request, "asistencias/registro_manual.html")

        profesor = Profesor.objects.filter(dni=dni).first()
        if not profesor:
            messages.error(request, "No se encontró un docente con ese DNI.")
            return render(request, "asistencias/registro_manual.html")

        ahora_local = timezone.localtime(timezone.now())
        ctx = {
            "profesor": profesor,
            "fecha_hora_str": ahora_local.strftime("%d/%m/%Y %H:%M:%S"),
        }
        return render(request, "asistencias/registro_manual.html", ctx)

    if accion == "aceptar":
        dni = (request.POST.get("dni") or "").strip()

        if not (dni.isdigit() and len(dni) == 8):
            messages.error(request, "DNI inválido.")
            return redirect("registro_manual")

        profesor = Profesor.objects.filter(dni=dni).first()
        if not profesor:
            messages.error(request, "El docente no existe o no fue encontrado.")
            return redirect("registro_manual")

        fecha = timezone.localdate()
        ahora = timezone.now()

        if Asistencia.objects.filter(profesor=profesor, fecha=fecha, tipo="E").exists():
            messages.warning(request, "Ese docente ya tiene ENTRADA registrada hoy.")
            return redirect("historial_asistencias")

        try:
            Asistencia.objects.create(
                profesor=profesor,
                fecha=fecha,
                fecha_hora=ahora,
                tipo="E",
                registrado_por=request.user,
                ip=_get_client_ip(request),
                user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:255],
            )
        except IntegrityError:
            messages.warning(request, "Ese docente ya tiene ENTRADA registrada hoy.")
            return redirect("historial_asistencias")

        messages.success(request, "✅ Asistencia registrada correctamente.")
        return redirect("historial_asistencias")

    messages.error(request, "Acción no válida.")
    return redirect("registro_manual")


# =========================================================
# PANEL JUSTIFICACIONES (GET) ✅ FINAL (OPTIMIZADO)
# URL: /asistencia/justificaciones/
# - guarda just_fecha en session
# - manda can_historial al template
# =========================================================
@user_passes_test(_in_group("JUSTIFICACIONES"), login_url="login")
@require_GET
def panel_justificaciones(request):
    hoy = timezone.localdate()

    fecha_str = (request.GET.get("fecha") or "").strip()
    q = (request.GET.get("q") or "").strip()

    if not fecha_str:
        fecha = hoy - timezone.timedelta(days=1)
    else:
        fecha = parse_date(fecha_str) or hoy

    request.session["just_fecha"] = fecha.strftime("%Y-%m-%d")

    # ✅ Profesores liviano (solo campos usados)
    profesores_qs = (
        Profesor.objects
        .only("id", "dni", "codigo", "apellidos", "nombres", "condicion")
        .order_by("apellidos", "nombres")
    )
    if q:
        profesores_qs = profesores_qs.filter(
            Q(dni__icontains=q) |
            Q(codigo__icontains=q) |
            Q(apellidos__icontains=q) |
            Q(nombres__icontains=q)
        )

    profesores = list(profesores_qs)  # 1 query

    # ✅ Asistencias del día (solo ENTRADA) → set de ids
    asist_ids = set(
        Asistencia.objects
        .filter(fecha=fecha, tipo="E")
        .values_list("profesor_id", flat=True)
    )

    # ✅ Justificaciones del día → objetos (para usar archivo y tipo_display)
    just_qs = (
        JustificacionAsistencia.objects
        .only("id", "profesor_id", "fecha", "tipo", "detalle", "archivo")
        .filter(fecha=fecha)
    )
    just_map = {j.profesor_id: j for j in just_qs}

    rows = []
    c_asistio = 0
    c_just = 0
    c_falto = 0

    for p in profesores:
        if p.id in asist_ids:
            estado_key = "ASISTIO"
            estado = "ASISTIÓ"
            estado_detalle = "Registro de entrada"
            j = None
            c_asistio += 1
        else:
            j = just_map.get(p.id)
            if j:
                estado_key = "JUSTIFICADO"
                tipo_label = j.get_tipo_display() if hasattr(j, "get_tipo_display") else (j.tipo or "")
                estado = f"JUSTIFICADO ({tipo_label})"
                estado_detalle = (j.detalle or "").strip()
                c_just += 1
            else:
                estado_key = "FALTO"
                estado = "FALTÓ"
                estado_detalle = "Sin registro ni justificación"
                c_falto += 1

        rows.append({
            "profesor": p,
            "estado": estado,
            "estado_key": estado_key,
            "estado_detalle": estado_detalle,
            "justificacion": j,
        })

    can_historial = (
        request.user.is_superuser
        or request.user.groups.filter(name="HISTORIAL").exists()
        or request.user.groups.filter(name="JUSTIFICACIONES").exists()
    )

    return render(request, "asistencias/justificaciones.html", {
        "fecha": fecha,
        "q": q,
        "rows": rows,
        "can_historial": can_historial,
        "resumen": {
            "asistio": c_asistio,
            "justificado": c_just,
            "falto": c_falto,
            "total": c_asistio + c_just + c_falto
        }
    })


# =========================================================
# SET JUSTIFICACIÓN (POST) ✅ FINAL
# =========================================================
@require_POST
@user_passes_test(_in_group("JUSTIFICACIONES"), login_url="login")
def set_justificacion(request):
    # ✅ (Opcional recomendado) proteger por método POST
    if request.method != "POST":
        messages.error(request, "Método no permitido.")
        return redirect("/asistencia/justificaciones/")

    accion = (request.POST.get("accion") or "").strip().lower()
    profesor_id = (request.POST.get("profesor_id") or "").strip()
    fecha_str = (request.POST.get("fecha") or "").strip()
    tipo = (request.POST.get("tipo") or "DM").strip().upper()
    detalle = (request.POST.get("detalle") or "").strip()
    archivo = request.FILES.get("archivo")  # PDF opcional

    redirect_url = (f"/asistencia/justificaciones/?fecha={fecha_str}" if fecha_str else "/asistencia/justificaciones/")

    if accion != "set":
        messages.error(request, "Acción inválida.")
        return redirect(redirect_url)

    fecha = parse_date(fecha_str)
    if not fecha:
        messages.error(request, "Fecha inválida.")
        return redirect(redirect_url)

    try:
        profesor = Profesor.objects.get(id=profesor_id)
    except Profesor.DoesNotExist:
        messages.error(request, "Profesor no encontrado.")
        return redirect(redirect_url)

    tipo_ok = tipo if tipo in ("DM", "C", "P", "O") else "DM"
    ip = _get_client_ip(request)
    ua = (request.META.get("HTTP_USER_AGENT") or "")[:255]

    # ✅ Si ya registró asistencia de entrada, no permitir justificar
    if Asistencia.objects.filter(profesor=profesor, fecha=fecha, tipo="E").exists():
        messages.warning(request, "🛑 Ya tiene ASISTENCIA ese día. No se registró justificación.")
        return redirect(redirect_url)

    # ✅ Si ya existe justificación para ese día/profesor
    if JustificacionAsistencia.objects.filter(profesor=profesor, fecha=fecha).exists():
        messages.warning(request, "✅ Este docente ya fue justificado en esta fecha. (Solo se puede editar en el Admin).")
        return redirect(redirect_url)

    # =========================
    # ✅ VALIDACIÓN PDF (frontend + backend)
    # =========================
    if archivo:
        nombre_original = (archivo.name or "").strip()
        nombre_lower = nombre_original.lower()
        ctype = (getattr(archivo, "content_type", "") or "").lower()
        size = getattr(archivo, "size", 0) or 0

        if not nombre_lower.endswith(".pdf"):
            messages.error(request, "El archivo debe terminar en .pdf")
            return redirect(redirect_url)

        # OJO: algunos navegadores mandan content_type vacío o raro, por eso no lo hago súper estricto si viene vacío
        if ctype and ctype != "application/pdf":
            messages.error(request, f"El archivo debe ser PDF (content_type recibido: {ctype}).")
            return redirect(redirect_url)

        if size > 10 * 1024 * 1024:
            messages.error(request, "El PDF es muy pesado (máx. 10 MB).")
            return redirect(redirect_url)

    try:
        with transaction.atomic():
            # ======================================
            # ✅ PREPARAR DATOS DE JUSTIFICACIÓN
            # ======================================
            just_kwargs = {
                "profesor": profesor,
                "fecha": fecha,
                "tipo": tipo_ok,
                "detalle": detalle,
                "creado_por": request.user,
                "actualizado_por": request.user,
            }

            # ======================================
            # ✅ SUBIDA DE ARCHIVO (Cloudinary preferido)
            # ======================================
            # Si Cloudinary está disponible y configurado, subimos allá para que TODOS puedan verlo.
            # Si falla, hacemos fallback a FileField local (archivo=archivo).
            if archivo:
                archivo_url_cloud = None
                cloudinary_error = None

                # Carpeta amigable por fecha
                folder = f"justificaciones/{fecha.year}/{fecha.month:02d}"

                if CLOUDINARY_AVAILABLE:
                    try:
                        # IMPORTANTE: PDFs => resource_type="raw"
                        upload_res = cloudinary.uploader.upload(
                            archivo,
                            resource_type="raw",
                            folder=folder,
                            use_filename=True,
                            unique_filename=True,
                            overwrite=False,
                        )
                        archivo_url_cloud = upload_res.get("secure_url") or upload_res.get("url")

                        # Si tienes campo archivo_url en el modelo, lo guardamos
                        model_field_names = {f.name for f in JustificacionAsistencia._meta.get_fields()}
                        if "archivo_url" in model_field_names and archivo_url_cloud:
                            just_kwargs["archivo_url"] = archivo_url_cloud

                        # ✅ Guardamos también una copia local en FileField si tu modelo lo requiere
                        # (opcional, pero útil para compatibilidad con código existente que usa .archivo)
                        # OJO: como el archivo ya fue leído por Cloudinary, reseteamos puntero si se puede.
                        try:
                            archivo.seek(0)
                        except Exception:
                            pass

                        just_kwargs["archivo"] = archivo

                    except Exception as ex:
                        # Fallback local si Cloudinary falla
                        cloudinary_error = str(ex)[:220]
                        try:
                            archivo.seek(0)
                        except Exception:
                            pass
                        just_kwargs["archivo"] = archivo
                else:
                    # Sin Cloudinary instalado: guardado local normal
                    just_kwargs["archivo"] = archivo

                # (Opcional) puedes notificar si Cloudinary falló pero guardó local
                if cloudinary_error:
                    messages.warning(
                        request,
                        f"⚠️ PDF guardado en almacenamiento local (Cloudinary falló): {cloudinary_error}"
                    )

            # ======================================
            # ✅ CREAR JUSTIFICACIÓN
            # ======================================
            just = JustificacionAsistencia.objects.create(**just_kwargs)

            # ======================================
            # ✅ (Compatibilidad extra) Si NO existe archivo_url en DB pero quieres exponer URL
            #    y tu modelo SÍ tiene archivo_url, lo llenamos desde archivo.url cuando sea local
            # ======================================
            try:
                model_field_names = {f.name for f in JustificacionAsistencia._meta.get_fields()}
                if "archivo_url" in model_field_names:
                    if not getattr(just, "archivo_url", None):
                        if getattr(just, "archivo", None):
                            try:
                                just.archivo_url = just.archivo.url  # local media URL
                                just.save(update_fields=["archivo_url", "actualizado_por"])
                            except Exception:
                                pass
            except Exception:
                pass

            # ======================================
            # ✅ CREAR / ACTUALIZAR ASISTENCIA tipo J
            # ======================================
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

        messages.success(request, "✅ Justificación guardada correctamente.")
        return redirect(redirect_url)

    except IntegrityError:
        messages.warning(request, "✅ Ya existía una justificación para ese docente en esa fecha.")
        return redirect(redirect_url)

    except Exception as e:
        messages.error(request, f"Error guardando justificación/PDF: {type(e).__name__} - {str(e)[:250]}")
        return redirect(redirect_url)