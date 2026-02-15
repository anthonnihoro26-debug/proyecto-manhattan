# asistencias/storage_backends.py
from cloudinary_storage.storage import MediaCloudinaryStorage
from cloudinary.utils import cloudinary_url

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

