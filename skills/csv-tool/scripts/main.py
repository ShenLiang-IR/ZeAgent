#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSV 工具 — 读取、筛选、转换 CSV 数据为 JSON。"""
import argparse, csv, json, sys, operator
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")

def parse_where(where_clause: str):
    """解析 'col>val' 或 'col=val' 条件，返回 (col, op_func, val)。"""
    for op_str, op_func in [(">=", operator.ge), ("<=", operator.le), (">", operator.gt), ("<", operator.lt), ("=", operator.eq), ("!=", operator.ne)]:
        if op_str in where_clause:
            col, val = where_clause.split(op_str, 1)
            col, val = col.strip(), val.strip()
            try: val = float(val) if "." in val or val.lstrip("-").isdigit() else val
            except: pass
            return col, op_func, val
    return None, None, None

def main():
    p = argparse.ArgumentParser(description="CSV 工具")
    p.add_argument("--file", required=True, help="CSV 文件路径")
    p.add_argument("--columns", default="", help="输出列名（逗号分隔）")
    p.add_argument("--where", default="", help="过滤条件")
    p.add_argument("--limit", type=int, default=0, help="行数限制")
    p.add_argument("--delimiter", default=",", help="CSV 分隔符")
    args = p.parse_args()

    cols = [c.strip() for c in args.columns.split(",") if c.strip()] if args.columns else None
    where_col, where_op, where_val = parse_where(args.where) if args.where else (None, None, None)

    try:
        with open(args.file, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=args.delimiter)
            rows = []
            for row in reader:
                if where_col and where_col in row:
                    cell = row[where_col]
                    try: cell_val = float(cell) if cell.replace(".", "").lstrip("-").isdigit() else cell
                    except: cell_val = cell
                    if not where_op(cell_val, where_val): continue
                if cols:
                    rows.append({k: row.get(k, "") for k in cols})
                else:
                    rows.append(dict(row))
                if args.limit and len(rows) >= args.limit: break
        print(json.dumps({"rows": rows, "count": len(rows)}, ensure_ascii=False, indent=2))
    except FileNotFoundError:
        print(json.dumps({"error": f"文件不存在: {args.file}"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))

if __name__ == "__main__": main()
