import json
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import threading
_tool_stats_lock = threading.Lock()
_tool_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
    'total_calls': 0,
    'successful_calls': 0,
    'failed_calls': 0,
    'total_duration': 0.0,
    'min_duration': float('inf'),
    'max_duration': 0.0,
    'last_call_time': None,
    'first_call_time': None,
    'error_types': defaultdict(int),
    'recent_errors': []
})
class ToolMonitor:
    @staticmethod
    def record_tool_call(
        tool_name: str,
        duration: float,
        success: bool = True,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        with _tool_stats_lock:
            stats = _tool_stats[tool_name]
            stats['total_calls'] += 1
            stats['total_duration'] += duration
            stats['last_call_time'] = datetime.now().isoformat()
            if not stats['first_call_time']:
                stats['first_call_time'] = datetime.now().isoformat()
            if duration < stats['min_duration']:
                stats['min_duration'] = duration
            if duration > stats['max_duration']:
                stats['max_duration'] = duration
            if success:
                stats['successful_calls'] += 1
            else:
                stats['failed_calls'] += 1
                if error_type:
                    stats['error_types'][error_type] += 1
                error_info = {
                    'timestamp': datetime.now().isoformat(),
                    'error_type': error_type,
                    'error_message': error_message[:200] if error_message else None
                }
                stats['recent_errors'].append(error_info)
                if len(stats['recent_errors']) > 10:
                    stats['recent_errors'].pop(0)
    @staticmethod
    def get_tool_stats(tool_name: Optional[str] = None) -> Dict[str, Any]:
        with _tool_stats_lock:
            if tool_name:
                stats = _tool_stats.get(tool_name, {})
                if stats:
                    return ToolMonitor._format_stats(tool_name, stats)
                return {}
            result = {}
            for name, stats in _tool_stats.items():
                result[name] = ToolMonitor._format_stats(name, stats)
            return result
    @staticmethod
    def _format_stats(tool_name: str, stats: Dict[str, Any]) -> Dict[str, Any]:
        total_calls = stats['total_calls']
        if total_calls == 0:
            return {
                'tool_name': tool_name,
                'total_calls': 0,
                'successful_calls': 0,
                'failed_calls': 0,
                'success_rate': 0.0,
                'avg_duration': 0.0,
                'min_duration': 0.0,
                'max_duration': 0.0,
                'last_call_time': None,
                'first_call_time': None,
                'error_types': {},
                'recent_errors': []
            }
        successful_calls = stats['successful_calls']
        failed_calls = stats['failed_calls']
        total_duration = stats['total_duration']
        return {
            'tool_name': tool_name,
            'total_calls': total_calls,
            'successful_calls': successful_calls,
            'failed_calls': failed_calls,
            'success_rate': (successful_calls / total_calls) * 100 if total_calls > 0 else 0.0,
            'avg_duration': total_duration / total_calls if total_calls > 0 else 0.0,
            'min_duration': stats['min_duration'] if stats['min_duration'] != float('inf') else 0.0,
            'max_duration': stats['max_duration'],
            'last_call_time': stats['last_call_time'],
            'first_call_time': stats['first_call_time'],
            'error_types': dict(stats['error_types']),
            'recent_errors': stats['recent_errors']
        }
    @staticmethod
    def get_unused_tools(all_tool_names: List[str]) -> List[str]:
        with _tool_stats_lock:
            used_tools = set(_tool_stats.keys())
            return [tool for tool in all_tool_names if tool not in used_tools]
    @staticmethod
    def get_most_used_tools(limit: int = 10) -> List[Dict[str, Any]]:
        with _tool_stats_lock:
            all_stats = []
            for name, stats in _tool_stats.items():
                formatted = ToolMonitor._format_stats(name, stats)
                all_stats.append(formatted)
            all_stats.sort(key=lambda x: x['total_calls'], reverse=True)
            return all_stats[:limit]
    @staticmethod
    def get_failed_tools() -> List[Dict[str, Any]]:
        with _tool_stats_lock:
            failed_tools = []
            for name, stats in _tool_stats.items():
                if stats['failed_calls'] > 0:
                    formatted = ToolMonitor._format_stats(name, stats)
                    failed_tools.append(formatted)
            failed_tools.sort(key=lambda x: x['failed_calls'], reverse=True)
            return failed_tools
    @staticmethod
    def export_stats(file_path: Optional[Path] = None) -> str:
        if file_path is None:
            log_dir = Path(__file__).parent.parent.parent.parent / "logs"
            log_dir.mkdir(exist_ok=True)
            file_path = log_dir / f"tool_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        stats = ToolMonitor.get_tool_stats()
        export_data = {
            'export_time': datetime.now().isoformat(),
            'total_tools': len(stats),
            'stats': stats
        }
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        return str(file_path)
    @staticmethod
    def print_summary():
        stats = ToolMonitor.get_tool_stats()
        if not stats:
            print("\n[] ")
            return
        print("\n" + "=" * 80)
        print("[] ")
        print("=" * 80)
        total_calls = sum(s['total_calls'] for s in stats.values())
        total_successful = sum(s['successful_calls'] for s in stats.values())
        total_failed = sum(s['failed_calls'] for s in stats.values())
        print(f"\n:")
        print(f"  : {len(stats)}")
        print(f"  : {total_calls}")
        print(f"  : {total_successful}")
        print(f"  : {total_failed}")
        if total_calls > 0:
            print(f"  : {(total_successful / total_calls) * 100:.2f}%")
        most_used = ToolMonitor.get_most_used_tools(5)
        if most_used:
            print(f"\n (Top 5):")
            for i, tool_stat in enumerate(most_used, 1):
                print(f"  {i}. {tool_stat['tool_name']}: {tool_stat['total_calls']} , "
                      f" {tool_stat['success_rate']:.2f}%, "
                      f" {tool_stat['avg_duration']:.3f}s")
        failed_tools = ToolMonitor.get_failed_tools()
        if failed_tools:
            print(f"\n:")
            for tool_stat in failed_tools[:5]:
                print(f"  - {tool_stat['tool_name']}: {tool_stat['failed_calls']} , "
                      f" {tool_stat['success_rate']:.2f}%")
        print("=" * 80 + "\n")