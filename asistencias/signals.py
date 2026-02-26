from decimal import Decimal, InvalidOperation

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from .models import LoginEvidencia


def _to_decimal(value):
    try:
        if value in (None, ""):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _get_client_ip(request):
    if not request:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _post_val(request, key, default=""):
    if not request:
        return default
    return (request.POST.get(key) or default).strip()


@receiver(user_logged_in)
def guardar_evidencia_login_exitoso(sender, request, user, **kwargs):
    """
    Se dispara cuando el login fue exitoso.
    """
    try:
        LoginEvidencia.objects.create(
            usuario=user,
            username_intentado=(getattr(user, "username", "") or _post_val(request, "username"))[:150],
            exito=True,
            fecha_hora_cliente=_post_val(request, "geo_time"),
            latitud=_to_decimal(_post_val(request, "geo_lat")),
            longitud=_to_decimal(_post_val(request, "geo_lng")),
            precision_m=_to_decimal(_post_val(request, "geo_acc")),
            estado_geo=_post_val(request, "geo_status")[:50],
            permiso_geo=_post_val(request, "geo_perm_state")[:20],
            device_info=_post_val(request, "device_info"),
            ip=_get_client_ip(request),
        )
    except Exception:
        # Nunca romper login por falla de auditoría
        pass


@receiver(user_login_failed)
def guardar_evidencia_login_fallido(sender, credentials, request, **kwargs):
    """
    Se dispara cuando falla el login.
    """
    try:
        username_intentado = ""
        if isinstance(credentials, dict):
            username_intentado = (credentials.get("username") or credentials.get("email") or "")[:150]

        LoginEvidencia.objects.create(
            usuario=None,
            username_intentado=username_intentado,
            exito=False,
            fecha_hora_cliente=_post_val(request, "geo_time"),
            latitud=_to_decimal(_post_val(request, "geo_lat")),
            longitud=_to_decimal(_post_val(request, "geo_lng")),
            precision_m=_to_decimal(_post_val(request, "geo_acc")),
            estado_geo=_post_val(request, "geo_status")[:50],
            permiso_geo=_post_val(request, "geo_perm_state")[:20],
            device_info=_post_val(request, "device_info"),
            ip=_get_client_ip(request),
        )
    except Exception:
        pass