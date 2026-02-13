# asistencias/storage_backends.py
from cloudinary_storage.storage import MediaCloudinaryStorage
from cloudinary.utils import cloudinary_url


class MediaCloudinaryStorageAuto(MediaCloudinaryStorage):
    """
    Sube con resource_type='auto'.
    Al generar URL:
      - si es PDF -> entrega como RAW y fuerza extensión .pdf
      - si no -> entrega como IMAGE
    """
    resource_type = "auto"

    def _looks_like_pdf(self, name: str) -> bool:
        n = (name or "").lower()

        # Si ya tiene .pdf
        if n.endswith(".pdf"):
            return True

        # Si está en tu carpeta de justificaciones (tu caso)
        if "justificaciones/" in n or "/justificaciones/" in n:
            return True

        return False

    def url(self, name, *args, **kwargs):
        if not name:
            return ""

        if self._looks_like_pdf(name):
            # ✅ RAW + FORZAR .pdf
            url, _ = cloudinary_url(
                name,
                resource_type="raw",
                secure=True,
                format="pdf",   # <- esto hace que termine en .pdf
            )
            return url

        # ✅ resto como imagen normal
        url, _ = cloudinary_url(
            name,
            resource_type="image",
            secure=True,
        )
        return url
