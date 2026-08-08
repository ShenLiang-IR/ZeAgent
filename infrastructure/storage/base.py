from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol
@dataclass
class FileReference:
    file_id: str
    path: str
    bucket: Optional[str] = None
    filename: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
@dataclass
class DownloadedFile:
    path: str
    source: str
    cleanup_required: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
class StorageDownloadError(Exception):
    pass
class StorageFileNotFoundError(StorageDownloadError):
    pass
class StorageConfigError(StorageDownloadError):
    pass
class StorageAccessDeniedError(StorageDownloadError):
    pass
class FileDownloader(Protocol):
    provider: str
    def download(self, file_ref: FileReference) -> DownloadedFile:
        ...
    def cleanup(self, downloaded_file: DownloadedFile) -> bool:
        ...