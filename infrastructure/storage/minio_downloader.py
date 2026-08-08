from typing import Any, Dict
from minio.error import S3Error
from .base import (
    DownloadedFile,
    FileReference,
    StorageConfigError,
    StorageDownloadError,
    StorageFileNotFoundError,
)
from .config import resolve_env
from .minio_client import MinIOClient, MinIOConfig
class MinioFileDownloader:
    provider = "minio"
    def __init__(self, config: MinIOConfig):
        self.config = config
        self.client = MinIOClient(config)
    @classmethod
    def from_storage_config(cls, storage_config: Dict[str, Any]) -> "MinioFileDownloader":
        minio_config = storage_config.get("minio", {})
        def read(key: str, default: Any) -> Any:
            return resolve_env(minio_config.get(key, storage_config.get(key, default)))
        config = MinIOConfig(
            endpoint=read("endpoint", "localhost:9000"),
            access_key=read("access_key", ""),
            secret_key=read("secret_key", ""),
            secure=read("secure", False),
            region=read("region", "us-east-1"),
            default_bucket=read("default_bucket", "agent-files"),
            temp_dir=resolve_env(storage_config.get("temp_dir", minio_config.get("temp_dir", "./temp/downloads"))),
        )
        if not config.access_key or not config.secret_key:
            raise StorageConfigError("MinIO access_key/secret_key 未配置")
        if not config.endpoint:
            raise StorageConfigError("MinIO endpoint ")
        return cls(config)
    def download(self, file_ref: FileReference) -> DownloadedFile:
        bucket = file_ref.bucket or self.config.default_bucket
        object_name = file_ref.path.lstrip("/")
        if not object_name:
            raise StorageConfigError("MinIO object_name ")
        try:
            local_path = self.client.download_file(bucket, object_name)
        except FileNotFoundError as exc:
            raise StorageFileNotFoundError(str(exc)) from exc
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchBucket"}:
                raise StorageFileNotFoundError(str(exc)) from exc
            raise StorageDownloadError(str(exc)) from exc
        except Exception as exc:
            raise StorageDownloadError(str(exc)) from exc
        return DownloadedFile(
            path=local_path,
            source=f"minio://{bucket}/{object_name}",
            cleanup_required=True,
            metadata={"bucket": bucket, "object_name": object_name},
        )
    def cleanup(self, downloaded_file: DownloadedFile) -> bool:
        if not downloaded_file.cleanup_required:
            return False
        return self.client.cleanup_temp_file(downloaded_file.path)