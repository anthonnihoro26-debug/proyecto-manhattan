# asistencias/storage_backends.py
from cloudinary_storage.storage import MediaCloudinaryStorage
from cloudinary.utils import cloudinary_url


class MediaCloudinaryStorageAuto(MediaCloudinaryStorage):
    """
    ✅ Sube con resource_type='auto'
    ✅ Entrega:
      - PDFs: como IMAGE (image/upload) porque RAW te está fallando
      - Imágenes: como IMAGE normal
    """
    resource_type = "auto"

    def _looks_like_pdf(self, name: str) -> bool:
        n = (name or "").lower()
        if n.endswith(".pdf"):
            return True
        # si guardas PDFs dentro de esta carpeta, también lo tratamos como PDF
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
                resource_type="image",  # 👈 IMPORTANTE: NO raw
                secure=True,
                format="pdf",           # 👈 fuerza .pdf al final
            )
            return url

        # ✅ resto (imágenes) normal
        url, _ = cloudinary_url(
            name,
            resource_type="image",
            secure=True,
        )
        return url
