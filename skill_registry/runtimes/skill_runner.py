"""通用 Skill 执行器 — 在 skill 的独立 venv 中被调用。

协议（JSON over stdio）：
  输入（stdin 一行 JSON）：
    {"module_path": "mymodule", "function_name": "execute", "arguments": {"text": "hello"}}
  输出（stdout 一行 JSON）：
    {"success": true, "result": "Hello, world!"}
  或
    {"success": false, "error": "ModuleNotFoundError: No module named 'xxx'"}

用法：
  venv_python skill_runner.py < stdin_request.json
"""
import json
import sys
import os
import asyncio

# 把项目根目录和 skill_registry 目录加入 sys.path，使 venv python 能找到 skill 模块
_RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))        # skill_registry/runtimes/
_SKILL_REGISTRY_DIR = os.path.dirname(_RUNNER_DIR)               # skill_registry/
_AGENT_DIR = os.path.dirname(_SKILL_REGISTRY_DIR)               # 项目根目录
for _p in (_AGENT_DIR, _SKILL_REGISTRY_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def handle_request(req: dict) -> dict:
    module_path = req.get("module_path", "")
    function_name = req.get("function_name", "")
    arguments = req.get("arguments", {})

    if not module_path or not function_name:
        return {"success": False, "error": "module_path 和 function_name 不能为空"}

    try:
        import importlib
        module = importlib.import_module(module_path)
        func = getattr(module, function_name, None)
        if func is None:
            return {"success": False, "error": f"函数 '{function_name}' 不存在于模块 '{module_path}'"}

        if asyncio.iscoroutinefunction(func):
            result = asyncio.run(func(**arguments))
        else:
            result = func(**arguments)

        return {"success": True, "result": result}

    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    line = sys.stdin.readline()
    if not line or not line.strip():
        print(json.dumps({"success": False, "error": "空输入"}))
        sys.stdout.flush()
        return

    try:
        req = json.loads(line.strip())
    except json.JSONDecodeError as e:
        print(json.dumps({"success": False, "error": f"JSON 解析失败: {e}"}))
        sys.stdout.flush()
        return

    resp = handle_request(req)
    print(json.dumps(resp, ensure_ascii=False, default=str))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
