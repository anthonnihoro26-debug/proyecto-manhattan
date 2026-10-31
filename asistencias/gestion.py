"""Gestión rápida para administradores, sin reemplazar los modelos históricos."""
from datetime import timedelta
from django import forms
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
            fechas = []
            for cursor in posibles:
                if cursor.weekday() < 5 and cursor not in especiales:
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
    form = JustificacionRangoForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        datos = form.cleaned_data
        prof = datos["profesor"]
        candidatas = datos["fechas_habiles"]
        # No se crean justificantes sobre días especiales institucionales activos.
        especiales = set(DiaEspecial.objects.filter(fecha__in=candidatas, activo=True).values_list("fecha", flat=True))
        validas = [d for d in candidatas if d not in especiales]
        existentes = set(JustificacionAsistencia.objects.filter(profesor=prof, fecha__in=validas).values_list("fecha", flat=True))
        pendientes = [d for d in validas if d not in existentes]
        if not pendientes:
            messages.warning(request, "No se crearon registros: las fechas ya estaban justificadas o son días especiales.")
            return redirect("gestion_justificar")
        # Subimos un PDF una sola vez para asociar una misma ruta a todos los días.
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
                    profesor=prof,
                    fecha=dia,
                    defaults={
                        "tipo": datos["tipo"], "detalle": datos["detalle"],
                        "archivo": nombre_guardado,
                        "creado_por": request.user,
                        "actualizado_por": request.user,
                    },
                )
                creados += int(nuevo)
        messages.success(request,
            f"Justificaciones creadas: {creados}. Ya existentes: {len(existentes)}. "
            f"Días especiales excluidos: {len(especiales)}. Se reflejarán en Historial.")
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
