#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标题优化工具 — 分析和优化内容标题，提升吸引力和点击率。

在实际部署中，标题变体由 LLM 生成后传入；
本脚本提供分析和评分框架。
"""
import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 标题优化模式
STYLE_PATTERNS = {
    "curiosity": {
        "name": "好奇心驱动",
        "templates": [
            "关于{T}，90%的人都不知道的{N}个真相",
            "为什么你的{T}总是做不好？答案在这里",
            "{T}背后不为人知的秘密",
            "我发现了一个{T}的隐藏技巧",
        ],
    },
    "digital": {
        "name": "数字列举型",
        "templates": [
            "{N}个让你{T}效率翻倍的实用方法",
            "亲测！这{N}款{T}工具，第3个最惊喜",
            "{T}必看的{N}个技巧，建议收藏",
            "花了{N}小时整理的{T}清单，拿走不谢",
        ],
    },
    "emotional": {
        "name": "情感共鸣型",
        "templates": [
            "终于有人把{T}说清楚了！",
            "看完这个{T}教程，我焦虑了整整一周",
            "{T}真的太重要了，后悔没有早知道",
            "一个{T}让我重新认识了自己",
        ],
    },
    "contrast": {
        "name": "对比冲突型",
        "templates": [
            "月薪3千和月薪3万的人的{T}差别",
            "{T}之前 vs {T}之后，效果惊人",
            "同样是{T}，为什么别人比你快10倍",
            "新手和老手的{T}有什么区别",
        ],
    },
    "pain_point": {
        "name": "痛点解决型",
        "templates": [
            "别再{T}了！试试这个高效方法",
            "{T}的{N}个常见错误，你中了几个",
            "90%的人都搞错了{T}的正确方式",
            "告别低效{T}，这个方法太绝了",
        ],
    },
    "urgency": {
        "name": "紧迫感",
        "templates": [
            "限时分享！{T}的终极指南",
            "今天才知道{T}可以这么做！",
            "再不学会{T}就晚了！",
        ],
    },
}

# 各平台标题规范
PLATFORM_RULES = {
    "xiaohongshu": {"max_length": 20, "emoji_ratio": "高", "style_priority": ["digital", "emotional", "curiosity"]},
    "douyin": {"max_length": 30, "emoji_ratio": "高", "style_priority": ["curiosity", "contrast", "urgency"]},
    "wechat": {"max_length": 30, "emoji_ratio": "中", "style_priority": ["curiosity", "digital", "emotional"]},
    "bilibili": {"max_length": 40, "emoji_ratio": "中", "style_priority": ["digital", "contrast", "curiosity"]},
    "zhihu": {"max_length": 40, "emoji_ratio": "低", "style_priority": ["curiosity", "contrast", "digital"]},
}


def analyze_title(title: str) -> dict:
    """分析原标题特征。"""
    analysis = {
        "length": len(title),
        "has_number": bool(re.search(r"\d+", title)),
        "has_emoji": bool(re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", title)),
        "has_question": "?" in title or "？" in title,
        "has_exclamation": "!" in title or "！" in title,
        "has_call_to_action": any(kw in title for kw in ["收藏", "点赞", "关注", "转发", "码住", "赶紧"]),
        "keywords_count": len(re.findall(r"[\u4e00-\u9fff]{2,}", title)),
    }

    # 评分（满分100）
    score = 50
    if 10 <= analysis["length"] <= 30:
        score += 10
    elif analysis["length"] > 40:
        score -= 10
    if analysis["has_number"]:
        score += 10
    if analysis["has_emoji"]:
        score += 5
    if analysis["has_question"]:
        score += 10
    if analysis["has_call_to_action"]:
        score += 5
    if analysis["keywords_count"] <= 2:
        score -= 5

    analysis["score"] = min(max(score, 0), 100)
    return analysis


def generate_variants(title: str, platform: str, styles: list, count: int) -> list:
    """生成标题变体。"""
    variants = []
    rules = PLATFORM_RULES.get(platform, PLATFORM_RULES["xiaohongshu"])

    # 提取核心关键词
    core_keywords = re.findall(r"[\u4e00-\u9fff]{2,}", title)
    topic = core_keywords[0] if core_keywords else title

    for i in range(min(count, 30)):
        style = styles[i % len(styles)]
        pattern_info = STYLE_PATTERNS.get(style, STYLE_PATTERNS["curiosity"])
        template = pattern_info["templates"][i % len(pattern_info["templates"])]

        # 填充模板
        variant_title = template.replace("{T}", topic)
        # 替换数字占位符
        numbers = [3, 5, 7, 10, 12, 15, 20, 30]
        variant_title = re.sub(r"\{N\}", str(numbers[i % len(numbers)]), variant_title)

        # 添加 emoji（根据平台特性）
        emojis = {
            "xiaohongshu": ["🔥", "✨", "💡", "📝", "🚀", "💯", "✅", "📌"],
            "douyin": ["🔥", "⚡", "👀", "💥", "🎯", "‼️"],
            "wechat": ["🔥", "📌", "✅", "👉"],
            "bilibili": ["🔥", "💡", "⚡", "💪", "🎯"],
            "zhihu": ["🔥", "📚", "💡", "✅"],
        }
        platform_emojis = emojis.get(platform, emojis["xiaohongshu"])
        emoji = platform_emojis[i % len(platform_emojis)]

        if rules["emoji_ratio"] == "高":
            variant_title = f"{emoji}{variant_title}{emoji}"
        elif rules["emoji_ratio"] == "中":
            variant_title = f"{emoji}{variant_title}"

        # 截断到合适长度
        max_len = rules["max_length"]
        if len(variant_title) > max_len:
            variant_title = variant_title[:max_len - 1] + "…"

        # 评估变体
        analysis = analyze_title(variant_title)

        variants.append({
            "title": variant_title,
            "style": style,
            "style_name": pattern_info["name"],
            "score": analysis["score"],
            "highlights": {
                "length_ok": 10 <= analysis["length"] <= 30,
                "has_number": analysis["has_number"],
                "has_emoji": analysis["has_emoji"],
            },
        })

    # 按评分排序
    variants.sort(key=lambda v: v["score"], reverse=True)
    return variants


def generate_recommendation(variants: list) -> str:
    """生成推荐建议。"""
    if not variants:
        return ""
    best = variants[0]
    return f"最推荐变体#{best.get('style_name', '')}「{best['title']}」，评分{best['score']}分，包含{best.get('style_name', '')}风格要素。"


def main():
    parser = argparse.ArgumentParser(description="标题优化工具")
    parser.add_argument("--title", required=True, help="原标题文本")
    parser.add_argument("--platform", default="xiaohongshu",
                        choices=["all", "xiaohongshu", "douyin", "wechat", "bilibili", "zhihu"],
                        help="目标平台")
    parser.add_argument("--count", type=int, default=5, help="生成数量")
    parser.add_argument("--style", default="all",
                        help="风格：curiosity/digital/emotional/contrast/pain_point/urgency/all")
    parser.add_argument("--analyze", default="true", help="是否分析原标题")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()

    platforms = list(PLATFORM_RULES.keys()) if args.platform == "all" else [args.platform]
    styles = (
        list(STYLE_PATTERNS.keys())
        if args.style == "all"
        else [s.strip() for s in args.style.split(",") if s.strip() in STYLE_PATTERNS]
    )

    results = []
    for plat in platforms:
        variants = generate_variants(args.title, plat, styles, args.count)
        results.append({
            "platform": plat,
            "platform_name": PLATFORM_RULES[plat].get("name", plat),
            "variants": variants,
            "recommendation": generate_recommendation(variants),
        })

    output = {
        "original_title": args.title,
        "original_analysis": analyze_title(args.title) if args.analyze.lower() != "false" else {},
        "platforms": results,
        "generated_at": datetime.now().isoformat(),
    }

    output_json = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(output_json)


if __name__ == "__main__":
    main()
