import time
from typing import Any, Dict, Optional, Union
from .helpers import (
    get_run_id,
    format_duration,
    add_event
)
class BaseCallbacksMixin:
    def _handle_start(
        self,
        run_id: str,
        event_type: str,
        log_message: str,
        event_data: Optional[Dict[str, Any]] = None,
        parent_run_id: Optional[str] = None,
        **log_kwargs
    ) -> str:
        run_id = get_run_id(run_id)
        self.start_times[run_id] = time.time()
        self._log(
            20,
            log_message,
            event_type,
            run_id=run_id,
            **log_kwargs
        )
        add_event(
            self.event_queue,
            event_type,
            run_id,
            parent_run_id,
            event_data or {}
        )
        return run_id
    def _handle_end(
        self,
        run_id: str,
        event_type: str,
        log_message: str,
        event_data: Optional[Dict[str, Any]] = None,
        parent_run_id: Optional[str] = None,
        **log_kwargs
    ) -> float:
        run_id = get_run_id(run_id)
        duration = time.time() - self.start_times.get(run_id, time.time())
        self._log(
            20,
            log_message,
            event_type,
            run_id=run_id,
            duration=duration,
            **log_kwargs
        )
        final_event_data = {
            'duration': duration,
            **(event_data or {})
        }
        add_event(
            self.event_queue,
            event_type,
            run_id,
            parent_run_id,
            final_event_data
        )
        return duration
    def _handle_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        run_id: str,
        event_type: str,
        log_message_prefix: str,
        event_data: Optional[Dict[str, Any]] = None,
        parent_run_id: Optional[str] = None,
        **log_kwargs
    ) -> float:
        run_id = get_run_id(run_id)
        duration = time.time() - self.start_times.get(run_id, time.time())
        error_info = {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'duration': duration,
            **(event_data or {})
        }
        self._log(
            logging.ERROR,
            f"{log_message_prefix} | : {str(error)}",
            event_type,
            run_id=run_id,
            exc_info=True,
            **error_info,
            **log_kwargs
        )
        add_event(
            self.event_queue,
            event_type,
            run_id,
            parent_run_id,
            error_info
        )
        return duration
    def _print_verbose_start(
        self,
        title: str,
        run_id: str,
        **details
    ):
        if not self.verbose:
            return
        print(f"\n{'='*60}")
        print(title)
        print(f"  Run ID: {run_id[:8]}")
        for key, value in details.items():
            if value is not None:
                print(f"  {key}: {value}")
        print(f"{'='*60}\n")
    def _print_verbose_end(
        self,
        title: str,
        duration: float,
        **details
    ):
        if not self.verbose:
            return
        print(f"\n{'='*60}")
        print(title)
        print(f"  : {format_duration(duration)}")
        for key, value in details.items():
            if value is not None:
                print(f"  {key}: {value}")
        print(f"{'='*60}\n")
    def _print_verbose_error(
        self,
        title: str,
        error: Union[Exception, KeyboardInterrupt],
        duration: float,
        **details
    ):
        if not self.verbose:
            return
        print(f"\n{'='*60}")
        print(title)
        print(f"  : {type(error).__name__}")
        print(f"  : {str(error)}")
        print(f"  : {format_duration(duration)}")
        for key, value in details.items():
            if value is not None:
                print(f"  {key}: {value}")
        print(f"{'='*60}\n")