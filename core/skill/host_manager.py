"""Skill Host Manager + 多语言隔离运行时（Python venv / Node.js / Go）。

核心设计：
- SkillHostManager：管理 skill 的独立运行时环境
  - Python: create_venv → pip install 到独立 venv
  - Node.js: create_node_env → npm install 到独立 node_modules
  - Go: create_go_binary → go build 编译为静态二进制

- 三种 Runtime（统一 JSON-over-stdio 协议）：
  - PythonSkillRuntime: 独立 venv 中执行 Python 模块
  - NodeJsSkillRuntime: 独立 node_modules 中执行 JS 模块
  - GoSkillRuntime: 执行编译后的 Go 二进制

目录结构：
  skill_registry/
  ├── venvs/            # Python venv
  │   └── {skill_id}/
  ├── node_envs/        # Node.js 环境
  │   └── {skill_id}/
  │       ├── node_modules/
  │       └── index.js
  ├── go_binaries/      # Go 编译产物
  │   └── {skill_id}.exe
  └── runtimes/
      ├── skill_runner.py   # Python runner
      └── skill_runner.js   # Node.js runner
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger


# ── 路径 ──
_AGENT_DIR = Path(__file__).resolve().parent.parent.parent
_VENVS_DIR = _AGENT_DIR / "skill_registry" / "venvs"
_NODE_ENVS_DIR = _AGENT_DIR / "skill_registry" / "node_envs"
_GO_BINARIES_DIR = _AGENT_DIR / "skill_registry" / "go_binaries"
_PYTHON_RUNNER = _AGENT_DIR / "skill_registry" / "runtimes" / "skill_runner.py"
_NODE_RUNNER = _AGENT_DIR / "skill_registry" / "runtimes" / "skill_runner.js"

# 共享基础 Python（用于创建 venv 和清理）
_BASE_PYTHON = sys.executable


# A1: skill_id 白名单校验（防路径逃逸 ../ + 防引号/分隔符拼路径/注子进程）
_SKILL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")


def _validate_skill_id(skill_id: str) -> str:
    """校验 skill_id 合法性，非法抛 ValueError。

    skill_id 仅允许 [A-Za-z0-9_.-]，首字符须字母数字，长度 ≤128。
    拒绝路径分隔符（../）与引号，防拼接路径逃逸或子进程命令注入。
    来源：插件市场 manifest / DB（半可信），用于拼路径前必须清洗。
    """
    if not isinstance(skill_id, str) or not _SKILL_ID_RE.match(skill_id):
        raise ValueError(f"非法 skill_id（仅允许字母数字及 _ . -）: {skill_id!r}")
    return skill_id


class SkillHostManager:
    """Skill 运行时环境管理器（多语言生命周期）。"""

    _instance: Optional["SkillHostManager"] = None

    def __init__(self):
        _VENVS_DIR.mkdir(parents=True, exist_ok=True)
        _NODE_ENVS_DIR.mkdir(parents=True, exist_ok=True)
        _GO_BINARIES_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_instance(cls) -> "SkillHostManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    # ── Python venv ──

    def _venv_path(self, skill_id: str) -> Path:
        return _VENVS_DIR / _validate_skill_id(skill_id)

    def _venv_python(self, skill_id: str) -> str:
        venv = self._venv_path(skill_id)
        if os.name == "nt":
            return str(venv / "Scripts" / "python.exe")
        return str(venv / "bin" / "python")

    def has_venv(self, skill_id: str) -> bool:
        return self._venv_path(skill_id).exists()

    async def create_venv(
        self,
        skill_id: str,
        requirements: Optional[List[str]] = None,
    ) -> str:
        """创建独立 venv 并安装依赖。返回 venv python 路径。"""
        venv_path = self._venv_path(skill_id)
        venv_python = self._venv_python(skill_id)

        if venv_path.exists():
            logger.info(f"[SkillHost] venv 已存在，跳过创建: {skill_id}")
            return venv_python

        logger.info(f"[SkillHost] 创建 venv: {skill_id} ({venv_path})")

        proc = await asyncio.create_subprocess_exec(
            _BASE_PYTHON, "-m", "venv", str(venv_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"venv 创建失败 ({skill_id}): {err}")

        if requirements:
            logger.info(f"[SkillHost] 安装依赖 ({skill_id}): {requirements}")
            pip_args = [venv_python, "-m", "pip", "install", "--no-input", "--quiet"] + requirements
            proc = await asyncio.create_subprocess_exec(
                *pip_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="ignore")
                logger.warning(f"[SkillHost] pip install 部分失败 ({skill_id}): {err[:500]}")

        logger.info(f"[SkillHost] venv 创建完成: {skill_id}")
        return venv_python

    async def remove_venv(self, skill_id: str) -> bool:
        """删除 venv 目录。"""
        return await self._remove_dir(self._venv_path(skill_id), "venv", skill_id)

    # ── Node.js 环境 ──

    def _node_env_path(self, skill_id: str) -> Path:
        return _NODE_ENVS_DIR / _validate_skill_id(skill_id)

    def has_node_env(self, skill_id: str) -> bool:
        return self._node_env_path(skill_id).exists()

    async def create_node_env(
        self,
        skill_id: str,
        dependencies: Optional[Dict[str, str]] = None,
        entry_script: Optional[str] = None,
    ) -> str:
        """创建 Node.js 环境（独立 node_modules）。返回 node 可执行路径。

        dependencies: {"package_name": "version"} → 写入 package.json + npm install
        entry_script: skill 入口 JS 文件内容（写入 index.js）
        """
        env_path = self._node_env_path(skill_id)
        if env_path.exists():
            logger.info(f"[SkillHost] node env 已存在，跳过创建: {skill_id}")
            return self._node_executable(skill_id)

        logger.info(f"[SkillHost] 创建 node env: {skill_id} ({env_path})")
        env_path.mkdir(parents=True, exist_ok=True)

        # 写 package.json
        pkg = {
            "name": skill_id,
            "version": "1.0.0",
            "type": "module",
            "dependencies": dependencies or {},
        }
        (env_path / "package.json").write_text(
            json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 写入口脚本（如果提供）
        if entry_script:
            (env_path / "index.js").write_text(entry_script, encoding="utf-8")

        # npm install
        if dependencies:
            node_exe = self._find_node()
            if not node_exe:
                raise RuntimeError("未找到 node 可执行文件（请确保 Node.js 已安装）")
            npm_cmd = shutil.which("npm") or shutil.which("npm.cmd") or f"{node_exe} {env_path / 'node_modules' / 'npm' / 'bin' / 'npm-cli.js'}"
            proc = await asyncio.create_subprocess_exec(
                node_exe, shutil.which("npm") or "npm", "install", "--prefix", str(env_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(env_path),
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="ignore")
                logger.warning(f"[SkillHost] npm install 部分失败 ({skill_id}): {err[:500]}")

        logger.info(f"[SkillHost] node env 创建完成: {skill_id}")
        return self._node_executable(skill_id)

    def _node_executable(self, skill_id: str) -> str:
        """返回 node 可执行路径。"""
        return self._find_node() or "node"

    @staticmethod
    def _find_node() -> Optional[str]:
        """查找系统 node。"""
        for name in ("node", "node.exe"):
            path = shutil.which(name)
            if path:
                return path
        return None

    async def remove_node_env(self, skill_id: str) -> bool:
        """删除 node 环境。"""
        return await self._remove_dir(self._node_env_path(skill_id), "node env", skill_id)

    # ── Go 二进制 ──

    def _go_binary_path(self, skill_id: str) -> Path:
        suffix = ".exe" if os.name == "nt" else ""
        return _GO_BINARIES_DIR / f"{_validate_skill_id(skill_id)}{suffix}"

    def has_go_binary(self, skill_id: str) -> bool:
        return self._go_binary_path(skill_id).exists()

    async def create_go_binary(
        self,
        skill_id: str,
        source_path: str,
    ) -> str:
        """编译 Go 源码为静态二进制。返回二进制路径。

        source_path: Go 源文件路径（.go 文件或含 main 包的目录）
        """
        binary_path = self._go_binary_path(skill_id)
        if binary_path.exists():
            logger.info(f"[SkillHost] go binary 已存在，跳过: {skill_id}")
            return str(binary_path)

        go_exe = shutil.which("go") or shutil.which("go.exe")
        if not go_exe:
            raise RuntimeError("未找到 go 可执行文件（请确保 Go 已安装）")

        logger.info(f"[SkillHost] 编译 go binary: {skill_id} ({source_path})")
        _GO_BINARIES_DIR.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            go_exe, "build", "-o", str(binary_path), source_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"go build 失败 ({skill_id}): {err}")

        logger.info(f"[SkillHost] go binary 编译完成: {skill_id}")
        return str(binary_path)

    async def remove_go_binary(self, skill_id: str) -> bool:
        """删除 Go 二进制。"""
        binary_path = self._go_binary_path(skill_id)
        if not binary_path.exists():
            return False
        binary_path.unlink()
        logger.info(f"[SkillHost] go binary 已删除: {skill_id}")
        return True

    # ── 通用 ──

    async def _remove_dir(self, path: Path, label: str, skill_id: str) -> bool:
        """通用目录删除（直接 shutil.rmtree，Windows 兼容，无子进程/无代码注入）。"""
        if not path.exists():
            return False
        try:
            await asyncio.to_thread(shutil.rmtree, str(path), True)
            logger.info(f"[SkillHost] {label} 已删除: {skill_id}")
            return True
        except Exception as e:
            logger.warning(f"[SkillHost] 删除 {label} 失败 ({skill_id}): {e}")
            return False

    def list_venvs(self) -> List[str]:
        if not _VENVS_DIR.exists():
            return []
        return [d.name for d in _VENVS_DIR.iterdir() if d.is_dir()]

    def list_node_envs(self) -> List[str]:
        if not _NODE_ENVS_DIR.exists():
            return []
        return [d.name for d in _NODE_ENVS_DIR.iterdir() if d.is_dir()]

    def list_go_binaries(self) -> List[str]:
        if not _GO_BINARIES_DIR.exists():
            return []
        return [f.stem for f in _GO_BINARIES_DIR.iterdir() if f.is_file()]


# ── 公共执行辅助（沙箱策略） ──

def _build_skill_policy(
    skill_id: str,
    plugin_type: str,
    cwd: Optional[str] = None,
    timeout: float = 60.0,
) -> "SandboxPolicy":
    """为 skill 执行构建沙箱策略。"""
    from infrastructure.sandbox.policy import SandboxPolicy
    return SandboxPolicy(
        cwd=cwd,
        skill_id=skill_id,
        plugin_type=plugin_type,
        caller="system",
        memory_limit_mb=512,
        cpu_limit_seconds=int(timeout * 2),  # CPU 限制为超时的 2 倍
    )


async def _run_subprocess_json(
    command: List[str],
    request: Dict[str, Any],
    skill_id: str,
    timeout: float = 60.0,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
    plugin_type: str = "skill_python",
) -> Any:
    """通用 JSON-over-stdio 子进程执行（Python/Node 共用），应用沙箱策略。"""
    from infrastructure.sandbox.policy import run_sandboxed_subprocess

    policy = _build_skill_policy(skill_id, plugin_type, cwd=cwd, timeout=timeout)
    if env:
        policy.env_inject.update(env)

    result_line = await run_sandboxed_subprocess(
        command=command,
        stdin_data=json.dumps(request),
        policy=policy,
        timeout=timeout,
    )
    resp = json.loads(result_line)
    if not resp.get("success"):
        raise RuntimeError(f"skill 执行失败 ({skill_id}): {resp.get('error', 'unknown')}")
    return resp.get("result")


class PythonSkillRuntime:
    """在独立 venv 中执行 Python skill 模块（沙箱隔离）。"""

    async def execute(
        self,
        skill_id: str,
        module_path: str,
        function_name: str,
        arguments: Dict[str, Any],
        timeout: float = 60.0,
    ) -> Any:
        host = SkillHostManager.get_instance()
        venv_python = host._venv_python(skill_id)

        if not host.has_venv(skill_id):
            raise RuntimeError(f"venv 不存在: {skill_id}（请先 create_venv）")

        if not _PYTHON_RUNNER.exists():
            raise RuntimeError(f"skill_runner.py 不存在: {_PYTHON_RUNNER}")

        # cwd 设为 venv 目录（限制相对路径访问范围）
        venv_dir = str(host._venv_path(skill_id))
        return await _run_subprocess_json(
            command=[venv_python, str(_PYTHON_RUNNER)],
            request={"module_path": module_path, "function_name": function_name, "arguments": arguments},
            skill_id=skill_id,
            timeout=timeout,
            cwd=venv_dir,
            plugin_type="skill_python",
        )


class NodeJsSkillRuntime:
    """在独立 node_modules 中执行 Node.js skill 模块（沙箱隔离）。

    协议与 Python 一致（JSON over stdio），通过 skill_runner.js 执行。
    module_path 为相对 env 目录的 JS 文件路径（如 "index.js"）。
    """

    async def execute(
        self,
        skill_id: str,
        module_path: str,
        function_name: str,
        arguments: Dict[str, Any],
        timeout: float = 60.0,
    ) -> Any:
        host = SkillHostManager.get_instance()
        if not host.has_node_env(skill_id):
            raise RuntimeError(f"node env 不存在: {skill_id}（请先 create_node_env）")

        node_exe = host._node_executable(skill_id)
        if not _NODE_RUNNER.exists():
            raise RuntimeError(f"skill_runner.js 不存在: {_NODE_RUNNER}")

        # cwd 设为 node env 目录
        env_dir = str(host._node_env_path(skill_id))
        return await _run_subprocess_json(
            command=[node_exe, str(_NODE_RUNNER)],
            request={"module_path": module_path, "function_name": function_name, "arguments": arguments},
            skill_id=skill_id,
            timeout=timeout,
            cwd=env_dir,
            plugin_type="skill_nodejs",
        )


class GoSkillRuntime:
    """执行编译后的 Go 二进制（沙箱隔离）。

    Go skill 不使用 JSON-over-stdio 协议（Go 编译为静态二进制，天然无依赖冲突）。
    直接以命令行参数传递 JSON 并执行。
    """

    async def execute(
        self,
        skill_id: str,
        arguments: Dict[str, Any],
        timeout: float = 60.0,
    ) -> Any:
        from infrastructure.sandbox.policy import run_sandboxed_subprocess

        host = SkillHostManager.get_instance()
        binary_path = host._go_binary_path(skill_id)

        if not host.has_go_binary(skill_id):
            raise RuntimeError(f"go binary 不存在: {skill_id}（请先 create_go_binary）")

        # cwd 设为 go binaries 目录
        policy = _build_skill_policy(
            skill_id, "skill_go",
            cwd=str(_GO_BINARIES_DIR),
            timeout=timeout,
        )
        result_line = await run_sandboxed_subprocess(
            command=[str(binary_path)],
            stdin_data=json.dumps(arguments),
            policy=policy,
            timeout=timeout,
        )
        return json.loads(result_line)
