# asistencias/storage_backends.py
from cloudinary_storage.storage import MediaCloudinaryStorage

class MediaCloudinaryStorageAuto(MediaCloudinaryStorage):
    """
    Cloudinary acepta:
    - image (por defecto)
    - raw (PDF, doc, zip)
    - auto (detecta)
    Usamos auto para que PDF no reviente.
    """
    resource_type = "auto"
