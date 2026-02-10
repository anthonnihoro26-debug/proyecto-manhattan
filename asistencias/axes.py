from datetime import timedelta

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from axes.models import AccessAttempt


def _get_client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _get_cooloff_td() -> timedelta:
    cooloff = getattr(settings, "AXES_COOLOFF_TIME", timedelta(minutes=15))
    if isinstance(cooloff, (int, float)):
        return timedelta(hours=float(cooloff))
    if isinstance(cooloff, timedelta):
        return cooloff
    return timedelta(minutes=15)


def _get_unlock_time(request, username: str):
    ip = _get_client_ip(request)
    cooloff = _get_cooloff_td()

    qs = AccessAttempt.objects.filter(username=username, ip_address=ip)
    if not qs.exists():
        qs = AccessAttempt.objects.filter(ip_address=ip)
        if not qs.exists():
            return None

    latest = qs.order_by("-attempt_time").first()
    last_dt = getattr(latest, "attempt_time", None)
    if not last_dt:
        return None

    if timezone.is_naive(last_dt):
        last_dt = timezone.make_aware(last_dt, timezone.get_current_timezone())

    return last_dt + cooloff


def lockout(request, response, credentials, *args, **kwargs):
    """
    Cuando Axes bloquea: guardamos en sesión la hora exacta de desbloqueo.
    NO enviamos messages para evitar duplicados; el HTML muestra el contador.
    """
    username = ""
    if isinstance(credentials, dict):
        username = credentials.get("username") or ""

    unlock_time = _get_unlock_time(request, username)
    if unlock_time:
        request.session["axes_unlock_at"] = unlock_time.isoformat()
        request.session.modified = True

    login_url = reverse("login")
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url:
        return redirect(f"{login_url}?{urlencode({'next': next_url})}")

    return redirect(login_url)
