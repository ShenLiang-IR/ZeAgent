import time
from typing import Dict, Any, Optional
from loguru import logger
from dataclasses import dataclass, field
from datetime import datetime
@dataclass
class TaskMetrics:
    task_id: str
    agent: str
    start_time: float
    end_time: float = 0.0
    duration: float = 0.0
    success: bool = False
    error: Optional[str] = None
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
@dataclass
class ExecutionMetrics:
    session_id: str
    total_duration: float = 0.0
    planning_duration: float = 0.0
    execution_duration: float = 0.0
    summarize_duration: float = 0.0
    task_count: int = 0
    task_metrics: Dict[str, TaskMetrics] = field(default_factory=dict)
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    timestamp: str = ""
    execution_mode: str = ""
    parallel_efficiency: float = 0.0
class PerformanceLogger:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.start_time = time.time()
        self.planning_start: Optional[float] = None
        self.planning_duration: float = 0.0
        self.execution_start: Optional[float] = None
        self.execution_duration: float = 0.0
        self.summarize_start: Optional[float] = None
        self.summarize_duration: float = 0.0
        self.task_metrics: Dict[str, TaskMetrics] = {}
        self.llm_calls: int = 0
        self.tool_calls: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.current_task_id: Optional[str] = None
        self.execution_mode: str = ""
        self._task_start_times: Dict[str, float] = {}
    def log_planning_start(self):
        self.planning_start = time.time()
        logger.info(f"[Perf] [] session={self.session_id}")
    def log_planning_end(self, duration: float):
        self.planning_duration = duration
        logger.info(f"[Perf] [] ={duration:.2f}")
    def log_execution_start(self):
        self.execution_start = time.time()
        logger.info(f"[Perf] [] session={self.session_id}")
    def log_execution_end(self):
        if self.execution_start:
            self.execution_duration = time.time() - self.execution_start
        logger.info(f"[Perf] [] ={self.execution_duration:.2f}")
    def log_task_start(self, task_id: str, agent: str):
        self.current_task_id = task_id
        self._task_start_times[task_id] = time.time()
        self.task_metrics[task_id] = TaskMetrics(
            task_id=task_id,
            agent=agent,
            start_time=time.time()
        )
        logger.info(f"[Perf] [] {task_id} ({agent})")
    def set_execution_mode(self, mode: str, task_count: int):
        self.execution_mode = mode
        logger.info(f"[Perf] [] {mode} | : {task_count}")
    def log_task_end(self, task_id: str, success: bool, error: Optional[str] = None):
        logger.debug(f"[Perf] log_task_end called: task_id={task_id}, success={success}, available_tasks={list(self.task_metrics.keys())}")
        if task_id not in self.task_metrics:
            logger.warning(f"[Perf]  {task_id} ")
            return
        metrics = self.task_metrics[task_id]
        metrics.end_time = time.time()
        metrics.duration = metrics.end_time - metrics.start_time
        metrics.success = success
        if error:
            metrics.error = error
        status = "[OK]" if success else "[FAIL]"
        logger.info(
            f"[Perf] {status} : {task_id} | "
            f"={metrics.duration:.2f} | "
            f"LLM={metrics.llm_calls} | "
            f"={metrics.tool_calls}"
        )
    def log_llm_call(
        self,
        model: str,
        duration: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        response_length: int = 0,
        task_id: Optional[str] = None
    ):
        self.llm_calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        target_task_id = task_id or self.current_task_id
        if target_task_id and target_task_id in self.task_metrics:
            task_metrics = self.task_metrics[target_task_id]
            task_metrics.llm_calls += 1
            task_metrics.input_tokens += input_tokens
            task_metrics.output_tokens += output_tokens
        estimated_output = output_tokens or (response_length // 2)
        logger.debug(
            f"[Perf] 🤖 LLM: {model} | "
            f"={duration:.2f} | "
            f"={input_tokens}tokens | ={estimated_output}tokens"
        )
    def log_tool_call(
        self,
        tool_name: str,
        duration: float,
        success: bool = True,
        task_id: Optional[str] = None
    ):
        if not success:
            logger.debug(f"[Perf] 🔧 : {tool_name}")
            return
        self.tool_calls += 1
        target_task_id = task_id or self.current_task_id
        if target_task_id and target_task_id in self.task_metrics:
            self.task_metrics[target_task_id].tool_calls += 1
        logger.debug(f"[Perf] 🔧 : {tool_name} | ={duration:.2f}")
    def log_summarize_start(self):
        self.summarize_start = time.time()
        logger.info(f"[Perf] 📝 ")
    def log_summarize_end(self, duration: float):
        self.summarize_duration = duration
        logger.info(f"[Perf] [] ={duration:.2f}")
    def get_current_summary(self) -> Dict[str, Any]:
        now = time.time()
        total_elapsed = now - self.start_time
        completed_tasks = [
            m for m in self.task_metrics.values()
            if m.end_time > 0
        ]
        return {
            "session_id": self.session_id,
            "total_elapsed": total_elapsed,
            "completed_tasks": len(completed_tasks),
            "total_tasks": len(self.task_metrics),
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
        }
    def finalize(self) -> ExecutionMetrics:
        total_duration = time.time() - self.start_time
        total_input = sum(m.input_tokens for m in self.task_metrics.values())
        total_output = sum(m.output_tokens for m in self.task_metrics.values())
        metrics = ExecutionMetrics(
            session_id=self.session_id,
            total_duration=total_duration,
            planning_duration=self.planning_duration,
            execution_duration=self.execution_duration,
            summarize_duration=self.summarize_duration,
            task_count=len(self.task_metrics),
            task_metrics={k: v for k, v in self.task_metrics.items()},
            llm_calls=self.llm_calls,
            tool_calls=self.tool_calls,
            input_tokens=total_input,
            output_tokens=total_output,
            timestamp=datetime.now().isoformat(),
            execution_mode=self.execution_mode
        )
        self._print_summary(metrics)
        return metrics
    def _print_summary(self, metrics: ExecutionMetrics):
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"[Perf] 📊 ")
        logger.info("=" * 80)
        logger.info(f"  ID: {metrics.session_id}")
        logger.info(f"  : {metrics.execution_mode or ''}")
        logger.info(f"  : {metrics.total_duration:.2f}")
        logger.info(f"    ├─ : {metrics.planning_duration:.2f} ({self._pct(metrics.planning_duration, metrics.total_duration)}%)")
        logger.info(f"    ├─ : {metrics.execution_duration:.2f} ({self._pct(metrics.execution_duration, metrics.total_duration)}%)")
        logger.info(f"    └─ : {metrics.summarize_duration:.2f} ({self._pct(metrics.summarize_duration, metrics.total_duration)}%)")
        logger.info(f"  : {metrics.task_count} ")
        logger.info(f"  LLM: {metrics.llm_calls} ")
        logger.info(f"  : {metrics.tool_calls} ")
        if metrics.input_tokens > 0 or metrics.output_tokens > 0:
            logger.info(f"  Token:")
            logger.info(f"    ├─ : {metrics.input_tokens} tokens")
            logger.info(f"    └─ : {metrics.output_tokens} tokens")
        if metrics.task_metrics:
            logger.info(f"  :")
            for task_id, task_metrics in metrics.task_metrics.items():
                status = "[OK]" if task_metrics.success else "[FAIL]"
                logger.info(
                    f"    {status} {task_id} ({task_metrics.agent}): "
                    f"{task_metrics.duration:.2f} | "
                    f"LLM={task_metrics.llm_calls} | "
                    f"={task_metrics.tool_calls}"
                )
        logger.info("=" * 80)
        logger.info("")
    def _pct(self, value: float, total: float) -> str:
        if total == 0:
            return "0.0"
        return f"{value / total * 100:.1f}"