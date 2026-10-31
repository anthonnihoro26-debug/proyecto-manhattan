from django.core.management.base import BaseCommand
from django.utils import timezone
from asistencias.servicio_reportes import preparar_envio, EnvioNoPermitido

class Command(BaseCommand):
    help = "Envía reportes solo los viernes, una vez por semana y con registro antifallos/duplicados."

    def handle(self, *args, **options):
        if timezone.localdate().weekday() != 4:
            self.stdout.write("No es viernes en Perú: sin envíos.")
            return
        try:
            lote = preparar_envio(origen="viernes")
        except EnvioNoPermitido as exc:
            self.stdout.write(self.style.WARNING(str(exc)))
            return
        self.stdout.write(f"Lote {lote.pk}: {lote.estado}, enviados={lote.enviados}, errores={lote.errores}")
        if lote.estado != "completado":
            raise RuntimeError("El lote no terminó completamente. Revisar el panel antes de cualquier reintento.")
