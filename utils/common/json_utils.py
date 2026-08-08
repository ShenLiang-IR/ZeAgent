"""JSON 工具函数 — 安全解析 JSON 字段

从 14 处重复的 json.loads+isinstance+except 模式抽取。
"""


def parse_json_field(value, default=None):
    """安全解析 JSON 字段。

    - str → json.loads（失败返回 default）
    - dict/list → 直接返回
    - None/空 → default（默认 {}）

    >>> parse_json_field('{"a": 1}')
    {'a': 1}
    >>> parse_json_field(None)
    {}
    >>> parse_json_field('invalid', default=[])
    []
    """
    import json
    if not value:
        return default if default is not None else {}
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default if default is not None else {}
    return value
