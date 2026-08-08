"""本地 Agent Card（A4）：从 subagent_config 生成能力卡，供 Planner 路由。

Planner 原先只拿 name+description 文本猜测能力；Agent Card 补充工具名/MCP/skills 等
能力信息，提升选 agent 准确率。仅用 config 字段（不触发工具加载，零额外开销）。

远程 agent 的 A2A Agent Card（/.well-known/agent.json）属 L1 终落地，本模块为本地。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentCard:
    """本地 agent 能力卡。"""
    name: str
    description: str
    tools: List[str] = field(default_factory=list)
    external_tools: List[str] = field(default_factory=list)
    mcp_tools: List[str] = field(default_factory=list)
    is_public: Optional[bool] = None
    input_schema: Optional[dict] = None   # IO schema：输入格式（JSON Schema 子集）
    output_schema: Optional[dict] = None  # IO schema：输出格式

    def to_prompt_text(self) -> str:
        """渲染为 Planner 可读文本（含能力+IO schema信息，优于纯 description）。"""
        parts = [f"- **{self.name}**: {self.description}"]
        caps: List[str] = []
        if self.tools:
            caps.append(f"内置工具: {', '.join(self.tools)}")
        if self.external_tools:
            caps.append(f"外部工具: {', '.join(self.external_tools)}")
        if self.mcp_tools:
            caps.append(f"MCP: {', '.join(self.mcp_tools)}")
        if caps:
            parts.append(f"  - 能力: {'; '.join(caps)}")
        if self.input_schema:
            parts.append(f"  - 输入: {self._schema_str(self.input_schema)}")
        if self.output_schema:
            parts.append(f"  - 输出: {self._schema_str(self.output_schema)}")
        return "\n".join(parts)

    @staticmethod
    def _schema_str(schema: dict) -> str:
        """把 JSON schema 子集渲染为紧凑文本。"""
        if not isinstance(schema, dict):
            return str(schema) if schema else "any"
        t = schema.get("type", "any")
        d = schema.get("description", "")
        result = str(t)
        if d:
            result += f" ({d})"
        # 嵌套 properties 简要展示
        props = schema.get("properties")
        if props and isinstance(props, dict):
            fields = ", ".join(f"{k}:{v.get('type','?')}" for k, v in props.items() if isinstance(v, dict))
            if fields:
                result += f" {{{fields}}}"
        return result


def _norm_list(val: Any) -> List[str]:
    """把 tools/mcp_tools 字段归一为 list[str]（容忍 str/JSON 字符串）。"""
    if not val:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        # 容忍 JSON 字符串或逗号分隔
        s = val.strip()
        if s.startswith("["):
            import json
            try:
                parsed = json.loads(s)
                return [str(x).strip() for x in parsed if str(x).strip()] if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                pass
        return [x.strip() for x in s.split(",") if x.strip()]
    return []


def build_agent_card(subagent_config: Dict[str, Any]) -> AgentCard:
    """从 subagent_config 构建本地 AgentCard（仅 config 字段，不加载工具）。"""
    name = subagent_config.get("agent_name") or subagent_config.get("name") or "unknown"
    desc = subagent_config.get("agent_description") or subagent_config.get("description") or ""
    # IO schema：从 config 读（可选，DB 无此列则 None=不渲染=向后兼容）
    input_schema = subagent_config.get("input_schema")
    output_schema = subagent_config.get("output_schema")
    # 容忍 JSON 字符串
    if isinstance(input_schema, str):
        try:
            import json
            input_schema = json.loads(input_schema)
        except (json.JSONDecodeError, TypeError):
            input_schema = None
    if isinstance(output_schema, str):
        try:
            import json
            output_schema = json.loads(output_schema)
        except (json.JSONDecodeError, TypeError):
            output_schema = None
    return AgentCard(
        name=name,
        description=desc,
        tools=_norm_list(subagent_config.get("tools")),
        external_tools=_norm_list(subagent_config.get("external_tools")),
        mcp_tools=_norm_list(subagent_config.get("mcp_tools")),
        is_public=subagent_config.get("is_public"),
        input_schema=input_schema,
        output_schema=output_schema,
    )


def format_agent_cards(subagents: List[Dict[str, Any]]) -> str:
    """把 subagent 列表渲染为 Planner 用的能力卡文本（替代原 _format_subagents）。"""
    lines = []
    for sa in subagents:
        if not sa:
            continue
        lines.append(build_agent_card(sa).to_prompt_text())
    return "\n".join(lines)
