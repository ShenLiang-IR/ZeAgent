from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
class PlanMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    DAG = "dag"
    DIRECT = "direct"
    AGENT = "agent"
    DYNAMIC = "dynamic"  # 迭代规划：plan 1 task → execute → observe → plan next
    DEBATE = "debate"    # 多 Agent 辩论对抗
    VOTE = "vote"        # 多 Agent 共识投票
class TaskNode(BaseModel):
    id: str = Field(..., description="")
    agent: str = Field(..., description=" SubAgent ")
    description: str = Field(..., description="")
    dependencies: List[str] = Field(default=[], description="ID")
    params: Dict[str, Any] = Field(default={}, description="")
    context_focus: Optional[str] = Field(None, description="")
    on_failure: str = Field(default="stop", description="stop(), continue(), retry()")
    # 动态重规划：条件分支触发
    condition: Optional[Dict[str, Any]] = Field(default=None, description="条件分支 {when: 'failed', replan: true}")
    # 动态重规划：动态插入触发
    replan_on: Optional[str] = Field(default=None, description="重规划触发表达式，如 result.contains('keyword')")
    # 动态重规划第二期：task 级条件循环
    loop: Optional[Dict[str, Any]] = Field(default=None, description="循环配置 {max_iterations: 3, until: \"result.contains('keyword')\"}。until 未满足则重跑同 plan，max_iterations 防无限")
class ExecutionPlan(BaseModel):
    mode: PlanMode = Field(..., description="")
    tasks: List[TaskNode] = Field(default=[], description="")
    original_query: str = Field(..., description="")
    auto_summary: bool = Field(default=True, description="")
    metadata: Dict[str, Any] = Field(default={}, description="ID")
    direct_response: Optional[str] = Field(None, description="DIRECT")
    def to_dict(self) -> Dict[str, Any]:
        if hasattr(self, "model_dump"):
            return self.model_dump()
        return self.dict()