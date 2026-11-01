# Manhattan Asistencias V9 — panel blanco unificado

## Cambios
- Se conserva el mismo login de Manhattan; el usuario admin autorizado entra a `/gestion/`.
- Profesores, agregar y editar profesor, historial, justificaciones y días especiales se abren con el diseño blanco del panel, ya no saltan al administrador azul.
- El formulario **Justificar rango** se puede utilizar directamente en **Historial** y **Justificaciones**. Admite `Desde` / `Hasta` o **cantidad de días hábiles**, motivo, observación y un PDF opcional. Cada fecha justificada queda registrada individualmente.
- No se justifican días especiales ni fechas con una entrada ya registrada; no se sobrescriben justificaciones existentes.
- La lista diaria del historial mostrará **Justificado** al elegir una fecha incluida en el rango.
- En `Gestión → Envío de reportes` se conserva el botón general con confirmación y simulación, y se añade un formulario para pegar el enlace antiguo con el token privado. **No se abre una URL externa**: se valida contra el mismo host y token almacenado en Render y se invoca el mismo control de envío una vez por semana.
- Solo acepta el enlace de envío general con `?token=...`, nunca los enlaces `modo=prueba` ni `modo=simular`. El token no se guarda en la base de datos.
- Conserva el formato de correo institucional aprobado, la función de correo individual de prueba y el comando del viernes.
- No incluye cambios de modelos ni migraciones nuevas.

## Instalación
1. Haz copia de seguridad del código y respaldo independiente de PostgreSQL antes del despliegue.
2. Descomprime el ZIP y copia el contenido de la carpeta `proyecto_manhattan/` dentro de tu carpeta de trabajo original, eligiendo **reemplazar archivos** sin borrar la carpeta original.
3. Mantén intactos `.git/`, `.env`, `media/`, tu `db.sqlite3` local si existe, y la base PostgreSQL de Render.
4. Verifica los cambios en VS Code y ejecuta desde la raíz del repositorio:

```bash
git status
git add asistencias/gestion.py asistencias/templates/asistencias/gestion asistencias/static/asistencias/css/gestion.css asistencias/test_panel_gestion.py proyecto_manhattan/urls.py LEEME_INSTALACION_MANHATTAN_V9.md
git diff --cached --stat
git commit -m "Panel blanco unificado y justificaciones por rango V9"
git push origin main
```

`git push` puede activar Auto Deploy en Render. Comprueba antes que el estado de PostgreSQL y el servicio sean correctos y que el backup esté disponible.

## Comprobaciones seguras tras el despliegue
- Inicia sesión con la cuenta administradora que ya creaste y abre `/gestion/`.
- Abre **Profesores**, **Historial**, **Justificaciones**, **Días especiales** y **Envío de reportes**: todo dentro del mismo panel claro.
- Prueba un rango **solo en un docente de prueba** que no tenga asistencia en esos días. Comprueba las fechas individualmente en Historial y el listado de Justificaciones.
- Para correos empieza con **Simular esta semana sin enviar**. No pegues el enlace privado en capturas ni lo compartas; el botón general enviará correos reales.
- El Cron Job de los viernes se debe crear aparte en Render; no se activa por el ZIP.

## Límites
- El envío general sigue limitado a 40 destinatarios activos por ejecución y protegido contra dobles envíos semanales.
- Las credenciales de administrador no se redefinen con esta versión.
- No se realizó ninguna conexión a tu Render ni envío real desde este entorno.
- No se pudieron ejecutar tests Django integrales aquí porque las dependencias no están instaladas ni existe conexión a tu PostgreSQL. La sintaxis Python, rutas y archivos HTML fueron revisados estáticamente.
