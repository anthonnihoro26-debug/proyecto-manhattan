# asistencias/storage_backends.py
from cloudinary_storage.storage import MediaCloudinaryStorage
from cloudinary.utils import cloudinary_url
from whitenoise.storage import CompressedManifestStaticFilesStorage


class MediaCloudinaryStorageAuto(MediaCloudinaryStorage):
    """
    ✅ Sube con resource_type='auto'
    ✅ Entrega PDFs como IMAGE (image/upload) porque RAW te fallaba
    ✅ Imágenes normal (image/upload)
    """
    resource_type = "auto"

    def _looks_like_pdf(self, name: str) -> bool:
        n = (name or "").lower().strip()
        if n.endswith(".pdf"):
            return True
        if "justificaciones/" in n:
            return True
        return False

    def url(self, name, *args, **kwargs):
        if not name:
            return ""

        # ✅ PDF -> image/upload + format=pdf
        if self._looks_like_pdf(name):
            url, _ = cloudinary_url(
                name,
                resource_type="image",  # ✅ NO raw
                secure=True,
                format="pdf",
            )
            return url

        # ✅ Imágenes -> normal
        url, _ = cloudinary_url(
            name,
            resource_type="image",
            secure=True,
        )
        return url


class NonStrictCompressedManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """
    ✅ Evita que collectstatic falle cuando un CSS referencia .map que no existe
    (bootswatch/jazzmin a veces referencian .css.map y no viene el archivo)
    """
    manifest_strict = False
