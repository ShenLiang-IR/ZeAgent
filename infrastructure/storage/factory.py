from typing import Optional
from .base import FileDownloader, StorageConfigError
from .http_downloader import HttpFileDownloader
from .local_downloader import LocalFileDownloader
from .minio_downloader import MinioFileDownloader
_file_downloader: Optional[FileDownloader] = None
def create_file_downloader(storage_config: dict) -> FileDownloader:
    provider = storage_config.get("provider", "minio")
    if not provider:
        provider = "minio"
    provider = str(provider).lower()
    if provider == "minio":
        return MinioFileDownloader.from_storage_config(storage_config)
    if provider == "local":
        return LocalFileDownloader.from_storage_config(storage_config)
    if provider == "http":
        return HttpFileDownloader.from_storage_config(storage_config)
    raise StorageConfigError(f" storage.provider: {provider}")
def get_file_downloader() -> FileDownloader:
    global _file_downloader
    if _file_downloader is None:
        from utils.config.db_config import get_storage_config
        storage_config = get_storage_config()
        _file_downloader = create_file_downloader(storage_config)
    return _file_downloader
def reset_file_downloader() -> None:
    global _file_downloader
    _file_downloader = None