# asistencias/storage_backends.py
from cloudinary_storage.storage import MediaCloudinaryStorage

class MediaCloudinaryStorageAuto(MediaCloudinaryStorage):
    # auto soporta raw/pdf e imágenes sin romper
    resource_type = "auto"