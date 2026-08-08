from __future__ import annotations
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set
from .sandbox import Sandbox
@dataclass(frozen=True)
class PathMapping:
    container_path: str
    local_path: str
    read_only: bool = False
class LocalSandbox(Sandbox):
    def __init__(self, sandbox_id: str, path_mappings: List[PathMapping]):
        self._id = sandbox_id
        self._path_mappings = sorted(
            path_mappings,
            key=lambda m: len(m.container_path),
            reverse=True,
        )
        self._agent_written_paths: Set[str] = set()
    @property
    def id(self) -> str:
        return self._id
    @property
    def path_mappings(self) -> List[PathMapping]:
        return list(self._path_mappings)
    def find_path_mapping(self, container_path: str) -> Optional[PathMapping]:
        for mapping in self._path_mappings:
            if container_path.startswith(mapping.container_path):
                return mapping
        return None
    def resolve_path(self, container_path: str) -> str:
        mapping = self.find_path_mapping(container_path)
        if mapping is None:
            raise ValueError(
                f"路径未映射: {container_path}"
            )
        relative = container_path[len(mapping.container_path):]
        resolved = str(Path(mapping.local_path) / relative.lstrip("/"))
        return str(Path(resolved).resolve())
    def resolve_path_with_mapping(self, container_path: str):
        mapping = self.find_path_mapping(container_path)
        if mapping is None:
            raise ValueError(
                f"路径未映射: {container_path}"
            )
        relative = container_path[len(mapping.container_path):]
        resolved = str(Path(mapping.local_path) / relative.lstrip("/"))
        return str(Path(resolved).resolve()), mapping
    def reverse_resolve_path(self, local_path: str) -> str:
        resolved = str(Path(local_path).resolve()).replace("\\", "/")
        for mapping in self._path_mappings:
            prefix = str(Path(mapping.local_path).resolve()).replace("\\", "/")
            if resolved.startswith(prefix):
                relative = resolved[len(prefix):]
                return mapping.container_path.rstrip("/") + "/" + relative.lstrip("/")
        return local_path
    def resolve_paths_in_content(self, content: str) -> str:
        result = content
        for mapping in self._path_mappings:
            host_path = str(Path(mapping.local_path).resolve()).replace("\\", "/")
            result = result.replace(mapping.container_path, host_path)
        return result
    def reverse_resolve_paths_in_output(self, output: str) -> str:
        result = output
        for mapping in self._path_mappings:
            host_path = str(Path(mapping.local_path).resolve())
            host_posix = host_path.replace("\\", "/")
            host_native = host_path
            result = result.replace(host_posix, mapping.container_path)
            result = result.replace(host_native, mapping.container_path)
        return result
    @staticmethod
    def reject_path_traversal(path: str) -> None:
        if ".." in Path(path).parts:
            raise ValueError(f"路径遍历被拒: {path}")
    def _resolve_to_workspace(self, path: str):
        """解析沙箱路径。不以 /mnt/ 开头的相对路径自动映射到 /mnt/workspace/ 下。"""
        if not path.startswith("/mnt/"):
            path = f"/mnt/workspace/{path}"
        return self.resolve_path_with_mapping(path)
    def _find_workspace_path(self) -> Optional[str]:
        for mapping in self._path_mappings:
            if mapping.container_path == "/mnt/workspace" and not mapping.read_only:
                return str(Path(mapping.local_path).resolve())
        return None
    def execute_command(self, command: str) -> str:
        resolved_command = self.resolve_paths_in_content(command)
        workspace_path = self._find_workspace_path()
        if workspace_path:
            Path(workspace_path).mkdir(parents=True, exist_ok=True)
        system = platform.system()
        if system == "Windows":
            shell_args = ["cmd", "/c", resolved_command]
            preexec_fn = None  # Windows 不支持 RLIMIT
        else:
            shell_path = "/bin/bash" if Path("/bin/bash").exists() else "/bin/sh"
            shell_args = [shell_path, "-c", resolved_command]
            preexec_fn = self._set_rlimits  # Linux/Unix 资源限制
        try:
            from utils.config import get_config
            timeout = int(get_config("sandbox.bash_timeout", 60))
            result = subprocess.run(
                shell_args,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=workspace_path,
                preexec_fn=preexec_fn,
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"
            if result.returncode != 0:
                output += f"\nExit code: {result.returncode}"
            output = self.reverse_resolve_paths_in_output(output)
            output = self._redact_secrets(output)
            return output
        except subprocess.TimeoutExpired:
            return f"命令执行超时({timeout}s)，已终止"
        except Exception as e:
            return f"命令执行失败: {e}"

    @staticmethod
    def _set_rlimits() -> None:
        """子进程资源限制（Linux/Unix，preexec_fn 回调）。

        限制 CPU/内存/文件大小，防 fork bomb / OOM / 磁盘耗尽。
        完整容器级隔离（nsjail/cgroup）需运维部署，见 docs。
        """
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
            mem = 512 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
            fsize = 100 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        except Exception:
            pass

    @staticmethod
    def _redact_secrets(output: str) -> str:
        """脱敏输出中的 password/token/secret/api_key 等敏感值。"""
        import re
        return re.sub(
            r'(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+',
            r'\1=***',
            output,
            flags=re.IGNORECASE,
        )
    def read_file(self, path: str) -> str:
        self.reject_path_traversal(path)
        host_path, _ = self._resolve_to_workspace(path)
        try:
            content = Path(host_path).read_text(encoding="utf-8")
            if host_path in self._agent_written_paths:
                return self.reverse_resolve_paths_in_output(content)
            return content
        except FileNotFoundError:
            raise FileNotFoundError(f"文件不存在: {path}")
        except UnicodeDecodeError:
            raise ValueError(f"文件编码错误(非UTF-8): {path}")
    def write_file(self, path: str, content: str, append: bool = False) -> None:
        self.reject_path_traversal(path)
        host_path, mapping = self._resolve_to_workspace(path)
        if mapping.read_only:
            raise PermissionError(f"映射只读，禁止写入: {path}")
        resolved_content = self.resolve_paths_in_content(content)
        Path(host_path).parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(host_path, mode, encoding="utf-8") as f:
            f.write(resolved_content)
        self._agent_written_paths.add(host_path)
    def list_dir(self, path: str, max_depth: int = 2) -> List[str]:
        self.reject_path_traversal(path)
        host_path, _ = self._resolve_to_workspace(path)
        root = Path(host_path)
        if not root.is_dir():
            raise FileNotFoundError(f"目录不存在: {path}")
        entries: List[str] = []
        self._walk_dir(root, root, entries, max_depth, 0)
        return entries
    def _walk_dir(
        self,
        root: Path,
        current: Path,
        entries: List[str],
        max_depth: int,
        depth: int,
    ) -> None:
        if depth > max_depth:
            return
        try:
            items = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except PermissionError:
            return
        for item in items:
            if item.name.startswith("."):
                continue
            relative = item.relative_to(root)
            virtual = self.reverse_resolve_path(str(item))
            if item.is_dir():
                entries.append(f"{virtual}/")
                self._walk_dir(root, item, entries, max_depth, depth + 1)
            else:
                entries.append(virtual)
    def update_file(self, path: str, content: bytes) -> None:
        self.reject_path_traversal(path)
        host_path, mapping = self._resolve_to_workspace(path)
        if mapping.read_only:
            raise PermissionError(f"映射只读，禁止写入: {path}")
        Path(host_path).parent.mkdir(parents=True, exist_ok=True)
        Path(host_path).write_bytes(content)
        self._agent_written_paths.add(host_path)