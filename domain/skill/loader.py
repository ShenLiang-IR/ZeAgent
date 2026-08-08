import asyncio
from typing import Any
from loguru import logger
import importlib
from .entities import SkillMetadata
class SkillLoader:
    async def load_implementation(self, metadata: SkillMetadata) -> Any:
        # 检查运行时类型
        config = getattr(metadata, "_config_dict", None) or {}
        if isinstance(config, dict):
            runtime = config.get("runtime", "")
        else:
            runtime = ""

        if runtime == "python_venv":
            return await self._load_venv_implementation(metadata)
        elif runtime == "nodejs":
            return await self._load_nodejs_implementation(metadata)
        elif runtime == "go":
            return await self._load_go_implementation(metadata)

        return await self._load_inproc_implementation(metadata)

    async def _load_venv_implementation(self, metadata: SkillMetadata) -> Any:
        """加载 venv 隔离的 skill（通过 subprocess 执行，不在主进程 import）。"""
        if not metadata.module_path:
            raise ValueError(f"skill '{metadata.skill_name}' 缺少 module_path")
        if not metadata.function_name:
            raise ValueError(f"skill '{metadata.skill_name}' 缺少 function_name")
        from core.skill.host_manager import PythonSkillRuntime, SkillHostManager
        host = SkillHostManager.get_instance()
        if not host.has_venv(metadata.skill_id):
            raise RuntimeError(f"venv 不存在: {metadata.skill_id}")
        runtime = PythonSkillRuntime()
        wrapper = VenvSkillWrapper(runtime, metadata)
        logger.info(f"[SkillLoader] venv skill '{metadata.skill_name}' 加载完成")
        return wrapper

    async def _load_nodejs_implementation(self, metadata: SkillMetadata) -> Any:
        """加载 Node.js 隔离的 skill。"""
        if not metadata.module_path:
            raise ValueError(f"skill '{metadata.skill_name}' 缺少 module_path")
        if not metadata.function_name:
            raise ValueError(f"skill '{metadata.skill_name}' 缺少 function_name")
        from core.skill.host_manager import NodeJsSkillRuntime, SkillHostManager
        host = SkillHostManager.get_instance()
        if not host.has_node_env(metadata.skill_id):
            raise RuntimeError(f"node env 不存在: {metadata.skill_id}")
        runtime = NodeJsSkillRuntime()
        wrapper = VenvSkillWrapper(runtime, metadata)
        logger.info(f"[SkillLoader] nodejs skill '{metadata.skill_name}' 加载完成")
        return wrapper

    async def _load_go_implementation(self, metadata: SkillMetadata) -> Any:
        """加载 Go 编译的 skill。"""
        from core.skill.host_manager import GoSkillRuntime, SkillHostManager
        host = SkillHostManager.get_instance()
        if not host.has_go_binary(metadata.skill_id):
            raise RuntimeError(f"go binary 不存在: {metadata.skill_id}")
        runtime = GoSkillRuntime()
        wrapper = VenvSkillWrapper(runtime, metadata, is_go=True)
        logger.info(f"[SkillLoader] go skill '{metadata.skill_name}' 加载完成")
        return wrapper

    async def _load_inproc_implementation(self, metadata: SkillMetadata) -> Any:
        """加载主进程内的 skill（原有 importlib 逻辑）。"""
        if not metadata.module_path:
            raise ValueError(
                f" '{metadata.skill_name}'  module_path "
                f""
            )
        if not metadata.class_name and not metadata.function_name:
            raise ValueError(
                f" '{metadata.skill_name}'  class_name  function_name "
                f""
            )
        try:
            module_path = metadata.module_path
            if module_path.startswith("app."):
                module_path = module_path[4:]
                logger.debug(f"[SkillLoader]  app. : {metadata.module_path} -> {module_path}")
            logger.debug(
                f"[SkillLoader] : {module_path} "
                f"(: {metadata.skill_name})"
            )
            module = importlib.import_module(module_path)
            logger.debug(f"[SkillLoader] : {module_path}")
            if metadata.class_name:
                if not hasattr(module, metadata.class_name):
                    raise AttributeError(
                        f" '{metadata.module_path}'  '{metadata.class_name}'"
                    )
                cls = getattr(module, metadata.class_name)
                logger.debug(
                    f"[SkillLoader] : {metadata.class_name} "
                    f"(: {metadata.skill_name})"
                )
                instance = cls(metadata)
                logger.info(
                    f"[SkillLoader]  '{metadata.skill_name}' "
                )
                return instance
            elif metadata.function_name:
                if not hasattr(module, metadata.function_name):
                    raise AttributeError(
                        f" '{metadata.module_path}'  '{metadata.function_name}'"
                    )
                func = getattr(module, metadata.function_name)
                logger.debug(
                    f"[SkillLoader] : {metadata.function_name} "
                    f"(: {metadata.skill_name})"
                )
                wrapper = FunctionSkillWrapper(func, metadata)
                logger.info(
                    f"[SkillLoader]  '{metadata.skill_name}' "
                )
                return wrapper
        except ImportError as e:
            logger.error(
                f"[SkillLoader] : {metadata.module_path} - {e}",
                exc_info=True
            )
            raise ImportError(
                f" '{metadata.skill_name}'  '{metadata.module_path}': {e}"
            ) from e
        except AttributeError as e:
            logger.error(
                f"[SkillLoader] : {e}",
                exc_info=True
            )
            raise
        except Exception as e:
            logger.error(
                f"[SkillLoader]  '{metadata.skill_name}' : {e}",
                exc_info=True
            )
            raise
class VenvSkillWrapper:
    """隔离 skill 的执行包装器（通过 subprocess 调用独立运行时）。

    支持 Python venv / Node.js / Go 三种运行时。
    """
    def __init__(self, runtime, metadata: SkillMetadata, is_go: bool = False):
        self._runtime = runtime
        self._metadata = metadata
        self._is_go = is_go

    async def execute(self, **kwargs):
        logger.debug(f"[VenvSkillWrapper] 执行 skill: {self._metadata.skill_name} 参数: {list(kwargs.keys())}")
        try:
            if self._is_go:
                # Go binary 不需要 module_path/function_name，直接传 arguments
                result = await self._runtime.execute(
                    skill_id=self._metadata.skill_id,
                    arguments=kwargs,
                )
            else:
                result = await self._runtime.execute(
                    skill_id=self._metadata.skill_id,
                    module_path=self._metadata.module_path,
                    function_name=self._metadata.function_name,
                    arguments=kwargs,
                )
            logger.debug(f"[VenvSkillWrapper] 执行完成: {self._metadata.skill_name}")
            return result
        except Exception as e:
            logger.error(f"[VenvSkillWrapper] 执行失败: {self._metadata.skill_name} - {e}", exc_info=True)
            raise
class FunctionSkillWrapper:
    def __init__(self, func, metadata: SkillMetadata):
        self._func = func
        self._metadata = metadata
        self._is_coroutine = asyncio.iscoroutinefunction(func)
    async def execute(self, **kwargs):
        logger.debug(
            f"[FunctionSkillWrapper] : {self._metadata.skill_name} "
            f": {list(kwargs.keys())}"
        )
        try:
            if self._is_coroutine:
                result = await self._func(**kwargs)
            else:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: self._func(**kwargs))
            logger.debug(
                f"[FunctionSkillWrapper] : {self._metadata.skill_name}"
            )
            return result
        except Exception as e:
            logger.error(
                f"[FunctionSkillWrapper] : {self._metadata.skill_name} - {e}",
                exc_info=True
            )
            raise