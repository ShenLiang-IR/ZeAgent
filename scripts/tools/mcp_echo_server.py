"""简单 MCP stdio server（echo 工具）

实现 MCP 协议的 JSON-RPC 2.0 over stdio，提供 echo 工具。
用于验证项目的 call_mcp_stdio 客户端。
"""
import json
import sys


def handle_request(req):
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}
        }
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"tools": [{
                "name": "echo",
                "description": "Echo input text back",
                "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}
            }]}
        }
    elif method == "tools/call":
        params = req.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        if name == "echo":
            text = args.get("text", "")
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": f"Echo: {text}"}]}
            }
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {name}"}}
    return {"jsonrpc": "2.0", "id": req_id, "result": {}}


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
        resp = handle_request(req)
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
    except Exception as e:
        sys.stdout.write(json.dumps({
            "jsonrpc": "2.0", "id": req.get("id", 0),
            "error": {"code": -32700, "message": str(e)}
        }) + "\n")
        sys.stdout.flush()
