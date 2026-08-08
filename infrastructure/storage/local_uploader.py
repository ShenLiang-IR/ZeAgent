import mimetypes
import shutil
from pathlib import Path
from typing import Any, Dict
from loguru import logger
from .base import StorageAccessDeniedError, StorageConfigError
from .config import resolve_env
from .upload_base import UploadRequest, UploadResult, generate_unique_path
class LocalFileUploader:
    provider = "local"
    def __init__(self, base_dir: str):
        if not base_dir:
            raise StorageConfigError("local.base_dir ")
        self.base_dir = Path(base_dir).expanduser().resolve()
    @classmethod
    def from_storage_config(cls, storage_config: Dict[str, Any]) -> "LocalFileUploader":
        local_config = storage_config.get("local", {})
        base_dir = resolve_env(local_config.get("base_dir", ""))
        return cls(base_dir=base_dir)
    def _resolve_target_path(self, target_path: str) -> Path:
        raw_path = Path(target_path)
        if raw_path.is_absolute():
            raise StorageAccessDeniedError("local uploader ")
        resolved = (self.base_dir / raw_path).resolve()
        try:
            resolved.relative_to(self.base_dir)
        except ValueError as exc:
            raise StorageAccessDeniedError(f"存储访问被拒: {target_path}") from exc
        return resolved
    def upload(self, request: UploadRequest) -> UploadResult:
        local_path = Path(request.local_path)
        if not local_path.exists() or not local_path.is_file():
            raise FileNotFoundError(f"待上传文件不存在: {request.local_path}")
        if request.target_path:
            object_name = request.target_path
        else:
            ext = local_path.suffix or ".bin"
            object_name = generate_unique_path(request.category, ext)
        target = self._resolve_target_path(object_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        content_type = request.content_type
        if not content_type:
            guessed, _ = mimetypes.guess_type(str(local_path))
            content_type = guessed or "application/octet-stream"
        try:
            shutil.copy2(str(local_path), str(target))
        except Exception as exc:
            from .upload_base import StorageUploadError
            raise StorageUploadError(f"本地上传失败: {exc}") from exc
        file_size = target.stat().st_size
        logger.info(f"本地上传完成: {local_path} -> {target}")
        return UploadResult(
            provider=self.provider,
            bucket_name="",
            file_path=object_name,
            content_type=content_type,
            size=file_size,
            source=f"local://{target}",
        )