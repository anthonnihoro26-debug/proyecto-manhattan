"""
URL configuration for proyecto_manhattan project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

from asistencias import views as asist_views

urlpatterns = [
    path('admin/', admin.site.urls),

    # ✅ Login
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),

    # ✅ Logout (te regresa al login)
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    # ✅ Post-login redirect por grupo (GEORGE o JORGE)
    path('', asist_views.post_login_redirect, name='post_login'),

# ✅ CRON PRIVADO (DEBE ESTAR AQUÍ, EN EL ROOT)
    path("cron/reporte-asistencia/", asist_views.trigger_reporte_asistencia, name="cron_reporte_asistencia"),

    
    # ✅ App
    path('asistencia/', include('asistencias.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

