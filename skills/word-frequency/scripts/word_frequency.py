"""词频分析工具：统计文本中词频，支持中英文，输出 Top N 高频词

对应 skills/word-frequency/SKILL.md 的本地实现。
读取文本文件，使用正则分词（中文按字符/双字词，英文按单词），
统计词频并输出 JSON 格式结果。
"""
import json
import re
import sys
import argparse
from pathlib import Path

# Windows console 默认 GBK，强制 UTF-8 输出避免中文乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
from collections import Counter


def tokenize(content: str, min_length: int = 1) -> list:
    """对文本进行分词：英文按单词，中文按单字+双字组合"""
    tokens = []
    # 英文单词
    en_words = re.findall(r'[a-zA-Z]+', content)
    tokens.extend(w.lower() for w in en_words if len(w) >= min_length)
    # 中文字符（连续中文字符串按单字和双字切分）
    cn_segments = re.findall(r'[\u4e00-\u9fff]+', content)
    for seg in cn_segments:
        # 单字
        for ch in seg:
            tokens.append(ch)
        # 双字词
        for i in range(len(seg) - 1):
            tokens.append(seg[i:i + 2])
    return tokens


_MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB 上限（防 OOM）


def analyze_file(filepath: str, top: int = 20, min_length: int = 1) -> dict:
    """分析单个文件的词频"""
    p = Path(filepath)
    size = p.stat().st_size
    if size > _MAX_FILE_SIZE:
        return {"error": f"文件过大（{size} 字节），超过上限 {_MAX_FILE_SIZE} 字节"}
    content = p.read_text(encoding='utf-8')
    tokens = tokenize(content, min_length)
    counter = Counter(tokens)
    total = len(tokens)
    unique = len(counter)
    top_words = []
    for word, count in counter.most_common(top):
        freq = f"{count / total * 100:.2f}%" if total > 0 else "0.00%"
        top_words.append({"word": word, "count": count, "frequency": freq})
    return {
        "file": filepath,
        "total_words": total,
        "unique_words": unique,
        "top_words": top_words,
    }


def main():
    parser = argparse.ArgumentParser(description="词频分析工具")
    parser.add_argument("file", help="要分析的文本文件路径")
    parser.add_argument("--top", type=int, default=20, help="返回前 N 个高频词")
    parser.add_argument("--min-length", type=int, default=1, help="最小词长度过滤")
    args = parser.parse_args()

    try:
        result = analyze_file(args.file, args.top, args.min_length)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except FileNotFoundError:
        print(json.dumps({"error": f"文件不存在: {args.file}"}, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
