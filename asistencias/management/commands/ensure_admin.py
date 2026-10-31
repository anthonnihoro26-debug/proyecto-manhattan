import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = "Crea superusuario inicial sin restablecer contraseñas existentes (DJANGO_SUPERUSER_*)"

    def handle(self, *args, **options):
        User = get_user_model()

        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not username or not password:
            self.stdout.write(self.style.WARNING("Faltan DJANGO_SUPERUSER_USERNAME o DJANGO_SUPERUSER_PASSWORD"))
            return

        user, created = User.objects.get_or_create(username=username, defaults={"email": email})

        if created:
            user.is_staff = True
            user.is_superuser = True
            user.set_password(password)
            user.save(update_fields=["is_staff", "is_superuser", "password"])
            self.stdout.write(self.style.SUCCESS(f"Superusuario '{username}' creado."))
        else:
            # CRÍTICO: nunca restablecer contraseñas/permisos en cada deploy.
            self.stdout.write(self.style.SUCCESS(f"El usuario '{username}' ya existe; se respetaron sus credenciales."))
