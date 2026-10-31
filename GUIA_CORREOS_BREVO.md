# MANHATTAN – ASISTENCIAS – Reparación y prueba de correos de Brevo

Este arreglo solo cambia el enlace de envío de **reportes de asistencia**. No cambia los modelos ni las migraciones, ni modifica los registros de profesores y asistencias, CV o reuniones.

## 1. Sustituir el código sin perder datos (Windows)

1. Cierra VS Code y haz una **copia completa de seguridad** de la carpeta `proyecto_manhattan` que aparece en tu Explorador de Windows; no borres la original.
2. Descomprime el ZIP completo: trae una carpeta llamada `proyecto_manhattan` con la misma estructura de código.
3. Abre la carpeta `proyecto_manhattan` **del ZIP**, selecciona **todos sus archivos y carpetas**, cópialos y pégalos **dentro de tu carpeta original `proyecto_manhattan`**. Cuando Windows pregunte, elige reemplazar archivos con el mismo nombre. **No borres antes la carpeta original.**
4. Como el ZIP limpio no incluye `.git`, `media`, `staticfiles`, `db.sqlite3`, `profesores.json`, `asistencias.json` ni `.env`, esas carpetas y archivos permanecen en tu copia original y no serán reemplazados.
5. Verifica los cambios con `git status` y `git diff` antes de subirlos. Ejecuta `git add -A`, `git commit -m "Prueba segura de correo Brevo"`, `git push origin main` **solo cuando quieras actualizar Render**. Si el servicio tiene *Auto Deploy* habilitado, hacer push puede desplegar de inmediato.

**No** borres `.git`, `media`, `db.sqlite3` ni otra información de tu carpeta original. La información real de producción se conserva en la PostgreSQL configurada mediante `DATABASE_URL`; este ZIP no mueve ni copia sus registros.


Si utilizas GitHub y Render, los cambios del ZIP solo se aplicarán al sitio desplegado **después** de `git push` y de que Render complete un deploy. La opción *Save only* para variables de entorno NO actualiza el servicio en ejecución.

## 2. Variables en Render → Environment (sin mostrar sus valores)

- `BREVO_API_KEY`: **clave API nueva** de Brevo con permiso **Emails transaccionales → Todos**.
- `BREVO_SENDER_EMAIL`: dirección de remitente autorizada/verificada en Brevo.
- `REPORT_TRIGGER_TOKEN`: token actual de tu enlace privado; **no debe ser la clave API de Brevo**.
- `EMAIL_HOST_PASSWORD`: **clave SMTP** distinta. El enlace del reporte de asistencias utiliza API y no depende de ella.
- `DATABASE_URL`: **no modificar**.

**No compartas** contraseñas, tokens, `.env`, `DATABASE_URL` ni capturas con valores visibles.

## 3. Probar sin enviar reportes masivos

Una vez desplegado el nuevo código y cuando `proyecto-manhattan` aparezca *Live*:

**Verificar configuración (no envía):**

```
https://proyecto-manhattan.onrender.com/cron/reporte-asistencia/?token=TU_TOKEN&modo=verificar
```

`ok: true` solo dice que las variables están cargadas: **no valida la clave en los servidores de Brevo**.

**Correo de prueba (envía SOLO uno, sin registros de profesores):**

```
https://proyecto-manhattan.onrender.com/cron/reporte-asistencia/?token=TU_TOKEN&modo=prueba&correo=tu_correo%40ejemplo.com
```

Sustituye `tu_correo%40ejemplo.com` por **tu propio correo**, escribiendo `@` en vez de `%40` si quieres. Brevo debe aceptar el envío y el correo debe llegar a la bandeja de entrada (revisa también spam). No abras el enlace de prueba repetidamente.

**Simulación de reportes (sin enviar):**

```
https://proyecto-manhattan.onrender.com/cron/reporte-asistencia/?token=TU_TOKEN&modo=simular
```

## 4. Enviar reportes reales, solo cuando estés listo

El enlace histórico **SIN `modo`** permanece exactamente como antes:

```
https://proyecto-manhattan.onrender.com/cron/reporte-asistencia/?token=TU_TOKEN
```

**ATENCIÓN: al abrir ese enlace intenta enviar reportes reales a los docentes**; el comando original limita a 40 correos entregados a Brevo por ejecución y NO cuenta con bloqueo de duplicados. No lo abras varias veces ni compartas el enlace.

Si la prueba devuelve `ok: false`, entra a Render → proyecto-manhattan → Logs y revisa el error **sin compartir tokens**. Un `401` de Brevo normalmente indica clave API inválida/desactivada; un `403` puede ser falta de permisos o cuenta restringida; errores `4xx` también pueden señalar remitente no autorizado. Corrige la causa antes de un envío masivo.

Si Render o su base PostgreSQL siguen suspendidos, reanúdalos y verifica su estado antes de probar el envío de reportes.

## Seguridad y datos

Este ZIP no incluye `.git`, `.env`, `DATABASE_URL`, bases SQLite locales, archivos privados de profesores, archivos del directorio `media/` ni `staticfiles/` generado. La fuente original incluía material sensible y no debería subirse a repositorios públicos. La URL privada contiene un token que puede quedar registrado en el historial del navegador; considéralo un secreto y rótalo si se ha expuesto.

## Pruebas locales (sin enviar correos reales)

```bash
python manage.py test asistencias.test_reporte_correos
```

Las pruebas utilizan mocks; no envían nada a Brevo. Debes configurar Django y sus dependencias antes de ejecutarlas en un entorno real.

## 5. Particularidades del envío original

- El enlace original ejecuta el envío real sin una confirmación adicional: abrirlo desde el navegador puede enviar mensajes inmediatamente.
- Por defecto solo envía **hasta 40 correos aceptados** por Brevo cada vez; esto **no garantiza que todos los docentes reciban** el reporte si hay más de 40. **No ejecutes otra vez el enlace para alcanzar el resto**, porque se repetiría a los primeros destinatarios.
- El sistema original **no registra qué docentes ya recibieron el reporte**. Para envío a más de 40 o reintentos sin duplicados será necesaria una mejora posterior, que debe revisarse con cuidado.
- Una prueba con `modo=prueba` solo confirma que Brevo acepta un mensaje neutro; no confirma que los reportes de todos los docentes estén bien ni garantiza la entrega final en la bandeja.
- Si ves *Suspended* en Render, la web o la PostgreSQL no funcionarán correctamente hasta que estén activos.

## 6. Enviar UN REPORTE REAL a UN SOLO docente (antes del envío general)

La versión incluye dos modos nuevos que usan el mismo cálculo y diseño HTML
que el correo semanal real, sin cambiar base de datos, migraciones ni modelos.

**Simular ese docente sin enviar nada:**

```
https://proyecto-manhattan.onrender.com/cron/reporte-asistencia/?token=TU_TOKEN&modo=reporte-simular&correo=anthonnihoro26@gmail.com
```

**Enviar UN reporte real solo a ese docente:**

```
https://proyecto-manhattan.onrender.com/cron/reporte-asistencia/?token=TU_TOKEN&modo=reporte-prueba&correo=anthonnihoro26@gmail.com
```

- Confirma que el correo está registrado en exactamente **un** docente. Si no existe o está repetido, la función se niega a enviar.
- Solo genera el reporte de ese docente y lo envía al correo que figura en su ficha. **No envía a los otros docentes**.
- El correo se arma con la información real de asistencias/justificaciones de esa semana, no con un texto técnico.
- El enlace nuevo requiere **actualizar GitHub y completar un despliegue en Render**. No lo ejecutes hasta que Render aparezca Live con el nuevo commit.
- Abre el enlace real una sola vez y comprueba recepción y diseño en Gmail. Repetir la URL provoca otro envío de ese mismo reporte.
- El enlace original sin `modo` conserva el envío general, con sus precauciones (40 máximo por ejecución; sin deduplicación).
- **No compartas el token completo**. Como va en la URL, queda en el historial del navegador.


## 7. Plantilla institucional compacta (nueva versión)

El correo de asistencia usa un diseño institucional guinda/dorado discreto, con ancho máximo
aproximado de 600 px, tablas compatibles con Gmail y seis indicadores compactos.
Se retiró por completo el mensaje de **marcha blanca** tanto del HTML como de la
versión de texto; se conserva el cálculo de asistencia, justificaciones, días especiales,
faltas, cumplimiento y todos los mecanismos de envío del código anterior.

**Primero comprueba SOLO el reporte real de tu docente de prueba:**

```
https://proyecto-manhattan.onrender.com/cron/reporte-asistencia/?token=TU_TOKEN&modo=reporte-simular&correo=anthonnihoro26@gmail.com
```

Cuando aparezca un solo docente sin errores, utiliza **una sola vez**:

```
https://proyecto-manhattan.onrender.com/cron/reporte-asistencia/?token=TU_TOKEN&modo=reporte-prueba&correo=anthonnihoro26@gmail.com
```

No olvides que estas URL solo estarán disponibles tras desplegar la nueva versión en Render.
El envío general (sin `modo`) sigue siendo real y no tiene protección contra duplicados.
No lo ejecutes hasta validar los reportes y destinatarios.


## Versión V4: resumen con dos indicadores

El correo ahora presenta solo dos indicadores visuales compactos (Asistencias y Cumplimiento).
Días evaluables, faltas, justificaciones y días especiales aparecen en texto discreto debajo.
Los cálculos, la tabla diaria, las rutas de simulación y prueba individual, los destinatarios y los envíos no cambiaron.
No ejecuta automáticamente correos al instalarse.
