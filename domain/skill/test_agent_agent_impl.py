"""SKL_TEST_AGENT skill 实现：统计文本单词数并回显文本。

由 SkillLoader 通过 function_name 方式加载（FunctionSkillWrapper 包装）。
config_param: {"module_path":"domain.skill.test_agent_agent_impl","function_name":"analyze_text"}
"""
from loguru import logger


def analyze_text(text: str = "", **kwargs) -> str:
    """统计文本中的单词数量并回显文本。

    Args:
        text: 要分析的文本
        **kwargs: 接受 agent_id 等额外注入参数（LazySkillProxy._invoke 注入）

    Returns:
        回显文本 + 单词数量的结果字符串
    """
    if not text or not text.strip():
        logger.info("[analyze_text] 空文本")
        return "未提供文本，无法统计。"
    words = text.split()
    word_count = len(words)
    logger.info(f"[analyze_text] text='{text[:50]}', word_count={word_count}")
    return f"回显文本: {text}\n单词数量: {word_count}"
