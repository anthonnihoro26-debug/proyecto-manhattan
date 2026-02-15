# asistencias/storage_backends.py
from cloudinary_storage.storage import MediaCloudinaryStorage
from cloudinary.utils import cloudinary_url

from whitenoise.storage import CompressedManifestStaticFilesStorage
from whitenoise.storage import MissingFileError


class MediaCloudinaryStorageAuto(MediaCloudinaryStorage):
    """
    ✅ Sube con resource_type='auto'
    ✅ Entrega PDFs como IMAGE (image/upload) para evitar RAW
    """
    resource_type = "auto"

    def _looks_like_pdf(self, name: str) -> bool:
        n = (name or "").lower()
        if n.endswith(".pdf"):
            return True
        if "media/justificaciones/" in n or "justificaciones/" in n:
            return True
        return False

    def url(self, name, *args, **kwargs):
        if not name:
            return ""

        # ✅ PDF -> forzamos image/upload y format=pdf
        if self._looks_like_pdf(name):
            url, _ = cloudinary_url(
                name,
                resource_type="image",
                secure=True,
                format="pdf",
            )
            return url

        # ✅ resto (imágenes) normal
        url, _ = cloudinary_url(
            name,
            resource_type="image",
            secure=True,
        )
        return url


class NonStrictCompressedManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """
    ✅ Arregla el deploy en Render:
    - Ignora faltantes de *.css.map referenciados por bootswatch
    """
    manifest_strict = False

    def post_process(self, paths, dry_run=False, **options):
        try:
            yield from super().post_process(paths, dry_run=dry_run, **options)
        except MissingFileError as e:
            msg = str(e)

            # ✅ Ignorar sourcemaps faltantes (.css.map) que rompen el build
            if ".css.map" in msg or "bootstrap.min.css.map" in msg:
                # seguimos sin tumbar el deploy
                return

            # si es otra cosa, sí levantamos el error
            raise
