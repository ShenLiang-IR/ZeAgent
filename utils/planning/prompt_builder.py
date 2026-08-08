from datetime import date
from typing import Optional
from loguru import logger
from .components.efficiency import get_efficiency_guidance
from .components.quality import get_quality_assurance
def build_execution_prompt(
    base_prompt: str,
    response_mode: Optional[str] = None,
    enable_quality: bool = True,
    enable_efficiency: bool = True,
    disable_thinking: bool = False,
    context_focus: Optional[str] = None,
    execution_context: Optional[str] = None
) -> str:
    layers = [base_prompt]
    today = date.today().isoformat()
    layers.append(f"<environment_info>\n: {today}\n</environment_info>")
    if enable_quality:
        quality_section = get_quality_assurance(for_planning=False)
        layers.append(quality_section)
    if response_mode:
        mode_guidance = _get_mode_execution_guidance(response_mode)
        if mode_guidance:
            layers.append(mode_guidance)
            logger.debug(f"[prompt_builder]  '{response_mode}' ")
    if enable_efficiency:
        efficiency_prompt = get_efficiency_guidance(context=execution_context)
        layers.append(efficiency_prompt)
    if context_focus:
        layers.append(f"## \n{context_focus}")
    if disable_thinking:
        layers.append("/no_think")
    full_prompt = "\n\n".join(layers)
    return full_prompt
def _get_mode_execution_guidance(mode_name: str) -> str:
    if not mode_name:
        return ""
    try:
        from utils.config.mode_helper import get_mode_execution_guidance
        return get_mode_execution_guidance(mode_name)
    except Exception as e:
        logger.warning(f"[prompt_builder] : {e}")
        return ""
def build_workflow_prompt(
    base_prompt: str,
    response_mode: Optional[str] = None,
    enable_quality: bool = True,
    context_focus: Optional[str] = None,
    disable_thinking: bool = False
) -> str:
    return build_execution_prompt(
        base_prompt=base_prompt,
        response_mode=response_mode,
        enable_quality=enable_quality,
        enable_efficiency=True,
        disable_thinking=disable_thinking,
        context_focus=context_focus,
        execution_context="workflow"
    )
def build_agent_prompt(
    base_prompt: str,
    response_mode: Optional[str] = None,
    enable_quality: bool = True,
    enable_efficiency: bool = True,
    disable_thinking: bool = False
) -> str:
    return build_execution_prompt(
        base_prompt=base_prompt,
        response_mode=response_mode,
        enable_quality=enable_quality,
        enable_efficiency=enable_efficiency,
        disable_thinking=disable_thinking,
        context_focus=None,
        execution_context="agent"
    )