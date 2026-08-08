"""业务监控指标（Prometheus 自定义 metrics）。

用 prometheus_client 定义 Counter/Histogram，注册到默认 REGISTRY，
通过 prometheus_fastapi_instrumentator 的 /metrics 端点（server.py 暴露）自动采集。

设计参见 docs/current.md §12 可观测性（E22 业务指标补充）。
prometheus_fastapi_instrumentator 默认只暴露 HTTP 层指标（http_requests /
http_request_duration_seconds / http_requests_inprogress），本模块补充业务层：
  - dispatch 调度次数 + 耗时（multi_agent_service 插桩）
  - chat 对话次数 + 耗时（chat_routes 插桩）
  - LLM token 消耗（usage_service 插桩）
  - 工具调用次数 + 健康度（task_executor / tool_health_tracker 插桩，第二期）
"""
from prometheus_client import Counter, Histogram

# ─── dispatch 调度（多 agent）───
DISPATCH_TOTAL = Counter(
    "agent_dispatch_total",
    "多 agent 调度次数",
    labelnames=["mode", "status"],  # mode=parallel/sequential/dag, status=completed/failed
)
DISPATCH_DURATION = Histogram(
    "agent_dispatch_duration_seconds",
    "多 agent 调度总耗时（秒）",
    labelnames=["mode"],
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)

# ─── chat 对话（单 agent / 直连）───
CHAT_TOTAL = Counter(
    "agent_chat_total",
    "对话请求次数",
    labelnames=["status"],  # status=success/failed
)
CHAT_DURATION = Histogram(
    "agent_chat_duration_seconds",
    "对话请求耗时（秒）",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120),
)

# ─── LLM token 消耗 ───
LLM_TOKENS_TOTAL = Counter(
    "agent_llm_tokens_total",
    "LLM token 消耗总量",
    labelnames=["type", "model"],  # type=prompt/completion
)

# ─── 工具调用（第二期在 task_executor 插桩）───
TOOL_CALLS_TOTAL = Counter(
    "agent_tool_calls_total",
    "工具调用次数",
    labelnames=["tool", "status"],  # status=success/failed
)
