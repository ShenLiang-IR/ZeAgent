import time
from loguru import logger
from typing import Any, Dict, List, Optional, Union
from langchain_core.outputs import LLMResult
from .base_callbacks import BaseCallbacksMixin
from .helpers import (
    get_run_id,
    format_duration,
    add_event,
    extract_model_name_unified
)
from .agent_inference import (
    infer_agent_from_tool,
    find_agent_from_task_tool
)
from ..common.logging_utils import (
    get_agent_logger,
    should_log_llm_io_details,
    format_log_payload
)
logger = get_agent_logger()
class LLMCallbacksMixin(BaseCallbacksMixin):
    def _log_formatted_prompts(self, prompt_content: Any) -> None:
        try:
            if isinstance(prompt_content, str):
                logger.info(prompt_content)
                return
            if isinstance(prompt_content, dict):
                if "messages" in prompt_content:
                    messages = prompt_content["messages"]
                    self._log_messages_list(messages)
                    return
                import json
                logger.info(json.dumps(prompt_content, ensure_ascii=False, indent=2, default=str))
                return
            if isinstance(prompt_content, list):
                self._log_messages_list(prompt_content)
                return
            if hasattr(prompt_content, 'content'):
                msg_type = type(prompt_content).__name__
                content = prompt_content.content
                logger.info(f"[{msg_type}] {content}")
                return
            logger.info(str(prompt_content))
        except Exception as e:
            logger.warning(f"记录 prompt 失败: {e}")
            logger.info(str(prompt_content))
    def _log_messages_list(self, messages: List[Any]) -> None:
        for i, msg in enumerate(messages, 1):
            try:
                if hasattr(msg, 'type'):
                    msg_type = msg.type.upper()
                    content = getattr(msg, 'content', str(msg))
                elif hasattr(msg, '__class__'):
                    msg_type = msg.__class__.__name__
                    content = getattr(msg, 'content', str(msg))
                elif isinstance(msg, dict):
                    msg_type = msg.get('type', msg.get('role', 'UNKNOWN')).upper()
                    content = msg.get('content', str(msg))
                else:
                    msg_type = 'MSG'
                    content = str(msg)
                if isinstance(content, str) and len(content) > 500:
                    content_display = content[:500] + f"... ({len(content)})"
                else:
                    content_display = content
                logger.info(f"[{i}] {msg_type}: {content_display}")
            except Exception as e:
                logger.info(f"[{i}] : {e}")
    def on_llm_start(
        self,
        serialized: Optional[Dict[str, Any]],
        prompts: Optional[List[str]],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        logger.info("=== [] on_llm_start  ===")
        run_id = get_run_id(run_id)
        self.start_times[run_id] = time.time()
        model_name = extract_model_name_unified(serialized)
        prompt_preview = ""
        if prompts and len(prompts) > 0:
            prompt_preview = prompts[0][:100] + "..." if len(prompts[0]) > 100 else prompts[0]
        agent_name = None
        if parent_run_id:
            parent_run_id_str = str(parent_run_id)
            for run_info in self.run_stack:
                if run_info.get('run_id') == parent_run_id_str:
                    agent_name = run_info.get('agent_name')
                    break
            if not agent_name and parent_run_id_str in self.tool_run_map:
                tool_identifier = self.tool_run_map[parent_run_id_str]
                inferred_agent = infer_agent_from_tool(tool_identifier, self.tool_to_subagent_map)
                if inferred_agent:
                    agent_name = inferred_agent
                    if self.verbose:
                        print(f"[DEBUG] LLM {tool_identifier}  SubAgent: {agent_name}")
            task_agent = find_agent_from_task_tool(self.tool_run_map)
            if task_agent:
                agent_name = task_agent
                if self.verbose:
                    print(f"[DEBUG] LLM task  SubAgent: {agent_name}")
        if agent_name:
            self.llm_run_map[run_id] = agent_name
        self.llm_model_map[run_id] = model_name
        log_message = f"🤖 LLM | : {model_name}"
        if agent_name:
            log_message += f" | Agent: {agent_name}"
        self._log(
            20,
            log_message,
            "llm_start",
            run_id=run_id,
            model_name=model_name,
            prompt_preview=prompt_preview,
            prompt_length=len(prompts[0]) if prompts else 0,
            agent_name=agent_name
        )
        add_event(
            self.event_queue,
            'llm_start',
            run_id,
            parent_run_id,
            {
                'model_name': model_name,
                'agent_name': agent_name,
                'prompt_preview': prompt_preview,
                'prompt_length': len(prompts[0]) if prompts else 0,
                'prompt_full': prompts[0] if prompts and len(prompts) > 0 else None
            }
        )
        if prompts and len(prompts) > 0:
            logger.info(f"{'='*60}")
            logger.info(f"[LLM] : {model_name} | Agent: {agent_name or 'Agent'}")
            logger.info(f"{'='*60}")
            prompt_content = prompts[0]
            self._log_formatted_prompts(prompt_content)
            logger.info(f"{'='*60}")
        if self.verbose:
            print(f"\n{'='*60}")
            print("🤖 LLM")
            print(f"  : {model_name}")
            print(f"  Run ID: {run_id[:8]}")
            if prompts:
                print(f"  : {prompt_preview}")
            print(f"{'='*60}\n")
    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        logger.info("=== [] on_llm_end  ===")
        run_id = get_run_id(run_id)
        duration = time.time() - self.start_times.get(run_id, time.time())
        token_usage = {}
        if response.llm_output:
            token_usage = response.llm_output.get('token_usage', {})
        if not token_usage or token_usage.get('total_tokens', 0) == 0:
            if response.generations and len(response.generations) > 0:
                if len(response.generations[0]) > 0:
                    generation = response.generations[0][0]
                    if hasattr(generation, 'usage_metadata') and generation.usage_metadata:
                        usage_metadata = generation.usage_metadata
                        token_usage = {
                            'total_tokens': getattr(usage_metadata, 'total_tokens', 0),
                            'prompt_tokens': getattr(usage_metadata, 'input_tokens', 0),
                            'completion_tokens': getattr(usage_metadata, 'output_tokens', 0)
                        }
                    elif hasattr(generation, 'response_metadata') and generation.response_metadata:
                        metadata = generation.response_metadata
                        if 'token_usage' in metadata:
                            token_usage = metadata['token_usage']
        total_tokens = token_usage.get('total_tokens', 0)
        prompt_tokens = token_usage.get('prompt_tokens', 0)
        completion_tokens = token_usage.get('completion_tokens', 0)
        content_preview = ""
        content_full = None
        if response.generations and len(response.generations) > 0:
            if len(response.generations[0]) > 0:
                content = response.generations[0][0].text
                content_preview = content[:100] + "..." if len(content) > 100 else content
                content_full = content
        agent_name = None
        parent_chain_name = None
        run_id_str = str(run_id)
        if run_id_str in self.llm_run_map:
            agent_name = self.llm_run_map[run_id_str]
            if self.verbose:
                print(f"[DEBUG] LLM llm_run_map  agent_name: {agent_name}")
        if parent_run_id:
            parent_run_id_str = str(parent_run_id)
            if not agent_name:
                for run_info in self.run_stack:
                    if run_info.get('run_id') == parent_run_id_str:
                        agent_name = run_info.get('agent_name')
                        parent_chain_name = run_info.get('chain_name')
                        break
            if not agent_name and parent_run_id_str in self.tool_run_map:
                tool_identifier = self.tool_run_map[parent_run_id_str]
                inferred_agent = infer_agent_from_tool(tool_identifier, self.tool_to_subagent_map)
                if inferred_agent:
                    agent_name = inferred_agent
                    if self.verbose:
                        print(f"[DEBUG] LLM {tool_identifier}  SubAgent: {agent_name}")
            task_agent = find_agent_from_task_tool(self.tool_run_map)
            if task_agent:
                agent_name = task_agent
                if self.verbose:
                    print(f"[DEBUG] LLM task  SubAgent: {agent_name}")
        self._log(
            20,
            f"[LLM] : {format_duration(duration)} | "
            f"Tokens: {total_tokens} (prompt: {prompt_tokens}, completion: {completion_tokens})" +
            (f" | Agent: {agent_name}" if agent_name else ""),
            "llm_end",
            run_id=run_id,
            duration=duration,
            token_count=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            content_preview=content_preview,
            agent_name=agent_name
        )
        add_event(
            self.event_queue,
            'llm_end',
            run_id,
            parent_run_id,
            {
                'duration': duration,
                'token_count': total_tokens,
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'content_preview': content_preview,
                'content_full': content_full,
                'agent_name': agent_name
            }
        )
        model_name = self.llm_model_map.get(run_id_str, 'unknown')
        should_log = should_log_llm_io_details()
        if should_log:
            logger.info(f"🧠 [LLM] : {model_name} | Agent: {agent_name or 'Agent'} | : {format_log_payload({'response': content_full or content_preview})}")
        else:
            logger.debug(f"[] on_llm_end: should_log_llm_io_details() = FalseLLM")
        self.llm_model_map.pop(run_id_str, None)
        if self.verbose:
            print(f"\n{'='*60}")
            print("[LLM]")
            print(f"  : {format_duration(duration)}")
            print(f"  Tokens: {total_tokens} (prompt: {prompt_tokens}, completion: {completion_tokens})")
            if content_preview:
                print(f"  : {content_preview}")
            print(f"{'='*60}\n")
    def on_llm_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: str,
        parent_run_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        duration = self._handle_error(
            error=error,
            run_id=run_id,
            event_type="llm_error",
            log_message_prefix="[LLM]",
            parent_run_id=parent_run_id
        )
        self._print_verbose_error(
            "[LLM]",
            error,
            duration
        )