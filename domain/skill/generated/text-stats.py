"""Text statistics skill - 统计文本的字符数、词数、行数。"""
import json

def run(text: str) -> str:
    """统计文本的字符数、词数、行数。

    Args:
        text: 要统计的文本

    Returns:
        JSON 格式的统计结果
    """
    if not text:
        return json.dumps({"chars": 0, "words": 0, "lines": 0}, ensure_ascii=False)
    chars = len(text)
    words = len(text.split())
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    return json.dumps({"chars": chars, "words": words, "lines": lines}, ensure_ascii=False)
