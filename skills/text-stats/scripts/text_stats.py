"""文本统计工具：统计字符数、词数、行数，支持多文件汇总

对应 skills/text-stats/SKILL.md 的本地实现。
原 SKILL.md 设计为沙箱环境（/mnt/skills/）的 bash 脚本，
本地改为 Python 实现，输出格式与 SKILL.md 一致。
"""
import json
import sys
from pathlib import Path


def count_stats(filepath: str) -> dict:
    """统计单个文件的字符数、词数、行数"""
    content = Path(filepath).read_text(encoding='utf-8')
    chars = len(content)
    words = len(content.split())
    lines = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
    return {"path": filepath, "chars": chars, "words": words, "lines": lines}


def main():
    files = sys.argv[1:]
    if not files:
        print(json.dumps({"error": "no files specified"}, ensure_ascii=False))
        sys.exit(1)
    results = []
    for f in files:
        try:
            results.append(count_stats(f))
        except Exception as e:
            results.append({"path": f, "error": str(e)})
    totals = {
        "chars": sum(r.get("chars", 0) for r in results),
        "words": sum(r.get("words", 0) for r in results),
        "lines": sum(r.get("lines", 0) for r in results),
    }
    print(json.dumps({"files": results, "totals": totals}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
