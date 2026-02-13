# asistencias/storage_backends.py
from cloudinary_storage.storage import MediaCloudinaryStorage
from cloudinary.utils import cloudinary_url


class MediaCloudinaryStorageAuto(MediaCloudinaryStorage):
    """
    - Sube con resource_type='auto' (Cloudinary detecta si es PDF/imagen/video)
    - Pero al generar URL:
        * si es PDF -> usa 'raw' (evita 401 por intentar servirlo como image)
        * si no -> usa 'image'
    """

    resource_type = "auto"

    def _delivery_resource_type(self, name: str) -> str:
        n = (name or "").lower()

        # Si el nombre guarda extensión, perfecto
        if n.endswith(".pdf"):
            return "raw"

        # Si NO guarda extensión (a veces Cloudinary genera sin .pdf),
        # como este campo es "archivo" de justificaciones,
        # asumimos raw cuando venga en esa carpeta:
        if "/justificaciones/" in n or "justificaciones/" in n:
            return "raw"

        return "image"

    def url(self, name, **options):
        options = options or {}
        options.setdefault("secure", True)
        options["resource_type"] = self._delivery_resource_type(name)

        # cloudinary_url devuelve (url, options)
        return cloudinary_url(name, **options)[0]
