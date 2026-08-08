from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from executor.workflow.types import TaskStatus


class TaskType(Enum):
    AGENT = "agent"
    TOOL = "tool"


@dataclass
class ExecutionOptions:
    """LangGraph 任务执行选项。"""
    enable_streaming: bool = True
    enable_checkpoint: bool = True
    timeout: Optional[int] = None
    tool_timeout: Optional[int] = None
    retry_on_error: bool = True
    max_retries: int = 3
    retry_backoff: str = "exponential"
    max_parallel_tools: int = 5
    max_parallel_tasks: int = 3
    deep_thinking: bool = False
    max_context_messages: int = 20
    preserve_tool_results: int = 3


@dataclass
class TaskContext:
    """LangGraph 任务上下文，承载单个任务执行所需的全部信息。"""
    session_id: str
    task_id: str
    parent_task_id: Optional[str] = None
    llm_model: Optional[BaseChatModel] = None
    tools: List[BaseTool] = field(default_factory=list)
    system_prompt: str = ""
    dependencies: Dict[str, Any] = field(default_factory=dict)
    deep_thinking: bool = False
    original_query: str = ""
    session_history: Optional[str] = None
    context_focus: Optional[str] = None
    skill_prompt_generator: Optional[Any] = None
    workspace_id: Optional[str] = None  # N4: 前向兼容，用于图缓存按 workspace 分桶（防多租户互相淘汰）


@dataclass
class ExecutionEvent:
    """LangGraph 执行事件，用于流式传输。"""
    type: str
    data: Any
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        valid_types = {"thinking", "tool_call", "tool_result", "message", "error", "status"}
        if self.type not in valid_types:
            raise ValueError(f"Invalid event type: {self.type}. Must be one of {valid_types}")


@dataclass
class TaskResult:
    """LangGraph 任务执行结果。"""
    task_id: str
    task_name: str
    status: TaskStatus
    task_type: TaskType
    duration: float
    output: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "task_type": self.task_type.value if isinstance(self.task_type, TaskType) else self.task_type,
            "duration": self.duration,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskResult":
        return cls(
            task_id=data["task_id"],
            task_name=data["task_name"],
            status=TaskStatus(data["status"]) if isinstance(data["status"], str) else data["status"],
            task_type=TaskType(data["task_type"]) if isinstance(data["task_type"], str) else data["task_type"],
            duration=data["duration"],
            output=data["output"],
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )
