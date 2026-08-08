from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
import os
from loguru import logger
from minio import Minio
from minio.error import S3Error
from urllib3 import PoolManager, Timeout
from urllib3.util.retry import Retry
from infrastructure.storage.config import resolve_env
@dataclass
class MinIOConfig:
    endpoint: str
    access_key: str
    secret_key: str
    secure: bool = False
    region: str = "us-east-1"
    default_bucket: str = "agent-files"
    temp_dir: str = "./temp/downloads"
class MinIOClient:
    def __init__(self, config: MinIOConfig):
        self.config = config
        self._client = Minio(
            config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=config.secure,
            region=config.region,
            http_client=PoolManager(
                timeout=Timeout(connect=10, read=30),
                retries=Retry(total=1, backoff_factor=0.1),
            ),
        )
        self._temp_dir = Path(config.temp_dir)
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        scheme = "https" if config.secure else "http"
        logger.info(f"MinIOClient : endpoint={config.endpoint}, base_url={scheme}://{config.endpoint}, bucket={config.default_bucket}")
    @staticmethod
    def parse_minio_path(path: str) -> Tuple[str, str]:
        if not path:
            raise ValueError("MinIO ")
        parts = path.strip("/").split("/", 1)
        if len(parts) < 2:
            raise ValueError(f"MinIO  'bucket/path/to/file': {path}")
        bucket = parts[0]
        object_name = parts[1]
        return bucket, object_name
    def get_file_info(self, bucket: str, object_name: str) -> Optional[dict]:
        try:
            stat = self._client.stat_object(bucket, object_name)
            return {
                "size": stat.size,
                "content_type": stat.content_type,
                "last_modified": stat.last_modified,
                "etag": stat.etag,
                "metadata": stat.metadata,
            }
        except S3Error as e:
            if e.code == "NoSuchKey":
                return None
            raise
    def download_file(self, bucket: str, object_name: str) -> str:
        file_info = self.get_file_info(bucket, object_name)
        if file_info is None:
            raise FileNotFoundError(f" MinIO: {bucket}/{object_name}")
        filename = os.path.basename(object_name)
        local_path = self._temp_dir / f"{os.urandom(8).hex()}_{filename}"
        try:
            scheme = "https" if self.config.secure else "http"
            logger.debug(f"MinIO : {scheme}://{self.config.endpoint}/{bucket}/{object_name}")
            self._client.fget_object(bucket, object_name, str(local_path))
            logger.info(f"MinIO 下载完成: {bucket}/{object_name} -> {local_path}")
            return str(local_path)
        except Exception as e:
            if local_path.exists():
                local_path.unlink()
            raise
    def cleanup_temp_file(self, path: str) -> bool:
        try:
            file_path = Path(path)
            if file_path.exists() and file_path.is_file():
                if str(file_path.parent) == str(self._temp_dir):
                    file_path.unlink()
                    logger.debug(f"已清理临时文件: {path}")
                    return True
                else:
                    logger.warning(f"文件不在临时目录，跳过清理: {path}")
            return False
        except Exception as e:
            logger.warning(f"清理临时文件失败: {path}, 错误: {e}")
            return False
    def upload_file(
        self,
        bucket: str,
        object_name: str,
        local_path: str,
        content_type: str = "application/octet-stream",
    ) -> dict:
        scheme = "https" if self.config.secure else "http"
        logger.debug(
            f"MinIO : {local_path} -> {scheme}://{self.config.endpoint}/{bucket}/{object_name}"
        )
        self._client.fput_object(
            bucket,
            object_name,
            local_path,
            content_type=content_type,
        )
        file_size = os.path.getsize(local_path)
        logger.info(
            f": {local_path} -> {bucket}/{object_name} ({file_size} bytes)"
        )
        return {
            "bucket": bucket,
            "object_name": object_name,
            "size": file_size,
        }
    def bucket_exists(self, bucket: str) -> bool:
        try:
            return self._client.bucket_exists(bucket)
        except S3Error:
            return False
_minio_client: Optional[MinIOClient] = None
def get_minio_client() -> MinIOClient:
    global _minio_client
    if _minio_client is None:
        from utils.config.db_config import get_storage_config
        storage_config = get_storage_config()
        if storage_config.get("provider") != "minio":
            raise ValueError(" MinIO")
        minio_config = MinIOConfig(
            endpoint=resolve_env(storage_config.get("endpoint", "localhost:9000")),
            access_key=resolve_env(storage_config.get("access_key", "")),
            secret_key=resolve_env(storage_config.get("secret_key", "")),
            secure=storage_config.get("secure", False),
            region=storage_config.get("region", "us-east-1"),
            default_bucket=storage_config.get("default_bucket", "agent-files"),
            temp_dir=storage_config.get("temp_dir", "./temp/downloads"),
        )
        if not minio_config.access_key or not minio_config.secret_key:
            raise ValueError("MinIO access_key/secret_key 未配置，请在 DB 或环境变量中设置")
        _minio_client = MinIOClient(minio_config)
    return _minio_client