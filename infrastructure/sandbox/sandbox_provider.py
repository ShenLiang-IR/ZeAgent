from __future__ import annotations
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional
from loguru import logger
from .local_sandbox import LocalSandbox, PathMapping
DEFAULT_MAX_CACHED_SANDBOXES = 256
DEFAULT_BASE_DIR = "./data/sandbox"
class LocalSandboxProvider:
    def __init__(
        self,
        base_dir: str = DEFAULT_BASE_DIR,
        max_cached: int = DEFAULT_MAX_CACHED_SANDBOXES,
        skills_dir: Optional[str] = None,
    ):
        self._base_dir = Path(base_dir).resolve()
        self._max_cached = max_cached
        self._skills_dir = skills_dir
        self._lock = threading.Lock()
        self._generic_sandbox: Optional[LocalSandbox] = None
        self._session_sandboxes: OrderedDict[str, LocalSandbox] = OrderedDict()
    def acquire(self, session_id: Optional[str] = None) -> LocalSandbox:
        if session_id is None:
            return self._get_or_create_generic()
        with self._lock:
            if session_id in self._session_sandboxes:
                self._session_sandboxes.move_to_end(session_id)
                return self._session_sandboxes[session_id]
        sandbox = self._create_session_sandbox(session_id)
        with self._lock:
            if session_id in self._session_sandboxes:
                self._session_sandboxes.move_to_end(session_id)
                return self._session_sandboxes[session_id]
            self._session_sandboxes[session_id] = sandbox
            while len(self._session_sandboxes) > self._max_cached:
                evicted_key, _ = self._session_sandboxes.popitem(last=False)
                logger.debug(
                    f"[SandboxProvider] LRU : {evicted_key}"
                )
        return sandbox
    def get(self, sandbox_id: str) -> Optional[LocalSandbox]:
        with self._lock:
            if sandbox_id == "local":
                return self._generic_sandbox
            if sandbox_id.startswith("local:"):
                session_id = sandbox_id[len("local:"):]
                if session_id in self._session_sandboxes:
                    self._session_sandboxes.move_to_end(session_id)
                    return self._session_sandboxes[session_id]
        return None
    def release(self, sandbox_id: str) -> None:
        pass
    def reset(self) -> None:
        with self._lock:
            self._session_sandboxes.clear()
            self._generic_sandbox = None
    def _get_or_create_generic(self) -> LocalSandbox:
        with self._lock:
            if self._generic_sandbox is not None:
                return self._generic_sandbox
        sandbox = self._build_sandbox("local", session_id=None)
        with self._lock:
            if self._generic_sandbox is None:
                self._generic_sandbox = sandbox
            return self._generic_sandbox
    def _create_session_sandbox(self, session_id: str) -> LocalSandbox:
        sandbox_id = f"local:{session_id}"
        return self._build_sandbox(sandbox_id, session_id=session_id)
    def _build_sandbox(
        self,
        sandbox_id: str,
        session_id: Optional[str] = None,
    ) -> LocalSandbox:
        mappings: list[PathMapping] = []
        if session_id:
            session_dir = self._base_dir / session_id
            workspace_dir = session_dir / "workspace"
            outputs_dir = session_dir / "outputs"
            uploads_dir = session_dir / "uploads"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            outputs_dir.mkdir(parents=True, exist_ok=True)
            uploads_dir.mkdir(parents=True, exist_ok=True)
            mappings.extend([
                PathMapping("/mnt/workspace", str(workspace_dir), read_only=False),
                PathMapping("/mnt/outputs", str(outputs_dir), read_only=False),
                PathMapping("/mnt/uploads", str(uploads_dir), read_only=True),
            ])
        else:
            workspace_dir = self._base_dir / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            mappings.append(
                PathMapping("/mnt/workspace", str(workspace_dir), read_only=False)
            )
        if self._skills_dir:
            skills_path = Path(self._skills_dir)
            if skills_path.is_dir():
                mappings.append(
                    PathMapping("/mnt/skills/public", str(skills_path), read_only=True)
                )
        logger.info(
            f"[SandboxProvider] : id={sandbox_id}, "
            f"mappings={len(mappings)}"
        )
        return LocalSandbox(sandbox_id, mappings)
_provider: Optional[LocalSandboxProvider] = None
_provider_lock = threading.Lock()
def get_sandbox_provider() -> LocalSandboxProvider:
    global _provider
    with _provider_lock:
        if _provider is None:
            _init_provider()
        return _provider
def _init_provider() -> None:
    global _provider
    try:
        from utils.config import get_config
        enabled = get_config("sandbox.enabled", False)
        if not enabled:
            logger.info("[SandboxProvider] sandbox.enabled=false，不初始化沙箱")
            return
        base_dir = get_config("sandbox.base_dir", DEFAULT_BASE_DIR)
        skills_dir = get_config("agent.skills_dir", None)
        _provider = LocalSandboxProvider(
            base_dir=base_dir,
            skills_dir=skills_dir,
        )
        logger.info(f"[SandboxProvider] : base_dir={base_dir}")
    except Exception as e:
        logger.warning(f"[SandboxProvider] : {e}")
        _provider = None
def is_sandbox_enabled() -> bool:
    try:
        from utils.config import get_config
        return get_config("sandbox.enabled", False)
    except Exception:
        return False


def reset_sandbox_provider() -> None:
    """重置 sandbox provider 单例（热重载时调用）。

    清空 _provider 后下次 get_sandbox_provider() 会按最新 config 重建。
    """
    global _provider
    _provider = None
    logger.debug("[SandboxProvider] 单例已重置，下次调用将重建")