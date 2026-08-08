#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEO关键词分析工具 — 关键词密度计算、长尾词推荐、内容优化建议。

在实际部署中，关键词数据由 LLM 搜索/分析后传入；
本脚本提供密度计算和结构化优化建议框架。
"""
import argparse
import json
import re
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def calc_keyword_density(text: str, keywords: list) -> dict:
    """计算关键词密度。"""
    text_lower = text.lower()
    total_chars = len(re.sub(r"\s", "", text))  # 去除空格后的总字符
    if total_chars == 0:
        return {}

    density = {}
    for kw in keywords:
        count = text_lower.count(kw.lower())
        # 密度 = 关键词出现次数 / 总字符数 * 100
        density[kw] = round(count / (total_chars / 100), 2)
    return density


def calc_word_frequency(text: str, top_n: int = 20) -> list:
    """词频分析。"""
    # 提取中文词汇（2-4字词）
    words = re.findall(r"[\u4e00-\u9fff]{2,4}", text)

    # 过滤停用词
    stopwords = {
        "我们", "他们", "你们", "这个", "那个", "什么", "怎么", "为什么",
        "可以", "没有", "已经", "现在", "然后", "因为", "所以", "但是",
        "如果", "虽然", "而且", "或者", "还是", "只能", "应该", "需要",
        "一个", "一种", "一些", "很多", "非常", "比较", "特别", "可能",
        "的话", "来说", "来说", "对于", "关于", "根据", "通过", "比如",
    }
    words = [w for w in words if w not in stopwords]

    counter = Counter(words)
    top_words = counter.most_common(top_n)
    return [{"word": w, "frequency": c} for w, c in top_words]


def generate_long_tail_keywords(core_keyword: str, category: str = "general") -> list:
    """生成长尾关键词建议。"""
    long_tail_patterns = {
        "general": [
            f"{core_keyword}教程",
            f"{core_keyword}入门",
            f"{core_keyword}是什么意思",
            f"{core_keyword}怎么用",
            f"{core_keyword}方法",
            f"{core_keyword}技巧",
            f"{core_keyword}推荐",
            f"{core_keyword}排行榜",
            f"{core_keyword}多少钱",
            f"{core_keyword}好不好",
            f"免费{core_keyword}",
            f"手机{core_keyword}",
            f"{core_keyword}软件",
            f"2024{core_keyword}",
            f"新手{core_keyword}",
        ],
        "howto": [
            f"如何{core_keyword}",
            f"怎么{core_keyword}",
            f"{core_keyword}步骤",
            f"{core_keyword}流程",
            f"快速{core_keyword}",
            f"简单{core_keyword}方法",
        ],
        "comparison": [
            f"{core_keyword} vs",
            f"{core_keyword}对比",
            f"{core_keyword}哪个好",
            f"{core_keyword}测评",
            f"{core_keyword}优缺点",
        ],
    }

    suggestions = []
    for pattern_cat, patterns in long_tail_patterns.items():
        for pattern in patterns:
            suggestions.append({
                "keyword": pattern,
                "category": pattern_cat,
                "search_intent": "informational" if "怎么" in pattern or "是什么" in pattern else "commercial",
            })
    return suggestions


def analyze_title_keywords(title: str, keywords: list) -> dict:
    """分析标题中的关键词使用。"""
    title_lower = title.lower()
    found_kw = [kw for kw in keywords if kw.lower() in title_lower]

    analysis = {
        "title": title,
        "keywords_in_title": found_kw,
        "keyword_count_in_title": len(found_kw),
        "first_keyword_position": 0,
    }

    # 找出第一个关键词在标题中的位置
    positions = []
    for kw in found_kw:
        idx = title_lower.index(kw.lower())
        positions.append(idx)
    if positions:
        analysis["first_keyword_position"] = min(positions)

    # 评分
    score = 0
    if len(found_kw) > 0:
        score += 30
    if len(found_kw) > 1:
        score += 20
    if positions and min(positions) < len(title) // 3:
        score += 20  # 关键词靠前加分
    if len(title) <= 30:
        score += 15
    if len(title) <= 20:
        score += 15
    analysis["score"] = min(score, 100)

    return analysis


def generate_recommendations(density: dict, freq: list, title_analysis: dict) -> list:
    """生成优化建议。"""
    recommendations = []

    # 密度检查
    for kw, d in density.items():
        if d < 0.5:
            recommendations.append(f"关键词「{kw}」密度偏低({d:.1f}%)，建议在正文中适当增加提及")
        elif d > 5.0:
            recommendations.append(f"关键词「{kw}」密度偏高({d:.1f}%)，可能被判定为关键词堆砌，建议降低频率")

    # 标题检查
    if title_analysis["keyword_count_in_title"] == 0:
        recommendations.append("标题中未包含任何目标关键词，建议至少包含1个核心关键词")
    elif title_analysis["keyword_count_in_title"] == 1:
        recommendations.append("标题可考虑增加1个长尾关键词以扩大搜索覆盖面")

    if title_analysis.get("first_keyword_position", 999) > len(title_analysis["title"]) // 2:
        recommendations.append("核心关键词在标题中位置偏后，建议前置以提高搜索权重")

    # 结构建议
    recommendations.append("建议在正文中合理使用H2/H3子标题，并在子标题中包含长尾关键词")
    recommendations.append("在首段自然融入核心关键词，有助于搜索引擎理解内容主题")

    return recommendations


def calculate_overall_score(density: dict, title_analysis: dict) -> int:
    """计算综合 SEO 评分。"""
    score = 50

    # 密度评分
    avg_density = sum(density.values()) / len(density) if density else 0
    if 1.0 <= avg_density <= 3.0:
        score += 20
    elif 0.5 <= avg_density <= 5.0:
        score += 10

    # 标题评分
    score += title_analysis.get("score", 0) // 5

    return min(score, 100)


def main():
    parser = argparse.ArgumentParser(description="SEO关键词分析工具")
    parser.add_argument("--text", default="", help="文章/内容文本")
    parser.add_argument("--file", default="", help="内容文件路径")
    parser.add_argument("--keywords", required=True, help="目标关键词（逗号分隔）")
    parser.add_argument("--mode", default="full", choices=["density", "suggestion", "full"], help="分析模式")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()

    # 读取文本
    if args.file:
        try:
            text = Path(args.file).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            print(json.dumps({"error": f"文件不存在: {args.file}"}, ensure_ascii=False))
            sys.exit(1)
    elif args.text:
        text = args.text
    else:
        print(json.dumps({"error": "需要 --text 或 --file 参数"}, ensure_ascii=False))
        sys.exit(1)

    keywords = [kw.strip() for kw in args.keywords.split(",") if kw.strip()]

    # 提取标题（第一行或第一个完整句子）
    lines = text.strip().split("\n")
    title_line = lines[0].strip("# ").strip() if lines else ""
    # 如果第一行以#开头，使用它作为标题
    if title_line.startswith("#"):
        title_line = title_line.lstrip("#").strip()

    result = {
        "keywords": keywords,
        "analyzed_at": datetime.now().isoformat(),
    }

    if args.mode in ("density", "full"):
        density = calc_keyword_density(text, keywords)
        result["density"] = density

        freq = calc_word_frequency(text, top_n=15)
        result["word_frequency"] = freq

        if title_line:
            title_analysis = analyze_title_keywords(title_line, keywords)
            result["title_analysis"] = title_analysis

        recommendations = generate_recommendations(
            result.get("density", {}),
            result.get("word_frequency", []),
            result.get("title_analysis", {}),
        )
        result["recommendations"] = recommendations

        result["score"] = calculate_overall_score(
            result.get("density", {}),
            result.get("title_analysis", {}),
        )

    if args.mode in ("suggestion", "full"):
        all_suggestions = []
        for kw in keywords:
            suggestions = generate_long_tail_keywords(kw)
            all_suggestions.extend(suggestions)
        result["long_tail_suggestions"] = all_suggestions[:20]

    result["content_stats"] = {
        "total_chars": len(text),
        "total_words_cn": len(re.findall(r"[\u4e00-\u9fff]", text)),
    }

    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(output_json)


if __name__ == "__main__":
    main()
