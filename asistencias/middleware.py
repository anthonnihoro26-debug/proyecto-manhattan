from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

try:
    from axes.models import AccessAttempt
except Exception:
    AccessAttempt = None


def _cooloff_td():
    cooloff = getattr(settings, "AXES_COOLOFF_TIME", timedelta(minutes=15))
    if isinstance(cooloff, (int, float)):
        return timedelta(hours=float(cooloff))
    if isinstance(cooloff, timedelta):
        return cooloff
    return timedelta(minutes=15)


def _get_client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


class ClearAxesUnlockAtMiddleware:
    """
    Limpia request.session['axes_unlock_at'] automáticamente cuando:
    - ya expiró el tiempo, o
    - ya no hay registros de Axes (ej: después de python manage.py axes_reset)
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        unlock_at_str = request.session.get("axes_unlock_at")

        if unlock_at_str:
            # 1) Si ya expiró por tiempo: lo borra
            dt = parse_datetime(unlock_at_str)
            if dt and dt <= timezone.now():
                request.session.pop("axes_unlock_at", None)
                request.session.modified = True
            else:
                # 2) Si no expiró, pero BD ya no tiene intentos (axes_reset):
                #    comprobamos rápido si aún existe algún intento para IP
                if AccessAttempt is not None:
                    ip = _get_client_ip(request)
                    # Si NO hay intentos para esa IP, ya no debe estar bloqueado
                    if ip and not AccessAttempt.objects.filter(ip_address=ip).exists():
                        request.session.pop("axes_unlock_at", None)
                        request.session.modified = True

        return self.get_response(request)
