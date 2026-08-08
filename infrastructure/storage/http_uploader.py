import mimetypes
from pathlib import Path
from typing import Any, Dict, Iterable
from urllib.parse import urlparse
import httpx
from loguru import logger
from .base import StorageAccessDeniedError, StorageConfigError
from .config import resolve_env
from .upload_base import UploadRequest, UploadResult, generate_unique_path
class HttpFileUploader:
    provider = "http"
    def __init__(
        self,
        upload_url: str = "",
        headers: Dict[str, str] | None = None,
        timeout: float = 120,
        allowed_hosts: Iterable[str] | None = None,
    ):
        self.upload_url = upload_url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout
        self.allowed_hosts = set(allowed_hosts or [])
    @classmethod
    def from_storage_config(cls, storage_config: Dict[str, Any]) -> "HttpFileUploader":
        http_config = storage_config.get("http", {})
        base_url = resolve_env(http_config.get("base_url", ""))
        upload_url = resolve_env(http_config.get("upload_url", "")) or base_url
        return cls(
            upload_url=upload_url,
            headers=resolve_env(http_config.get("headers", {})),
            timeout=float(http_config.get("timeout", 120)),
            allowed_hosts=resolve_env(http_config.get("allowed_hosts", [])),
        )
    def upload(self, request: UploadRequest) -> UploadResult:
        from .upload_base import StorageUploadError
        local_path = Path(request.local_path)
        if not local_path.exists() or not local_path.is_file():
            raise FileNotFoundError(f"待上传文件不存在: {request.local_path}")
        if not self.upload_url:
            raise StorageConfigError("HTTP  http.upload_url  http.base_url")
        parsed = urlparse(self.upload_url)
        if self.allowed_hosts and parsed.hostname not in self.allowed_hosts:
            raise StorageAccessDeniedError(f"URL host : {parsed.hostname}")
        bucket_name = request.target_bucket or ""
        if request.target_path:
            file_path = request.target_path
        else:
            ext = local_path.suffix or ".bin"
            file_path = generate_unique_path(request.category, ext)
        content_type = request.content_type
        if not content_type:
            guessed, _ = mimetypes.guess_type(str(local_path))
            content_type = guessed or "application/octet-stream"
        file_size = local_path.stat().st_size
        try:
            with open(local_path, "rb") as f:
                files = {"file": (local_path.name, f, content_type)}
                data = {"bucketName": bucket_name, "filePath": file_path}
                response = httpx.post(
                    self.upload_url,
                    files=files,
                    data=data,
                    headers=self.headers,
                    timeout=self.timeout,
                    follow_redirects=True,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise StorageUploadError(
                f"HTTP : {exc.response.status_code} "
                f"bucketName={bucket_name}, filePath={file_path}"
            ) from exc
        except Exception as exc:
            raise StorageUploadError(f"HTTP : {exc}") from exc
        logger.info(
            f"HTTP : {local_path} -> {self.upload_url}, "
            f"bucketName={bucket_name}, filePath={file_path}"
        )
        return UploadResult(
            provider=self.provider,
            bucket_name=bucket_name,
            file_path=file_path,
            content_type=content_type,
            size=file_size,
            source=f"http://{self.upload_url}",
        )