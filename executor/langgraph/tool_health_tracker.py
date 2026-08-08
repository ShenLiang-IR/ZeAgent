from __future__ import annotations
from enum import Enum
from typing import Dict, List
from loguru import logger
class ToolCallStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
class ToolHealthTracker:
    def __init__(self):
        self._calls: Dict[str, dict] = {}
    def on_event(self, event) -> None:
        if event.type == "tool_result":
            self._update_call(event.data)
    def _update_call(self, data: dict) -> None:
        call_id = data.get("tool_call_id")
        if not call_id:
            return
        tool_name = data.get("tool_name", "unknown")
        content = data.get("content", "")
        status = data.get("status", "success")
        if "was cancelled" in (content or ""):
            status = ToolCallStatus.CANCELLED
        if call_id in self._calls:
            self._calls[call_id]["attempts"] += 1
            self._calls[call_id]["status"] = status
            if status == ToolCallStatus.ERROR:
                self._calls[call_id]["error"] = content[:500] if content else ""
        else:
            self._calls[call_id] = {
                "tool_name": tool_name,
                "status": status,
                "attempts": 1,
                "error": content[:500] if status == ToolCallStatus.ERROR and content else "",
            }
    def get_health(self) -> dict:
        tool_summary: Dict[str, List[str]] = {}
        for call_id, info in self._calls.items():
            name = info["tool_name"]
            if name not in tool_summary:
                tool_summary[name] = []
            tool_summary[name].append(call_id)
        failed_tools: List[str] = []
        details: Dict[str, dict] = {}
        for name, call_ids in tool_summary.items():
            has_error = False
            has_cancelled = False
            total_attempts = 0
            error_msg = ""
            for cid in call_ids:
                call_info = self._calls[cid]
                total_attempts += call_info["attempts"]
                if call_info["status"] == ToolCallStatus.ERROR:
                    has_error = True
                    error_msg = call_info.get("error", "")
                elif call_info["status"] == ToolCallStatus.CANCELLED:
                    has_cancelled = True
            if has_error:
                final_status = ToolCallStatus.ERROR
                failed_tools.append(name)
            elif has_cancelled:
                final_status = ToolCallStatus.CANCELLED
            else:
                final_status = ToolCallStatus.SUCCESS
            details[name] = {
                "final_status": final_status,
                "attempts": total_attempts,
            }
            if has_error:
                details[name]["error"] = error_msg
        overall = "healthy" if not failed_tools else "degraded"
        result = {
            "status": overall,
            "failed_tools": failed_tools,
            "details": details,
        }
        logger.debug(
            f"[ToolHealthTracker] : status={overall}, "
            f"total_tools={len(details)}, failed={failed_tools}"
        )
        return result