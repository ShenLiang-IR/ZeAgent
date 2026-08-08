def sanitize_for_json(obj):
    if obj is None:
        return None
    try:
        from uuid import UUID
        if isinstance(obj, UUID):
            return str(obj)
    except ImportError:
        pass
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(item) for item in obj]
    try:
        from uuid import UUID
        if isinstance(obj, UUID):
            return str(obj)
    except (ImportError, AttributeError):
        pass
    try:
        return str(obj)
    except (TypeError, ValueError):
        return None
def sanitize_input(input_data):
    sanitized = {}
    sensitive_keys = ['api_key', 'password', 'secret', 'token', 'key']
    for key, value in input_data.items():
        key_lower = str(key).lower()
        if any(s in key_lower for s in sensitive_keys):
            sanitized[key] = "***REDACTED***"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_input(value)
        elif isinstance(value, str) and len(value) > 500:
            sanitized[key] = value[:500] + "...[truncated]"
        else:
            sanitized[key] = value
    return sanitized