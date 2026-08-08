"""测试用 venv skill 模块 — 在独立 venv 中被 skill_runner.py 调用。

提供两个函数：
  echo(text) → 回显
  add(a, b) → 加法
"""


def echo(text: str) -> str:
    """回显输入文本。"""
    return f"Venv echo: {text}"


def add(a: int, b: int) -> int:
    """加法。"""
    return a + b
