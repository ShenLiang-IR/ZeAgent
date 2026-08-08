from typing import Dict, Any
def merge_results_direct(results: Dict[str, Any]) -> str:
    merged = []
    for task_id, output in results.items():
        if output:
            if isinstance(output, str):
                merged.append(output)
            else:
                merged.append(str(output))
    return "".join(merged) if merged else ""
def merge_results_with_separator(
    results: Dict[str, Any],
    separator: str = "\n\n"
) -> str:
    merged = []
    for task_id, output in results.items():
        if output:
            if isinstance(output, str):
                merged.append(output)
            else:
                merged.append(str(output))
    return separator.join(merged) if merged else ""
def get_last_result(results: Dict[str, Any]) -> str:
    if not results:
        return ""
    last_output = list(results.values())[-1]
    return str(last_output) if last_output else ""