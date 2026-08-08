from __future__ import annotations
from pathlib import Path
def reject_path_traversal(path: str) -> None:
    parts = Path(path).parts
    if ".." in parts:
        raise ValueError(f"路径遍历被拒: {path}")
def validate_virtual_path(path: str) -> str:
    path = path.strip().replace("\\", "/")
    if not path.startswith("/mnt/"):
        raise ValueError(
            f"路径必须以 /mnt/ 开头: {path}"
        )
    reject_path_traversal(path)
    return path
def truncate_output(output: str, max_chars: int = 20000) -> str:
    if len(output) <= max_chars:
        return output
    head_size = int(max_chars * 0.7)
    tail_size = max_chars - head_size - 50
    return (
        output[:head_size]
        + f"\n\n... [ {len(output)} ] ...\n\n"
        + output[-tail_size:]
    )
def mask_host_paths(output: str, host_paths: dict[str, str]) -> str:
    result = output
    for host_path, virtual_path in host_paths.items():
        host_posix = host_path.replace("\\", "/")
        result = result.replace(host_posix, virtual_path)
        result = result.replace(host_path, virtual_path)
    return result