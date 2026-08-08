import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Protocol
from .base import StorageDownloadError
class StorageUploadError(StorageDownloadError):
    pass
@dataclass
class UploadRequest:
    local_path: str
    target_bucket: Optional[str] = None
    target_path: Optional[str] = None
    category: str = "uploads"
    content_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
@dataclass
class UploadResult:
    provider: str
    bucket_name: str
    file_path: str
    content_type: str
    size: int
    source: str
class FileUploader(Protocol):
    provider: str
    def upload(self, request: UploadRequest) -> UploadResult:
        ...
def generate_unique_path(category: str, extension: str) -> str:
    date_part = datetime.now().strftime("%Y-%m-%d")
    uuid_part = uuid.uuid4().hex[:8]
    ext = extension.lstrip(".")
    return f"{category}/{date_part}/{uuid_part}.{ext}"