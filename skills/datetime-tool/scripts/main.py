#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日期时间工具。"""
import argparse, json, sys
from datetime import datetime, timezone
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

def main():
    p = argparse.ArgumentParser(description="日期时间工具")
    p.add_argument("--action", default="now", help="操作: now/from-timestamp/to-timestamp/diff")
    p.add_argument("--value", default="", help="输入值")
    p.add_argument("--start", default="", help="开始日期")
    p.add_argument("--end", default="", help="结束日期")
    p.add_argument("--format", default="%Y-%m-%d %H:%M:%S", help="输出格式")
    p.add_argument("--timezone", default="", help="时区")
    args = p.parse_args()

    try:
        if args.action == "now":
            now = datetime.now()
            result = {
                "datetime": now.strftime(args.format),
                "timestamp": int(now.timestamp()),
                "iso": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "weekday": ["周一","周二","周三","周四","周五","周六","周日"][now.weekday()],
            }
        elif args.action == "from-timestamp":
            ts = int(args.value)
            dt = datetime.fromtimestamp(ts)
            result = {"datetime": dt.strftime(args.format), "timestamp": ts, "iso": dt.isoformat()}
        elif args.action == "to-timestamp":
            dt = datetime.strptime(args.value, "%Y-%m-%d %H:%M:%S" if " " in args.value else "%Y-%m-%d")
            result = {"timestamp": int(dt.timestamp()), "datetime": dt.strftime(args.format)}
        elif args.action == "diff":
            fmt = "%Y-%m-%d %H:%M:%S" if " " in args.start else "%Y-%m-%d"
            start = datetime.strptime(args.start, fmt)
            end = datetime.strptime(args.end, fmt)
            delta = end - start
            result = {
                "days": delta.days,
                "seconds": delta.total_seconds(),
                "hours": round(delta.total_seconds() / 3600, 1),
                "start": start.strftime(args.format),
                "end": end.strftime(args.format),
            }
        else:
            result = {"error": f"未知操作: {args.action}"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))

if __name__ == "__main__": main()
