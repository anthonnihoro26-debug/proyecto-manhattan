#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate
# Crea admin solamente si falta y existen DJANGO_SUPERUSER_USERNAME y PASSWORD.
# Nunca restablece la contraseña ni modifica usuarios existentes.
python manage.py ensure_admin
