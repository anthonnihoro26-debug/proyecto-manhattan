# Manhattan Asistencias — Administrador simple V10

Esta versión conserva la aplicación Asistencias, el correo institucional de dos tarjetas y la lógica existente de Brevo. No añade migraciones ni altera tablas históricas.

## Menú administrativo

El login habitual de Manhattan para una cuenta administradora lleva a `/gestion/`.

- **Profesores**: listar, buscar, agregar y editar sin abrir el antiguo admin azul.
- **Asistencias**: consultar los estados de un día con selector de fecha; o buscar un docente y revisar sus marcas de fechas diferentes. Las fechas no laborables no se presentan como faltas.
- **Justificaciones**: elegir docente y justificar un día (atajo Ayer), un rango desde/hasta o una cantidad de días hábiles. No se solicita «Tipo». Internamente se usa el código genérico O («Otro») conservando el campo existente del modelo. Los motivos históricos se mantienen sin modificaciones. No se justifica encima de una entrada o justificación previa; se omiten días especiales y fines de semana.
- **Días especiales**: crear, editar y listar.
- **Correos**: conserva simulación y botón protegido de envío semanal (máximo 40 destinatarios elegibles, con control de repetición); también entrada privada del enlace de reportes y opción de cron los viernes, que necesita configuración en Render.

## Instalación

1. **Respalda** la carpeta local, el historial Git y PostgreSQL de Render antes de desplegar.
2. Descomprime el ZIP y copia los archivos del interior de `proyecto_manhattan/` a tu carpeta de proyecto original (la que contiene `manage.py`). Reemplaza los archivos homónimos, **sin borrar primero la carpeta original**.
3. Conserva los archivos de datos y credenciales locales (no vienen en este ZIP): `.git`, `.env`, `db.sqlite3` y `media/`.
4. Abre PowerShell en el directorio de `manage.py` y ejecuta los comandos de la conversación. Revisa `git status` antes del push. El push puede activar un despliegue automático en Render.
5. En Render, tras pasar a Live, revisa el menú y realiza una prueba de justificación con un docente de pruebas. Antes de un envío general, comprueba que los correos activos no estén duplicados y realiza una simulación.

## Comandos para GitHub

```powershell
git status
git add asistencias/gestion.py asistencias/templates/asistencias/gestion asistencias/static/asistencias/css/gestion.css asistencias/test_panel_gestion.py LEEME_PANEL_SIMPLE_V10.md
git diff --cached --stat
git commit -m "Simplificar panel de asistencias y justificaciones V10"
git push origin main
```

Los comandos de la carpeta `asistencias/management/commands` **no se borraron**, porque se utilizan para el administrador y los envíos de reportes. No se cambió el código de envío de Brevo.

## Verificaciones

Se revisaron los archivos Python y la estructura de rutas/plantillas. **Las pruebas integrales en Django/PostgreSQL y un envío real no se ejecutaron aquí**, por no disponer de Django ni de acceso a los servicios del usuario. Por ello se debe validar en Render primero con un docente de prueba.
