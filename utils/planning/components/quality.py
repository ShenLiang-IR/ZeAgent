"""质量指导组件

提供规划与执行阶段的质量标准，供规划 prompt 和执行链路引用。
"""

QUALITY_PLANNING = """## 规划质量标准
- 任务拆分粒度合理：避免过细（冗余开销）或过粗（单 task 承担过多职责）
- 模式选择基于依赖关系：无依赖→parallel，有序链式→sequential，有依赖→dag，单 agent→agent
- 每个 task 必须指定唯一 id、合法 agent name、清晰 description
- dependencies 只能引用已存在的 task id，禁止循环依赖
- 仅在确实需要 agent 时才生成 task，能直接回答的用 direct 模式"""

QUALITY_EXECUTION = """## 执行质量标准
- 工具调用失败时降级处理，尽量不影响其他 task
- 优先复用已加载的工具与 agent 图缓存，避免重复初始化
- 输出结果完整、准确、可追溯，失败 task 应给出错误标记"""


def get_quality_assurance(for_planning: bool = False) -> str:
    return QUALITY_PLANNING if for_planning else QUALITY_EXECUTION


def get_planning_quality() -> str:
    return QUALITY_PLANNING


def get_execution_quality() -> str:
    return QUALITY_EXECUTION
