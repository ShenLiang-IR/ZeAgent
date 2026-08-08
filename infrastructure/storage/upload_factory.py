from typing import Optional
from .base import StorageConfigError
from .http_uploader import HttpFileUploader
from .local_uploader import LocalFileUploader
from .minio_uploader import MinioFileUploader
from .upload_base import FileUploader
_file_uploader: Optional[FileUploader] = None
def create_file_uploader(storage_config: dict) -> FileUploader:
    provider = storage_config.get("provider", "minio")
    if not provider:
        provider = "minio"
    provider = str(provider).lower()
    if provider == "minio":
        return MinioFileUploader.from_storage_config(storage_config)
    if provider == "local":
        return LocalFileUploader.from_storage_config(storage_config)
    if provider == "http":
        return HttpFileUploader.from_storage_config(storage_config)
    raise StorageConfigError(f" storage.provider: {provider}")
def get_file_uploader() -> FileUploader:
    global _file_uploader
    if _file_uploader is None:
        from utils.config.db_config import get_storage_config
        storage_config = get_storage_config()
        _file_uploader = create_file_uploader(storage_config)
    return _file_uploader
def reset_file_uploader() -> None:
    global _file_uploader
    _file_uploader = None