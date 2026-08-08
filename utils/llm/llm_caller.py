import json
from loguru import logger
from typing import Any, Dict, List, Optional
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
class LLMCallResult:
    def __init__(
        self,
        success: bool,
        content: Optional[str] = None,
        parsed: Optional[Dict] = None,
        error: Optional[str] = None,
        model: Optional[str] = None,
        tokens: Optional[Dict[str, int]] = None
    ):
        self.success = success
        self.content = content
        self.parsed = parsed
        self.error = error
        self.model = model
        self.tokens = tokens or {}
    def __repr__(self) -> str:
        return (
            f"LLMCallResult(success={self.success}, model={self.model}, "
            f"content_len={len(self.content) if self.content else 0}, "
            f"error={self.error})"
        )
class LLMCaller:
    @staticmethod
    async def call_with_messages(
        messages: List[BaseMessage],
        llm_model: Optional[Any] = None,
        parse_json: bool = False,
        json_start_pattern: str = "```json",
        json_end_pattern: str = "```",
        **kwargs
    ) -> LLMCallResult:
        if not llm_model:
            from utils.llm import get_default_llm
            llm_model = get_default_llm()
        if not llm_model:
            logger.warning("[LLMCaller]  LLM ")
            return LLMCallResult(
                success=False,
                error=" LLM ",
                model=None
            )
        try:
            logger.info(f"[LLMCaller] ========== LLM ==========")
            logger.info(f"[LLMCaller] : {getattr(llm_model, 'model_name', None) or getattr(llm_model, 'model', 'unknown')}")
            logger.info(f"[LLMCaller] Base URL: {getattr(llm_model, 'base_url', 'unknown')}")
            logger.info(f"[LLMCaller] : {getattr(llm_model, 'default_headers', {})}")
            logger.info(f"[LLMCaller] : {len(messages)}")
            logger.debug(f"[LLMCaller] : {[{'role': m.type, 'content': m.content[:200] + '...' if len(m.content) > 200 else m.content} for m in messages]}")
            logger.info(f"[LLMCaller] ==============================")
            if hasattr(llm_model, 'ainvoke'):
                response = await llm_model.ainvoke(messages, **kwargs)
            else:
                response = llm_model.invoke(messages, **kwargs)
            response_text = response.content if hasattr(response, 'content') else str(response)
            from utils.message import extract_reasoning_from_content
            _, cleaned_content = extract_reasoning_from_content(response_text)
            if cleaned_content != response_text:
                logger.debug(f"[LLMCaller]  | : {len(response_text)} -> : {len(cleaned_content)}")
            response_text = cleaned_content
            parsed = None
            if parse_json:
                parsed = LLMCaller._parse_json_from_response(
                    response_text,
                    json_start_pattern,
                    json_end_pattern
                )
            tokens = LLMCaller._extract_tokens(response)
            model_name = getattr(llm_model, 'model_name', None) or getattr(llm_model, 'model', 'unknown')
            logger.debug(f"[LLMCaller] LLM  | : {model_name} | : {len(response_text)}")
            return LLMCallResult(
                success=True,
                content=response_text,
                parsed=parsed,
                error=None,
                model=model_name,
                tokens=tokens
            )
        except Exception as e:
            logger.error(f"[LLMCaller] LLM : {e}", exc_info=True)
            return LLMCallResult(
                success=False,
                content=None,
                parsed=None,
                error=str(e),
                model=None
            )
    @staticmethod
    async def call_with_prompt(
        system_prompt: str,
        user_content: str,
        llm_model: Optional[Any] = None,
        parse_json: bool = False,
        **kwargs
    ) -> LLMCallResult:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content)
        ]
        return await LLMCaller.call_with_messages(
            messages=messages,
            llm_model=llm_model,
            parse_json=parse_json,
            **kwargs
        )
    @staticmethod
    def _parse_json_from_response(
        response_text: str,
        start_pattern: str = "```json",
        end_pattern: str = "```"
    ) -> Optional[Dict]:
        try:
            if start_pattern in response_text:
                start_idx = response_text.find(start_pattern) + len(start_pattern)
                end_idx = response_text.find(end_pattern, start_idx)
                if end_idx > start_idx:
                    json_str = response_text[start_idx:end_idx].strip()
                    return json.loads(json_str)
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.warning(f"[LLMCaller] JSON : {e} | : {response_text[:100]}")
            return None
        except Exception as e:
            logger.warning(f"[LLMCaller] JSON : {e}")
            return None
    @staticmethod
    def _extract_tokens(response: Any) -> Dict[str, int]:
        tokens = {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'total_tokens': 0
        }
        try:
            if hasattr(response, 'response_metadata') and response.response_metadata:
                metadata = response.response_metadata
                if 'usage' in metadata:
                    usage = metadata['usage']
                    tokens['prompt_tokens'] = usage.get('prompt_tokens', 0)
                    tokens['completion_tokens'] = usage.get('completion_tokens', 0)
                    tokens['total_tokens'] = usage.get('total_tokens', 0)
                    return tokens
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage = response.usage_metadata
                tokens['prompt_tokens'] = getattr(usage, 'input_tokens', 0)
                tokens['completion_tokens'] = getattr(usage, 'output_tokens', 0)
                tokens['total_tokens'] = getattr(usage, 'total_tokens', 0)
                return tokens
        except Exception as e:
            logger.debug(f"[LLMCaller]  Token : {e}")
        return tokens