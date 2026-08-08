import os
from pathlib import Path
from typing import Any, Dict, Iterable
from urllib.parse import urlparse
import httpx
from loguru import logger
from .base import (
    DownloadedFile,
    FileReference,
    StorageAccessDeniedError,
    StorageConfigError,
    StorageDownloadError,
    StorageFileNotFoundError,
)
from .config import resolve_env
class HttpFileDownloader:
    provider = "http"
    def __init__(
        self,
        base_url: str = "",
        headers: Dict[str, str] | None = None,
        timeout: float = 60,
        temp_dir: str = "./temp/downloads",
        allowed_hosts: Iterable[str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout
        self.temp_dir = Path(temp_dir).expanduser().resolve()
        self.allowed_hosts = set(allowed_hosts or [])
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    @classmethod
    def from_storage_config(cls, storage_config: Dict[str, Any]) -> "HttpFileDownloader":
        http_config = storage_config.get("http", {})
        return cls(
            base_url=resolve_env(http_config.get("base_url", "")),
            headers=resolve_env(http_config.get("headers", {})),
            timeout=float(http_config.get("timeout", 60)),
            temp_dir=resolve_env(http_config.get("temp_dir", storage_config.get("temp_dir", "./temp/downloads"))),
            allowed_hosts=resolve_env(http_config.get("allowed_hosts", [])),
        )
    def _build_post_body(self, file_ref: FileReference) -> Dict[str, str]:
        if not file_ref.file_id:
            raise StorageConfigError("HTTP  file_ref.file_id (filePath)")
        if not file_ref.bucket:
            raise StorageConfigError("HTTP  file_ref.bucket (bucketName)")
        return {
            "filePath": file_ref.file_id,
            "bucketName": file_ref.bucket,
        }
    def download(self, file_ref: FileReference) -> DownloadedFile:
        if not self.base_url:
            raise StorageConfigError("HTTP  http.base_url ")
        url = self.base_url
        parsed = urlparse(url)
        if self.allowed_hosts and parsed.hostname not in self.allowed_hosts:
            raise StorageAccessDeniedError(f"URL host : {parsed.hostname}")
        json_body = self._build_post_body(file_ref)
        filename = file_ref.filename or file_ref.file_id
        local_path = self.temp_dir / f"{os.urandom(8).hex()}_{Path(filename).name}"
        try:
            with httpx.stream(
                "POST", url,
                json=json_body,
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
            ) as response:
                if response.status_code == 404:
                    raise StorageFileNotFoundError(
                        f"HTTP : filePath={file_ref.file_id}, bucketName={file_ref.bucket}"
                    )
                response.raise_for_status()
                with open(local_path, "wb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
        except StorageDownloadError:
            if local_path.exists():
                local_path.unlink()
            raise
        except httpx.HTTPStatusError as exc:
            if local_path.exists():
                local_path.unlink()
            raise StorageDownloadError(
                f"HTTP : {exc.response.status_code} "
                f"filePath={file_ref.file_id}, bucketName={file_ref.bucket}"
            ) from exc
        except Exception as exc:
            if local_path.exists():
                local_path.unlink()
            raise StorageDownloadError(f"HTTP : {exc}") from exc
        logger.info(f"HTTP : {url} -> {local_path}, filePath={file_ref.file_id}")
        return DownloadedFile(
            path=str(local_path),
            source=url,
            cleanup_required=True,
            metadata={"url": url, "filePath": file_ref.file_id, "bucketName": file_ref.bucket},
        )
    def cleanup(self, downloaded_file: DownloadedFile) -> bool:
        if not downloaded_file.cleanup_required:
            return False
        file_path = Path(downloaded_file.path).resolve()
        try:
            file_path.relative_to(self.temp_dir)
        except ValueError:
            logger.warning(f"文件不在临时目录，拒绝清理: {downloaded_file.path}")
            return False
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
            return True
        return False