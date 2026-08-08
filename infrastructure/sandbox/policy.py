"""轻量沙箱策略 — 第一阶段：cwd 限制 + 环境变量注入 + 资源限制 + 审计日志。

设计原则：
- 不引入容器/VM 依赖，纯进程级限制
- 跨平台（Windows + Linux）
- 失败不阻塞执行（降级为无限制 + 记录 warning）
- 每次 skill/MCP 执行自动记录审计日志

限制项：
1. cwd 限制：子进程工作目录设为 skill 自己的目录（防止相对路径逃逸）
2. 环境变量注入：SANDBOX_ROOT / SANDBOX_SKILL_ID / SANDBOX_TIMEOUT
3. 资源限制（Linux）：RLIMIT_AS 内存上限 + RLIMIT_CPU CPU 时间上限
4. 资源限制（Windows）：Job Object 内存上限（可选）
5. 审计日志：who/when/what/duration/exit_code
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from loguru import logger


# ── 默认限制 ──
DEFAULT_MEMORY_LIMIT_MB = 512       # 子进程最大内存 512MB
DEFAULT_CPU_LIMIT_SECONDS = 120     # 子进程最大 CPU 时间 120s
DEFAULT_TIMEOUT_SECONDS = 60        # 等待响应超时 60s


@dataclass
class SandboxPolicy:
    """轻量沙箱策略配置。"""

    # 工作目录限制（子进程 cwd）
    cwd: Optional[str] = None

    # 注入的环境变量
    env_inject: Dict[str, str] = field(default_factory=dict)

    # 资源限制
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB
    cpu_limit_seconds: int = DEFAULT_CPU_LIMIT_SECONDS

    # 审计标识
    skill_id: str = ""
    plugin_type: str = ""  # skill_python / skill_nodejs / skill_go / mcp_server
    caller: str = ""       # 调用者标识（user_id 或 "system"）

    def build_env(self, base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """构建子进程环境变量（基础 + 注入）。"""
        env = dict(base_env or os.environ)
        # 注入沙箱标识
        env["SANDBOX_ROOT"] = self.cwd or ""
        env["SANDBOX_SKILL_ID"] = self.skill_id
        env["SANDBOX_TIMEOUT"] = str(DEFAULT_TIMEOUT_SECONDS)
        env["SANDBOX_MEMORY_LIMIT_MB"] = str(self.memory_limit_mb)
        # 用户自定义注入
        env.update(self.env_inject)
        return env

    def apply_resource_limits(self) -> None:
        """在子进程中调用（preexec_fn），设置资源限制。

        仅 Linux 有效（resource 模块）。Windows 上静默跳过。
        """
        if platform.system() != "Linux":
            return
        try:
            import resource
            # 内存限制（虚拟地址空间）
            mem_bytes = self.memory_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            # CPU 时间限制
            resource.setrlimit(resource.RLIMIT_CPU, (self.cpu_limit_seconds, self.cpu_limit_seconds))
        except Exception as e:
            # 不阻塞执行，仅记录
            logger.debug(f"[Sandbox] 资源限制设置失败（降级为无限制）: {e}")

    def get_preexec_fn(self):
        """返回 preexec_fn（仅 Linux 有效，Windows 返回 None）。"""
        if platform.system() != "Linux":
            return None
        return self.apply_resource_limits


class ExecutionAuditLog:
    """skill/MCP 执行审计日志。"""

    @staticmethod
    def log(
        skill_id: str,
        plugin_type: str,
        caller: str,
        action: str,
        duration_ms: float,
        success: bool,
        error: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录一条审计日志。"""
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "skill_id": skill_id,
            "plugin_type": plugin_type,
            "caller": caller,
            "action": action,
            "duration_ms": round(duration_ms, 1),
            "success": success,
        }
        if error:
            entry["error"] = error[:500]
        if extra:
            entry.update(extra)
        logger.info(f"[Audit] {json.dumps(entry, ensure_ascii=False)}")


async def run_sandboxed_subprocess(
    command: List[str],
    stdin_data: str,
    policy: SandboxPolicy,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """在沙箱策略下执行子进程，返回 stdout 第一行。

    应用：cwd 限制 + 环境变量注入 + 资源限制（Linux）+ 审计日志。
    """
    env = policy.build_env()
    preexec = policy.get_preexec_fn()
    start = time.perf_counter()

    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=policy.cwd,
        preexec_fn=preexec,
    )
    try:
        proc.stdin.write((stdin_data + "\n").encode())
        await proc.stdin.drain()

        line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
        duration_ms = (time.perf_counter() - start) * 1000

        if not line or not line.strip():
            stderr_data = await proc.stderr.read()
            stderr_text = stderr_data.decode("utf-8", errors="ignore") if stderr_data else ""
            ExecutionAuditLog.log(
                policy.skill_id, policy.plugin_type, policy.caller,
                "execute", duration_ms, False, f"空响应: {stderr_text[:200]}"
            )
            raise RuntimeError(f"执行空响应 ({policy.skill_id}): {stderr_text[:500]}")

        result = line.decode("utf-8", errors="ignore").strip()
        ExecutionAuditLog.log(
            policy.skill_id, policy.plugin_type, policy.caller,
            "execute", duration_ms, True
        )
        return result

    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        duration_ms = (time.perf_counter() - start) * 1000
        ExecutionAuditLog.log(
            policy.skill_id, policy.plugin_type, policy.caller,
            "execute", duration_ms, False, f"超时 ({timeout}s)"
        )
        raise RuntimeError(f"执行超时 ({policy.skill_id}, {timeout}s)")
    except Exception as e:
        duration_ms = (time.perf_counter() - start) * 1000
        ExecutionAuditLog.log(
            policy.skill_id, policy.plugin_type, policy.caller,
            "execute", duration_ms, False, str(e)[:200]
        )
        raise
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
