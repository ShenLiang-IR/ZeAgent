import datetime
def calculate_duration(start_time, end_time):
    if not start_time or not end_time:
        return None
    try:
        if isinstance(start_time, str):
            start = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        else:
            start = start_time
        if isinstance(end_time, str):
            end = datetime.datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        else:
            end = end_time
        return (end - start).total_seconds()
    except Exception:
        return None