import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = "Crea/actualiza superusuario con variables DJANGO_SUPERUSER_*"

    def handle(self, *args, **options):
        User = get_user_model()

        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not username or not password:
            self.stdout.write("Faltan DJANGO_SUPERUSER_USERNAME o DJANGO_SUPERUSER_PASSWORD")
            return

        user, created = User.objects.get_or_create(username=username, defaults={"email": email})

        # SIEMPRE actualiza contraseña (para que tu variable sí funcione)
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        if created:
            self.stdout.write(f"Superusuario '{username}' CREADO/ACTUALIZADO.")
        else:
            self.stdout.write(f"Superusuario '{username}' YA EXISTÍA, contraseña ACTUALIZADA.")
