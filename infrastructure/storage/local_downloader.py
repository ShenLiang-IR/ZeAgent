import os
import shutil
from pathlib import Path
from typing import Any, Dict
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
class LocalFileDownloader:
    provider = "local"
    def __init__(self, base_dir: str, temp_dir: str, copy_to_temp: bool = True):
        if not base_dir:
            raise StorageConfigError("local.base_dir ")
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.temp_dir = Path(temp_dir).expanduser().resolve()
        self.copy_to_temp = copy_to_temp
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    @classmethod
    def from_storage_config(cls, storage_config: Dict[str, Any]) -> "LocalFileDownloader":
        local_config = storage_config.get("local", {})
        return cls(
            base_dir=resolve_env(local_config.get("base_dir", "")),
            temp_dir=resolve_env(local_config.get("temp_dir", storage_config.get("temp_dir", "./temp/downloads"))),
            copy_to_temp=bool(local_config.get("copy_to_temp", True)),
        )
    def _resolve_source_path(self, path: str) -> Path:
        if not path:
            raise StorageConfigError("local file path ")
        raw_path = Path(path)
        if raw_path.is_absolute():
            raise StorageAccessDeniedError("local provider ")
        source_path = (self.base_dir / raw_path).resolve()
        try:
            source_path.relative_to(self.base_dir)
        except ValueError as exc:
            raise StorageAccessDeniedError(f"存储访问被拒: {path}") from exc
        return source_path
    def download(self, file_ref: FileReference) -> DownloadedFile:
        source_path = self._resolve_source_path(file_ref.path)
        if not source_path.exists() or not source_path.is_file():
            raise StorageFileNotFoundError(f"源文件不存在: {source_path}")
        if not self.copy_to_temp:
            return DownloadedFile(
                path=str(source_path),
                source=f"local://{source_path}",
                cleanup_required=False,
                metadata={"source_path": str(source_path)},
            )
        filename = file_ref.filename or source_path.name
        if not Path(filename).suffix:
            filename = source_path.name
        local_path = self.temp_dir / f"{os.urandom(8).hex()}_{Path(filename).name}"
        try:
            shutil.copy2(source_path, local_path)
        except Exception as exc:
            if local_path.exists():
                local_path.unlink()
            raise StorageDownloadError(f"本地下载失败: {exc}") from exc
        logger.info(f"本地下载完成: {source_path} -> {local_path}")
        return DownloadedFile(
            path=str(local_path),
            source=f"local://{source_path}",
            cleanup_required=True,
            metadata={"source_path": str(source_path)},
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