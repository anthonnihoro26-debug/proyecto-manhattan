"""Gestión rápida para administradores, sin reemplazar los modelos históricos."""
from datetime import timedelta
from django import forms
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.http import urlencode
from urllib.parse import urlsplit, parse_qs
from django.conf import settings
import secrets
from django.contrib.auth.hashers import check_password
from django.core.management import call_command
from io import StringIO
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from .models import Profesor, Asistencia, JustificacionAsistencia, DiaEspecial, ReporteEnvio
from .servicio_reportes import preparar_envio, EnvioNoPermitido, semana_actual


class JustificacionRangoForm(forms.Form):
    MODOS = [("rango", "Entre dos fechas"), ("cantidad", "Por cantidad de días hábiles")]
    profesor = forms.ModelChoiceField(label="Docente", queryset=Profesor.objects.none(), empty_label="Selecciona un docente")
    modo = forms.ChoiceField(label="Modalidad", choices=MODOS, widget=forms.RadioSelect, initial="rango")
    desde = forms.DateField(label="Desde", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hasta = forms.DateField(label="Hasta (si eliges rango)", required=False, widget=forms.DateInput(attrs={"type":"date"}, format="%Y-%m-%d"))
    cantidad = forms.IntegerField(label="Cantidad de días hábiles", required=False, min_value=1, max_value=90)
    tipo = forms.ChoiceField(label="Motivo", choices=JustificacionAsistencia.TIPO_CHOICES)
    detalle = forms.CharField(label="Detalle", max_length=255, widget=forms.Textarea(attrs={"rows":3}), required=False)
    archivo = forms.FileField(label="Sustento (PDF opcional, máximo 10 MB)", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["profesor"].queryset = Profesor.objects.all().order_by("apellidos", "nombres")
        self.fields["desde"].initial = timezone.localdate()
        for campo in self.fields.values():
            if not isinstance(campo.widget, forms.RadioSelect):
                campo.widget.attrs.setdefault("class", "campo")

    def clean_archivo(self):
        f = self.cleaned_data.get("archivo")
        if f and (not f.name.lower().endswith(".pdf") or f.size > 10 * 1024 * 1024):
            raise forms.ValidationError("Adjunta únicamente un PDF de hasta 10 MB.")
        if f:
            head = f.read(5)
            f.seek(0)
            if head != b"%PDF-":
                raise forms.ValidationError("El archivo no parece un PDF válido.")
        return f

    def clean(self):
        datos = super().clean()
        inicio = datos.get("desde")
        if not inicio:
            return datos
        modo = datos.get("modo")
        if modo == "cantidad":
            cantidad = datos.get("cantidad")
            if not cantidad:
                self.add_error("cantidad", "Indica una cantidad de días.")
                return datos
            # "Cantidad" significa días realmente justificables; omite sábados,
            # domingos y días especiales, completando la cantidad solicitada.
            cursor = inicio
            posibles = [inicio + timedelta(days=i) for i in range(183)]
            especiales = set(DiaEspecial.objects.filter(
                activo=True, fecha__in=posibles
            ).values_list("fecha", flat=True))
            prof = datos.get("profesor")
            ya_justificados = set()
            con_asistencia = set()
            if prof:
                ya_justificados = set(JustificacionAsistencia.objects.filter(
                    profesor=prof, fecha__in=posibles).values_list("fecha", flat=True))
                con_asistencia = set(Asistencia.objects.filter(
                    profesor=prof, fecha__in=posibles, tipo="E").values_list("fecha", flat=True))
            fechas = []
            for cursor in posibles:
                if (cursor.weekday() < 5 and cursor not in especiales
                        and cursor not in ya_justificados and cursor not in con_asistencia):
                    fechas.append(cursor)
                    if len(fechas) == cantidad:
                        break
            if len(fechas) != cantidad:
                raise forms.ValidationError(
                    "No se encontraron suficientes días hábiles justificables "
                    "dentro del plazo permitido."
                )
        else:
            final = datos.get("hasta")
            if not final:
                self.add_error("hasta", "Indica la fecha final.")
                return datos
            if final < inicio:
                self.add_error("hasta", "La fecha final debe ser posterior o igual a la inicial.")
                return datos
            if (final - inicio).days > 125:
                self.add_error("hasta", "El rango no puede superar 126 días.")
                return datos
            fechas = [inicio + timedelta(days=i) for i in range((final - inicio).days + 1)
                      if (inicio + timedelta(days=i)).weekday() < 5]
        if not fechas:
            raise forms.ValidationError("No hay días hábiles dentro de las fechas indicadas.")
        if len(fechas) > 90:
            raise forms.ValidationError("Máximo 90 días hábiles por operación.")
        datos["fechas_habiles"] = fechas
        return datos


@staff_member_required(login_url="/login/")
def inicio(request):
    hoy = timezone.localdate()
    contexto = {
        "clave_temporal": (request.user.username.lower() == "admin" and check_password("12345678", request.user.password)),
        "profesores": Profesor.objects.count(),
        "activos": Profesor.objects.filter(activo=True).count(),
        "asistencias_hoy": Asistencia.objects.filter(fecha=hoy, tipo="E").count(),
        "justificaciones": JustificacionAsistencia.objects.count(),
        "especiales": DiaEspecial.objects.filter(fecha__gte=hoy, activo=True).count(),
        "ultimas_asistencias": Asistencia.objects.select_related("profesor").order_by("-fecha_hora")[:7],
        "ultimas_justificaciones": JustificacionAsistencia.objects.select_related("profesor").order_by("-creado_en")[:7],
        "lote": ReporteEnvio.objects.filter(semana_inicio=semana_actual()).first(),
        "semana": semana_actual(),
    }
    return render(request, "asistencias/gestion/inicio.html", contexto)


@staff_member_required(login_url="/login/")
@require_http_methods(["GET", "POST"])
def justificar_rango(request):
    inicial = {}
    if request.method == "GET":
        if request.GET.get("profesor", "").isdigit():
            inicial["profesor"] = request.GET["profesor"]
        if request.GET.get("desde"):
            inicial["desde"] = request.GET["desde"]
            inicial["hasta"] = request.GET.get("hasta", request.GET["desde"])
    form = JustificacionRangoForm(request.POST or None, request.FILES or None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        datos = form.cleaned_data
        prof = datos["profesor"]
        candidatas = datos["fechas_habiles"]
        # No se crean justificantes sobre días especiales institucionales activos.
        especiales = set(DiaEspecial.objects.filter(fecha__in=candidatas, activo=True).values_list("fecha", flat=True))
        validas = [d for d in candidatas if d not in especiales]
        existentes = set(JustificacionAsistencia.objects.filter(profesor=prof, fecha__in=validas).values_list("fecha", flat=True))
        con_asistencia = set(Asistencia.objects.filter(profesor=prof, fecha__in=validas, tipo="E").values_list("fecha", flat=True))
        pendientes = [d for d in validas if d not in existentes and d not in con_asistencia]
        if not pendientes:
            messages.warning(request, "No se crearon registros: los días ya estaban justificados, tenían asistencia o son días especiales.")
            return redirect("gestion_justificar")
        # Guardar una sola copia del documento. No se modifican asistencias existentes.
        archivo = datos.get("archivo")
        nombre_guardado = ""
        if archivo:
            from django.core.files.storage import default_storage
            from uuid import uuid4
            nombre_guardado = default_storage.save(
                f"justificaciones/masivas/{timezone.localdate():%Y/%m}/{uuid4().hex}.pdf", archivo
            )
        creados = 0
        with transaction.atomic():
            for dia in pendientes:
                _, nuevo = JustificacionAsistencia.objects.get_or_create(
                    profesor=prof, fecha=dia,
                    defaults={
                        "tipo": datos["tipo"], "detalle": datos["detalle"],
                        "archivo": nombre_guardado,
                        "creado_por": request.user, "actualizado_por": request.user,
                    },
                )
                if nuevo:
                    creados += 1
                    # El historial legado también consulta registros tipo J.
                    Asistencia.objects.get_or_create(
                        profesor=prof, fecha=dia, tipo="J",
                        defaults={
                            "fecha_hora": timezone.now(),
                            "motivo": datos["tipo"], "detalle": datos["detalle"],
                            "registrado_por": request.user,
                        },
                    )
        messages.success(request,
            f"Justificados {creados} días. Ya justificados: {len(existentes)}. "
            f"Con asistencia: {len(con_asistencia)}. Días especiales omitidos: {len(especiales)}. "
            "Consulta Historial o Justificaciones para comprobarlos.")
        pagina_origen = request.POST.get("origen", "")
        if pagina_origen == "historial":
            return redirect("gestion_historial")
        if pagina_origen == "justificaciones":
            return redirect("gestion_justificaciones")
        return redirect("gestion_justificar")
    recientes = JustificacionAsistencia.objects.select_related("profesor", "creado_por").order_by("-creado_en")[:15]
    return render(request, "asistencias/gestion/justificar.html", {"form":form, "recientes": recientes})


@staff_member_required(login_url="/login/")
def reportes(request):
    hoy = timezone.localdate()
    return render(request, "asistencias/gestion/reportes.html", {
        "lunes": semana_actual(),
        "viernes": semana_actual() + timedelta(days=4),
        "elegibles": Profesor.objects.filter(activo=True, email__isnull=False).exclude(email="").count(),
        "lote": ReporteEnvio.objects.filter(semana_inicio=semana_actual()).first(),
        "anteriores": ReporteEnvio.objects.select_related("usuario").all()[:12],
        "dia": hoy.strftime("%A"),
    })


@staff_member_required(login_url="/login/")
@require_POST
def enviar_todos(request):
    if request.POST.get("confirmar") != "CONFIRMAR_ENVIO":
        messages.error(request, "Debes marcar la confirmación antes de enviar.")
        return redirect("gestion_reportes")
    try:
        lote = preparar_envio(origen="manual", usuario=request.user)
    except EnvioNoPermitido as exc:
        messages.error(request, str(exc))
        return redirect("gestion_reportes")
    if lote.estado == "completado":
        messages.success(request, f"Brevo aceptó {lote.enviados} correos. Consulta entregas en Brevo.")
    else:
        messages.error(request, f"Envío {lote.estado}: aceptados {lote.enviados}, errores {lote.errores}. No repitas el envío: revisa el historial.")
    return redirect("gestion_reportes")


@staff_member_required(login_url="/login/")
@require_http_methods(["GET"])
def simular_reportes(request):
    """Simula la semana actual sin enviar; accesible solo a staff."""
    salida = StringIO()
    try:
        call_command("enviar_reporte_asistencia", dry_run=True,
                     max_emails=40, stdout=salida, stderr=salida)
        return render(request, "asistencias/gestion/simulacion.html", {
            "salida": salida.getvalue(), "error": False,
        })
    except Exception:
        # No revelar detalles sensibles en HTML; el error real se registra.
        import logging
        logging.getLogger(__name__).exception("Error durante simulación")
        return render(request, "asistencias/gestion/simulacion.html", {
            "salida": "Error al preparar la simulación. Revisa los logs de Render.",
            "error": True,
        }, status=500)


# -------------------------------------------------------------------
# Todo el panel administrativo usa las mismas plantillas claras.
# Se conserva el administrador Django para funciones avanzadas.
# -------------------------------------------------------------------
class ProfesorGestionForm(forms.ModelForm):
    class Meta:
        model = Profesor
        fields = ["dni", "codigo", "apellidos", "nombres", "email", "sexo", "condicion", "tipo_jornada", "activo"]
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault("class", "campo")


class DiaEspecialGestionForm(forms.ModelForm):
    class Meta:
        model = DiaEspecial
        fields = ["fecha", "tipo", "descripcion", "activo"]
        widgets = {"fecha":forms.DateInput(format="%Y-%m-%d", attrs={"type":"date"})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault("class", "campo")


@staff_member_required(login_url="/login/")
def profesores(request):
    q = request.GET.get("q", "").strip()[:100]
    qs = Profesor.objects.all()
    if q:
        qs = qs.filter(Q(dni__icontains=q) | Q(codigo__icontains=q) | Q(nombres__icontains=q) | Q(apellidos__icontains=q) | Q(email__icontains=q))
    return render(request, "asistencias/gestion/profesores.html", {
        "busqueda":q,
        "pagina":Paginator(qs.order_by("apellidos", "nombres"), 25).get_page(request.GET.get("pagina")),
    })


@staff_member_required(login_url="/login/")
@require_http_methods(["GET", "POST"])
def profesor_formulario(request, pk=None):
    objeto = get_object_or_404(Profesor, pk=pk) if pk else None
    form = ProfesorGestionForm(request.POST or None, instance=objeto)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Datos del docente guardados correctamente.")
        return redirect("gestion_profesores")
    return render(request, "asistencias/gestion/formulario.html", {
        "titulo":"Editar docente" if objeto else "Agregar docente", "form":form,
        "volver":"gestion_profesores", "subtitulo":"No se modifica el historial de asistencias.",
    })


@staff_member_required(login_url="/login/")
def historial(request):
    from django.utils.dateparse import parse_date
    try:
        dia = parse_date(request.GET.get("fecha", "")) or timezone.localdate()
    except ValueError:
        dia = timezone.localdate()
    q = request.GET.get("q", "").strip()[:100]
    profesores_qs = Profesor.objects.all().order_by("apellidos", "nombres")
    if q:
        profesores_qs = profesores_qs.filter(Q(dni__icontains=q) | Q(nombres__icontains=q) | Q(apellidos__icontains=q) | Q(codigo__icontains=q))
    pagina = Paginator(profesores_qs, 30).get_page(request.GET.get("pagina"))
    ids = [p.pk for p in pagina.object_list]
    entradas = set(Asistencia.objects.filter(fecha=dia, tipo="E", profesor_id__in=ids).values_list("profesor_id", flat=True))
    justificados = {j.profesor_id:j for j in JustificacionAsistencia.objects.filter(fecha=dia, profesor_id__in=ids)}
    especial = DiaEspecial.objects.filter(fecha=dia, activo=True).first()
    rows = []
    for prof in pagina.object_list:
        if prof.pk in entradas:
            estado = "Asistió"
            estilo = "bien"
        elif prof.pk in justificados:
            estado = "Justificado"
            estilo = "justo"
        elif especial:
            estado = "Día especial"
            estilo = "justo"
        elif dia > timezone.localdate():
            estado = "Pendiente"
            estilo = "pendiente"
        else:
            estado = "Sin registro"
            estilo = "falta"
        rows.append({"profesor":prof,"estado":estado,"estilo":estilo})
    return render(request, "asistencias/gestion/historial.html", {
        "dia":dia, "dia_iso":dia.isoformat(), "busqueda":q, "filas":rows,
        "pagina":pagina, "especial":especial,
        "form":JustificacionRangoForm(initial={"desde":dia.isoformat(), "hasta":dia.isoformat()}),
        "origen":"historial",
    })


@staff_member_required(login_url="/login/")
def justificaciones(request):
    q = request.GET.get("q", "").strip()[:100]
    qs = JustificacionAsistencia.objects.select_related("profesor", "creado_por").all()
    if q:
        qs = qs.filter(Q(profesor__nombres__icontains=q) | Q(profesor__apellidos__icontains=q) | Q(profesor__dni__icontains=q))
    return render(request, "asistencias/gestion/justificaciones_lista.html", {
        "busqueda":q,"pagina":Paginator(qs, 30).get_page(request.GET.get("pagina")),
        "form":JustificacionRangoForm(), "origen":"justificaciones",
    })


@staff_member_required(login_url="/login/")
def dias_especiales(request):
    return render(request, "asistencias/gestion/dias_especiales.html", {
        "pagina":Paginator(DiaEspecial.objects.order_by("-fecha"), 30).get_page(request.GET.get("pagina")),
    })


@staff_member_required(login_url="/login/")
@require_http_methods(["GET", "POST"])
def dia_especial_formulario(request, pk=None):
    objeto = get_object_or_404(DiaEspecial, pk=pk) if pk else None
    form = DiaEspecialGestionForm(request.POST or None, instance=objeto)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Día especial guardado. El historial se actualizará al consultar esa fecha.")
        return redirect("gestion_dias_especiales")
    return render(request, "asistencias/gestion/formulario.html", {
        "titulo":"Editar día especial" if objeto else "Nuevo día especial", "form":form,
        "volver":"gestion_dias_especiales", "subtitulo":"Los días especiales activos no cuentan como falta.",
    })


@staff_member_required(login_url="/login/")
def historial_reportes(request):
    return render(request, "asistencias/gestion/envios_historial.html", {
        "pagina":Paginator(ReporteEnvio.objects.select_related("usuario"), 25).get_page(request.GET.get("pagina")),
    })


@staff_member_required(login_url="/login/")
@require_POST
def enviar_desde_enlace(request):
    """Alternativa al botón: permite pegar enlace privado solo en el panel.

    NO se realiza una petición HTTP al enlace que pega el usuario: se verifica el
    token local y se usa el MISMO control anti-duplicados del botón.
    """
    if request.POST.get("confirmar") != "CONFIRMAR_ENVIO":
        messages.error(request, "Debes marcar la confirmación antes de enviar.")
        return redirect("gestion_reportes")
    raw = (request.POST.get("enlace", "") or "").strip()
    try:
        parsed = urlsplit(raw)
        expected = (getattr(settings, "REPORT_TRIGGER_TOKEN", "") or "").strip()
        if not expected:
            from os import environ
            expected = (environ.get("REPORT_TRIGGER_TOKEN") or "").strip()
        parametros = parse_qs(parsed.query)
        token = parametros.get("token", [""])[0]
        # Un enlace de prueba/simulación JAMÁS debe iniciar un envío masivo.
        solo_token = set(parametros) == {"token"} and len(parametros["token"]) == 1
        ruta_ok = parsed.path == "/cron/reporte-asistencia/"
        host_ok = parsed.netloc.lower() == request.get_host().lower()
        protocolo_ok = parsed.scheme == "https"
        if not (solo_token and ruta_ok and host_ok and protocolo_ok and token and expected and secrets.compare_digest(token, expected)):
            messages.error(request, "Enlace no válido o token no coincide con el configurado en Render.")
            return redirect("gestion_reportes")
    except ValueError:
        messages.error(request, "El enlace introducido no es válido.")
        return redirect("gestion_reportes")
    # Reutiliza el mismo guardarraíl de semana ya procesada.
    return enviar_todos(request)
