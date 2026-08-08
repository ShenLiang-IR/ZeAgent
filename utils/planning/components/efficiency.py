"""效率指导组件

提供工作流效率与工具优化指导，供规划 prompt 引用。
"""
from typing import Optional

BASE_EFFICIENCY = """## 效率指导
- 并行执行无依赖的任务以提升吞吐
- 链式依赖任务按拓扑序执行，前一个结果传递给后一个
- 避免冗余的 agent 调用，单 agent 能完成的不拆分"""

WORKFLOW_EXTENSION = """## 工作流扩展
根据任务依赖关系选择最优调度模式：无依赖用 parallel，有序链式用 sequential，复杂依赖用 dag。"""

TOOL_OPTIMIZATION_GUIDANCE = """## 工具优化
优先复用已加载的工具与 agent 图缓存，按需加载 MCP/skill 工具，避免重复初始化。"""


def get_efficiency_guidance(context: Optional[str] = None) -> str:
    return BASE_EFFICIENCY


def get_tool_optimization_guidance() -> str:
    return TOOL_OPTIMIZATION_GUIDANCE
