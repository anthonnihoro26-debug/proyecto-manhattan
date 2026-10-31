# MANHATTAN — ASISTENCIAS / Panel administrativo limpio

## Alcance
- Un solo login institucional: `/login/` para profesores y el administrador.
- El superusuario **admin** entra directamente a `/gestion/`.
- Accesos a profesores, asistencias, justificaciones, días especiales y reportes desde Gestión.
- Justificaciones por rango o cantidad de días hábiles excluyendo días especiales; se conserva cada día en el historial.
- El correo institucional compacto (dos tarjetas) conserva los cálculos y la tabla diaria.
- El botón **Simular** NO envía; el botón **Enviar a todos** requiere sesión staff y confirmación, y registra un único lote semanal.
- Los enlaces originales de prueba con `modo=reporte-prueba` y `modo=reporte-simular` se mantienen para pruebas individuales.
- **Por seguridad, el enlace antiguo sin `modo` ya NO envía correos masivos**. Usa `/gestion/reportes/` para los envíos generales.

## Qué se ha limpiado
- No se empaquetan `.git`, `.env`, contraseñas, `db.sqlite3`, `media`, `staticfiles`, `__pycache__`, exportaciones JSON o caches.
- **Los comandos bajo `asistencias/management/commands/` se conservan porque son necesarios**: `ensure_admin.py` crea el administrador, `enviar_reporte_asistencia.py` genera los correos y `enviar_reportes_viernes.py` sirve para automatizar los viernes.
- No se borran ni recrean las tablas antiguas de profesores, asistencias o justificaciones.
- Migración `0017_reporteenvio.py`: agrega una tabla nueva para controlar los lotes semanales, sin borrar asistencias.

## Instalación en tu PC
1. Haz respaldo de tu carpeta original y de PostgreSQL en Render antes de desplegar.
2. Descomprime el ZIP. **Copia el contenido INTERIOR de `proyecto_manhattan/` encima de tu carpeta original**, sin borrarla. Conserva tu `.git`, `.env`, `media`, `db.sqlite3` y demás archivos de datos. Los archivos antiguos de guías, si quedaron, son inocuos; puedes eliminarlos manualmente si deseas.
3. Abre PowerShell o terminal de VS Code en la carpeta donde está `manage.py`.
4. Con el entorno Python de tu proyecto y una base de datos de prueba, verifica:

   ```bash
   python manage.py check
   python manage.py migrate --plan
   python manage.py test asistencias.test_login_admin_unico asistencias.test_panel_gestion asistencias.test_reporte_correos
   ```
5. Verifica `git status`. Confirma que no estén cambiando bases locales o secretos.
6. Subir solo código, no credenciales:

   ```bash
   git add asistencias proyecto_manhattan build.sh requirements.txt render.yaml LEEME_INSTALACION_MANHATTAN.md
   git status
   git commit -m "Panel de administracion limpio y envio seguro Manhattan"
   git push origin main
   ```
   **Atención:** `git push` puede activar el despliegue automático en Render.

## Usuario administrador
Render > `proyecto-manhattan` > Environment:
- `DJANGO_SUPERUSER_USERNAME=admin`
- `DJANGO_SUPERUSER_EMAIL=` tu correo administrador.
- `DJANGO_SUPERUSER_PASSWORD=` contraseña **inicial** que elegiste (solo si el usuario todavía no existe).

El comando `ensure_admin` crea la cuenta **solo cuando no existe**. No restablece contraseñas de cuentas existentes.
Tu contraseña inicial solicitada `12345678` es insegura: cámbiala por una larga y única antes de usar el sistema con datos reales. Luego retira la contraseña inicial de las variables de Render. La pantalla muestra un aviso mientras siga en uso.

## Brevo
Conservar en Render las variables `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME` y `REPORT_TRIGGER_TOKEN` con sus valores privados, sin compartirlos. En `Environment`, cambiar la clave no cambia nada hasta el siguiente despliegue.
El envío de reporte usa la API de Brevo, no la contraseña SMTP.

Para **una prueba individual real**, luego de desplegar, abre este enlace con tu token secreto y SOLO tu correo asociado a un único profesor:

`https://proyecto-manhattan.onrender.com/cron/reporte-asistencia/?token=TU_TOKEN&modo=reporte-prueba&correo=anthonnihoro26@gmail.com`

No abra el enlace antiguo sin modo para enviar a todos: el nuevo sistema responde que se use el panel.
Para enviar a todos, inicia sesión y abre `/gestion/reportes/`, primero simula y luego confirma el botón de envío.

## Viernes automáticos (no activados por el ZIP)
Si después quieres activar el envío automático en Render, crea un Cron Job con el comando:
`python manage.py enviar_reportes_viernes`
Cron: `0 23 * * 5` (viernes a las 18:00 hora de Lima, UTC-5, sin horario de verano). Usa la misma PostgreSQL y variables Brevo que el Web Service.
Se impide repetir automáticamente el lote de la semana; si hay error o envío parcial hay que investigarlo en el panel y Brevo.

## Limitaciones / validación pendiente
No es posible comprobar desde aquí tu PostgreSQL real, las credenciales o el Render desplegado. En este ambiente no están instaladas las dependencias de Django, por lo que no se ejecutó la batería de tests integrada; sí se comprueba la sintaxis y la estructura del ZIP.
En el primer despliegue asegúrate de que se aplique la migración 0017, de que `admin` tenga permisos de staff/superuser y de que PostgreSQL esté disponible.
