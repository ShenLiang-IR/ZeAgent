#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自媒体内容策划工具 — 生成选题日历、大纲框架、内容策略。

在实际部署中，此脚本配合 LLM 完成选题创意和文案生成；
本脚本提供策划框架和模板输出。
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 各平台内容策略特征
PLATFORM_STRATEGIES = {
    "xiaohongshu": {
        "name": "小红书",
        "style": "亲切真实、实用种草、视觉吸引",
        "best_publish_time": "工作日 7:00-8:30 / 12:00-13:30 / 18:00-21:00",
        "tag_strategy": "1-2个核心大词 + 2-3个长尾词 + 1个品牌词",
        "content_tips": ["封面图要精美有冲击力", "标题用数字和emoji吸引点击", "正文用短段落+emoji分隔", "结尾引导互动（点赞/收藏/评论）"],
        "ideal_length": "标题20字以内，正文400-800字",
    },
    "douyin": {
        "name": "抖音",
        "style": "快节奏、强视觉、前3秒抓人",
        "best_publish_time": "工作日 7:00-9:00 / 12:00-13:00 / 19:00-22:00，周末偏晚",
        "tag_strategy": "1-2个热门挑战标签 + 内容相关标签",
        "content_tips": ["前3秒必须抛出钩子或悬念", "节奏紧凑，信息密度高", "结尾引导点赞关注转发"],
        "ideal_length": "15-60秒短视频为佳",
    },
    "wechat": {
        "name": "微信公众号",
        "style": "深度、专业、有观点",
        "best_publish_time": "工作日 7:30-8:30 / 12:00-13:00 / 20:00-21:30",
        "tag_strategy": "文章分类标签 + 话题标签",
        "content_tips": ["标题要有信息量和吸引力", "开头用故事或数据引入", "排版清晰，多用小标题分段", "结尾设置互动或引导转发"],
        "ideal_length": "1500-3000字深度文章",
    },
    "bilibili": {
        "name": "B站",
        "style": "有趣有料、硬核内容、人格化表达",
        "best_publish_time": "工作日 12:00-14:00 / 17:00-19:00，周末全天",
        "tag_strategy": "分区标签 + 热门话题标签 + 内容关键词",
        "content_tips": ["标题党适度（但不能过分）", "内容要有干货或独特观点", "适度玩梗增加趣味性", "引导一键三连"],
        "ideal_length": "5-15分钟中长视频",
    },
    "zhihu": {
        "name": "知乎",
        "style": "专业、逻辑清晰、有深度分析",
        "best_publish_time": "工作日 12:00-14:00 / 20:00-23:00",
        "tag_strategy": "精准话题标签 + 专业领域词",
        "content_tips": ["开头直接给结论或核心观点", "用数据、案例支撑论点", "结构清晰：观点-论证-总结", "结尾可以抛出开放式问题引发讨论"],
        "ideal_length": "2000-5000字专业回答",
    },
}

# 常见内容类型模板
CONTENT_TYPES = {
    "教程类": {"structure": ["痛点引入", "解决方案概述", "步骤详解（3-5步）", "进阶技巧", "总结与资源推荐"], "angle": "教你学会XX"},
    "测评类": {"structure": ["测评对象介绍", "评测维度和标准", "逐一分析对比", "优缺点总结", "购买/使用建议"], "angle": "实测对比告诉你哪个更好"},
    "观点类": {"structure": ["抛出观点或争议", "论据支撑（数据/案例）", "反面观点分析", "结论与建议"], "angle": "关于XX，我想说..."},
    "故事类": {"structure": ["引入场景或冲突", "展开故事过程", "高潮或转折点", "感悟与启示", "互动引导"], "angle": "我的XX经历..."},
    "盘点类": {"structure": ["盘点主题说明", "逐一列举（5-10项）", "每项简短点评", "总结推荐"], "angle": "全网最全XX清单"},
    "合集类": {"structure": ["合集主题", "分类展示", "每类精选推荐", "使用场景说明"], "angle": "收藏！XX必备合集"},
}


def generate_weeks_calendar(start_date: datetime, count: int) -> list:
    """生成日期列表。"""
    dates = []
    for i in range(count):
        d = start_date + timedelta(days=i)
        # 跳过周末（可选，对于某些平台）
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        dates.append({
            "date": d.strftime("%m/%d"),
            "weekday": weekdays[d.weekday()],
            "is_weekend": d.weekday() >= 5,
        })
    return dates


def generate_topic_ideas(topic: str, platform: str, count: int, audience: str = "") -> list:
    """生成选题思路框架。"""
    ideas = []
    platform_info = PLATFORM_STRATEGIES.get(platform, PLATFORM_STRATEGIES["xiaohongshu"])
    content_type_keys = list(CONTENT_TYPES.keys())

    for i in range(min(count, 30)):
        content_type = content_type_keys[i % len(content_type_keys)]
        type_info = CONTENT_TYPES[content_type]

        # 根据序号生成不同角度的选题
        angles = [
            f"{topic}入门指南",
            f"{topic}的{i+1}个隐藏技巧",
            f"亲测{i+3}款{topic}工具",
            f"为什么你的{topic}总是做不好",
            f"{topic}避坑指南",
            f"{topic}进阶攻略",
            f"{audience}必备的{topic}清单" if audience else f"必备的{topic}清单",
            f"{topic}和你想的不一样",
            f"关于{topic}的{i+2}个真相",
            f"3分钟学会{topic}核心技巧",
        ]

        ideas.append({
            "index": i + 1,
            "title_candidate": angles[i % len(angles)],
            "content_type": content_type,
            "structure": type_info["structure"],
            "angle": type_info["angle"],
            "platform_tips": platform_info["content_tips"][:2],
        })

    return ideas


def generate_content_strategy(topic: str, platform: str, audience: str = "") -> dict:
    """生成内容策略。"""
    platform_info = PLATFORM_STRATEGIES.get(platform, PLATFORM_STRATEGIES["xiaohongshu"])

    strategy = {
        "platform": platform_info["name"],
        "positioning": f"围绕「{topic}」，打造{'专业' if audience else '实用'}、{'贴近' if audience else '可信'}的内容形象",
        "style": platform_info["style"],
        "audience_insight": f"目标用户：{audience if audience else '对{topic}感兴趣的泛用户'}",
        "posting_frequency": "建议每周3-5篇/条，保持稳定更新节奏",
        "best_publish_time": platform_info["best_publish_time"],
        "tag_strategy": platform_info["tag_strategy"],
        "engagement_tips": platform_info["content_tips"],
        "ideal_length": platform_info["ideal_length"],
        "growth_hacks": [
            "蹭热点：关注行业新闻和节日营销节点",
            "系列化：将热门选题做成系列内容提高留存",
            "互动：在评论区积极回复，建立粉丝关系",
            "跨界：和其他创作者联动/互推",
        ],
    }
    return strategy


def main():
    parser = argparse.ArgumentParser(description="自媒体内容策划工具")
    parser.add_argument("--topic", required=True, help="内容主题/行业领域")
    parser.add_argument("--platform", default="all",
                        choices=["all", "xiaohongshu", "douyin", "wechat", "bilibili", "zhihu"],
                        help="发布平台")
    parser.add_argument("--count", type=int, default=10, help="选题数量")
    parser.add_argument("--period", default="week", choices=["week", "month"], help="规划周期")
    parser.add_argument("--audience", default="", help="目标受众描述")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()

    platforms = (
        ["xiaohongshu", "douyin", "wechat", "bilibili", "zhihu"]
        if args.platform == "all"
        else [args.platform]
    )

    start_date = datetime.now()
    days = 30 if args.period == "month" else 7
    dates = generate_weeks_calendar(start_date, days)

    results = []
    for plat in platforms:
        ideas = generate_topic_ideas(args.topic, plat, args.count, args.audience)
        strategy = generate_content_strategy(args.topic, plat, args.audience)

        results.append({
            "platform": plat,
            "platform_name": PLATFORM_STRATEGIES.get(plat, {}).get("name", plat),
            "strategy": strategy,
            "calendar": [
                {"date": d, "topic": ideas[i % len(ideas)]["title_candidate"],
                 "type": ideas[i % len(ideas)]["content_type"]}
                for i, d in enumerate(dates)
            ],
            "topic_ideas": ideas,
        })

    output = {
        "topic": args.topic,
        "planning_period": f"{start_date.strftime('%Y-%m-%d')} 起 {args.period}",
        "generated_at": datetime.now().isoformat(),
        "platforms": results,
    }

    output_json = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(json.dumps({"success": True, "output_file": args.output}, ensure_ascii=False))
    else:
        print(output_json)


if __name__ == "__main__":
    main()
