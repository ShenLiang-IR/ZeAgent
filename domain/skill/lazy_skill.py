from typing import TYPE_CHECKING
from loguru import logger
from .entities import SkillMetadata, SkillExecutionResult
if TYPE_CHECKING:
    from .loader import SkillLoader
class LazySkillProxy:
    STATE_METADATA_ONLY = "metadata_only"
    STATE_LOADED = "loaded"
    STATE_FAILED = "failed"
    def __init__(self, metadata: SkillMetadata, loader: "SkillLoader"):
        self._metadata = metadata
        self._loader = loader
        self._implementation = None
        self._load_state = self.STATE_METADATA_ONLY
    @property
    def metadata(self) -> SkillMetadata:
        return self._metadata
    @property
    def is_loaded(self) -> bool:
        return self._load_state == self.STATE_LOADED
    async def execute(self, **kwargs) -> SkillExecutionResult:
        if self._load_state == self.STATE_METADATA_ONLY:
            logger.debug(
                f"[LazySkillProxy] : {self._metadata.skill_name}"
            )
            await self._load_implementation()
        if self._load_state == self.STATE_FAILED or self._implementation is None:
            return SkillExecutionResult(
                success=False,
                error=f" '{self._metadata.skill_name}' "
            )
        try:
            logger.debug(
                f"[LazySkillProxy] : {self._metadata.skill_name} "
                f": {list(kwargs.keys())}"
            )
            output = await self._implementation.execute(**kwargs)
            logger.info(
                f"[LazySkillProxy] : {self._metadata.skill_name}"
            )
            return SkillExecutionResult(success=True, output=output)
        except Exception as e:
            logger.error(
                f"[LazySkillProxy] : {self._metadata.skill_name} - {e}",
                exc_info=True
            )
            return SkillExecutionResult(
                success=False,
                error=str(e)
            )
    async def _load_implementation(self) -> None:
        try:
            logger.debug(
                f"[LazySkillProxy] : {self._metadata.skill_name} "
                f": {self._metadata.module_path}"
            )
            self._implementation = await self._loader.load_implementation(self._metadata)
            self._load_state = self.STATE_LOADED
            logger.info(
                f"[LazySkillProxy] : {self._metadata.skill_name}"
            )
        except Exception as e:
            self._load_state = self.STATE_FAILED
            logger.error(
                f"[LazySkillProxy] : {self._metadata.skill_name} - {e}",
                exc_info=True
            )
            # 不 re-raise：实现加载失败时设 STATE_FAILED，由 execute 返回失败结果
    async def preload(self) -> bool:
        if self._load_state != self.STATE_METADATA_ONLY:
            return self._load_state == self.STATE_LOADED
        await self._load_implementation()
        return self._load_state == self.STATE_LOADED
    def to_langchain_tool(self, agent_id: str = None, resource_context: dict = None):
        from langchain_core.tools import StructuredTool
        from pydantic import create_model
        fields = {}
        for param in self._metadata.parameters:
            fields[param.param_name] = param.to_langchain_field()
        if not fields:
            # 无参数时添加默认 text 参数，避免 LLM 调用时参数不匹配
            from pydantic import Field
            fields = {"text": (str, Field(..., description="要处理的文本"))}
            logger.debug(f"[LazySkillProxy] {self._metadata.skill_id} parameters，text")
        InputModel = create_model(f"{self._metadata.skill_id}Input", **fields)
        tool_description = self._metadata.build_tool_description()
        build_func_name = f"build_{self._metadata.skill_id}_tool"
        if self._metadata.module_path:
            try:
                import importlib
                module = importlib.import_module(self._metadata.module_path)
                build_func = getattr(module, build_func_name, None)
                if build_func and callable(build_func):
                    logger.info(f"[LazySkillProxy]  {build_func_name} : {self._metadata.skill_id}")
                    return build_func(
                        metadata=self._metadata,
                        agent_id=agent_id,
                        resource_context=resource_context,
                    )
            except Exception as e:
                logger.debug(f"[LazySkillProxy]  {self._metadata.module_path} : {e}")
        try:
            import importlib
            module = importlib.import_module("db_skills.implementations")
            build_func = getattr(module, build_func_name, None)
            if build_func and callable(build_func):
                logger.info(f"[LazySkillProxy]  implementations  {build_func_name}")
                return build_func(
                    metadata=self._metadata,
                    agent_id=agent_id,
                    resource_context=resource_context,
                )
        except Exception as e:
            logger.debug(f"[LazySkillProxy]  implementations : {e}")
        logger.info(f"[LLM-] {self._metadata.skill_id} - : {len(self._metadata.parameters)}")
        for param in self._metadata.parameters:
            req = "" if param.required else ""
            logger.info(f"[LLM-] {self._metadata.skill_id} - : {param.param_name} = {param.param_desc} ({req})")
        logger.debug(f"[LLM-] {self._metadata.skill_id} - :\n{tool_description}")
        if agent_id:
            logger.info(f"[LLM-] {self._metadata.skill_id} -  agent_id: {agent_id}")
        _agent_id = agent_id
        async def _invoke(**kwargs):
            if _agent_id and 'agent_id' not in kwargs:
                kwargs['agent_id'] = _agent_id
                logger.debug(f"[LazySkillProxy]  agent_id={_agent_id}  {self._metadata.skill_id}")
            logger.debug(f"[LazySkillProxy]  {self._metadata.skill_id} : {kwargs}")
            for key, value in kwargs.items():
                logger.debug(f"[LazySkillProxy]  {key} = {value} (type: {type(value).__name__})")
            result = await self.execute(**kwargs)
            if result.success:
                return result.output
            else:
                # 实现失败时返回友好提示（而非抛异常），让 LLM 能兜底用其他工具
                logger.warning(f"[LazySkillProxy] {self._metadata.skill_id} : {result.error}")
                return f"skill {self._metadata.skill_name} 未实现，无法执行。请使用其他可用工具。"
        return StructuredTool.from_function(
            func=None,
            coroutine=_invoke,
            name=self._metadata.skill_id,
            description=tool_description,
            args_schema=InputModel
        )
    def __repr__(self) -> str:
        return (
            f"LazySkillProxy(id={self._metadata.skill_id}, "
            f"name={self._metadata.skill_name}, "
            f"state={self._load_state})"
        )