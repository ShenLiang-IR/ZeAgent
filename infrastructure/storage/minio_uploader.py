import mimetypes
from pathlib import Path
from typing import Any, Dict
from .base import StorageConfigError
from .config import resolve_env
from .minio_client import MinIOClient, MinIOConfig
from .upload_base import UploadRequest, UploadResult, generate_unique_path
class MinioFileUploader:
    provider = "minio"
    def __init__(self, config: MinIOConfig):
        self.config = config
        self.client = MinIOClient(config)
    @classmethod
    def from_storage_config(cls, storage_config: Dict[str, Any]) -> "MinioFileUploader":
        minio_config = storage_config.get("minio", {})
        def read(key: str, default: Any) -> Any:
            return resolve_env(minio_config.get(key, storage_config.get(key, default)))
        config = MinIOConfig(
            endpoint=read("endpoint", "localhost:9000"),
            access_key=read("access_key", "minioadmin"),
            secret_key=read("secret_key", "minioadmin"),
            secure=read("secure", False),
            region=read("region", "us-east-1"),
            default_bucket=read("default_bucket", "agent-files"),
            temp_dir=resolve_env(
                storage_config.get("temp_dir", minio_config.get("temp_dir", "./temp/downloads"))
            ),
        )
        if not config.endpoint:
            raise StorageConfigError("MinIO endpoint ")
        return cls(config)
    def upload(self, request: UploadRequest) -> UploadResult:
        local_path = Path(request.local_path)
        if not local_path.exists() or not local_path.is_file():
            raise FileNotFoundError(f"待上传文件不存在: {request.local_path}")
        bucket = request.target_bucket or self.config.default_bucket
        if request.target_path:
            object_name = request.target_path
        else:
            ext = local_path.suffix or ".bin"
            object_name = generate_unique_path(request.category, ext)
        content_type = request.content_type
        if not content_type:
            guessed, _ = mimetypes.guess_type(str(local_path))
            content_type = guessed or "application/octet-stream"
        try:
            result = self.client.upload_file(
                bucket, object_name, str(local_path), content_type=content_type
            )
        except FileNotFoundError:
            raise
        except Exception as exc:
            from .upload_base import StorageUploadError
            raise StorageUploadError(f"MinIO : {exc}") from exc
        return UploadResult(
            provider=self.provider,
            bucket_name=bucket,
            file_path=object_name,
            content_type=content_type,
            size=result["size"],
            source=f"minio://{bucket}/{object_name}",
        )