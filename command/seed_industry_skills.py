"""初始化行业技能包到插件市场（tb_plugin）。

将 skills/ 目录下的行业技能（legal/finance/medical/media）发布到插件市场。
运行方式：python command/seed_industry_skills.py

幂等：plugin name 已存在则跳过。
发布后，用户可在 前端 > 插件市场 中浏览和安装这些技能。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 强制 UTF-8 输出（Windows GBK 终端兼容）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services.plugin_marketplace_service import PluginMarketplaceService, PLUGIN_TYPE_SKILL_PYTHON
from pathlib import Path
import json
import yaml
import re

# ──────────────────── 行业技能包清单 ────────────────────
# 每个技能对应 skills/ 目录下的一个子目录 + SKILL.md
INDUSTRY_PLUGINS = [
    # ═══════════ 法律行业 ═══════════
    {
        "name": "legal-contract-review",
        "display_name": "合同审查",
        "description": "分析合同条款、识别风险点、提供修改建议。支持买卖/租赁/劳动/服务/NDA 等常见合同类型审查。自动识别合同类型、扫描6大风险维度、提供修改建议。",
        "category": "legal",
        "tags": ["legal", "contract", "compliance", "risk", "法律", "合同"],
        "author": "system",
        "version": "1.0.0",
        "icon": "Document",
        "plugin_type": PLUGIN_TYPE_SKILL_PYTHON,
        "manifest": {
            "module_path": "skills.legal-contract-review.scripts.main",
            "function_name": "main",
            "config_param": {
                "category": "legal",
                "module_path": "skills.legal-contract-review.scripts.main",
                "function_name": "main",
                "lazy_load": True,
                "preload_priority": 0,
            },
            "parameters": [
                {"param_name": "file", "param_type": "string", "param_desc": "合同文件路径（txt/md/docx）", "required": True},
                {"param_name": "type", "param_type": "string", "param_desc": "合同类型：sales/lease/labor/service/nda", "required": False},
                {"param_name": "focus", "param_type": "string", "param_desc": "审查重点：all/risk/compliance/balance", "required": False},
            ],
            "dependencies": [],
        },
    },
    {
        "name": "legal-case-analyzer",
        "display_name": "法律案例分析",
        "description": "检索相关法条、分析案情要素、提供裁判倾向参考。支持民事/刑事/行政/商事/劳动争议各类案件。自动识别案由、匹配法条、提取关键要素、输出裁判倾向。",
        "category": "legal",
        "tags": ["legal", "case-law", "statute", "precedent", "法律", "案例"],
        "author": "system",
        "version": "1.0.0",
        "icon": "Search",
        "plugin_type": PLUGIN_TYPE_SKILL_PYTHON,
        "manifest": {
            "module_path": "skills.legal-case-analyzer.scripts.main",
            "function_name": "main",
            "config_param": {
                "category": "legal",
                "module_path": "skills.legal-case-analyzer.scripts.main",
                "function_name": "main",
                "lazy_load": True,
                "preload_priority": 0,
            },
            "parameters": [
                {"param_name": "case", "param_type": "string", "param_desc": "案情描述文本", "required": True},
                {"param_name": "category", "param_type": "string", "param_desc": "案件类别：civil/criminal/administrative/commercial/labor", "required": False},
                {"param_name": "keywords", "param_type": "string", "param_desc": "检索关键词（逗号分隔）", "required": False},
            ],
            "dependencies": [],
        },
    },
    {
        "name": "legal-doc-generator",
        "display_name": "法律文书生成",
        "description": "自动生成起诉状、答辩状、申请书、法律意见书、律师函、合同模板等常见法律文书。支持6种文书类型，输出格式规范、结构完整。",
        "category": "legal",
        "tags": ["legal", "document", "template", "litigation", "法律", "文书"],
        "author": "system",
        "version": "1.0.0",
        "icon": "Edit",
        "plugin_type": PLUGIN_TYPE_SKILL_PYTHON,
        "manifest": {
            "module_path": "skills.legal-doc-generator.scripts.main",
            "function_name": "main",
            "config_param": {
                "category": "legal",
                "module_path": "skills.legal-doc-generator.scripts.main",
                "function_name": "main",
                "lazy_load": True,
                "preload_priority": 0,
            },
            "parameters": [
                {"param_name": "type", "param_type": "string", "param_desc": "文书类型：complaint/answer/application/opinion/notice/contract", "required": True},
                {"param_name": "parties", "param_type": "string", "param_desc": "当事人信息（JSON字符串）", "required": False},
                {"param_name": "facts", "param_type": "string", "param_desc": "案件事实描述", "required": False},
                {"param_name": "claims", "param_type": "string", "param_desc": "诉讼请求/申请事项", "required": False},
                {"param_name": "format", "param_type": "string", "param_desc": "输出格式：md/txt", "required": False},
            ],
            "dependencies": [],
        },
    },

    # ═══════════ 金融行业 ═══════════
    {
        "name": "finance-report-analyzer",
        "display_name": "财报分析",
        "description": "解析资产负债表、利润表、现金流量表，自动计算ROE/ROA/毛利率/流动比率/资产负债率等15+项关键财务指标。支持同比环比分析，生成结构化分析报告。",
        "category": "finance",
        "tags": ["finance", "report", "accounting", "investment", "金融", "财报"],
        "author": "system",
        "version": "1.0.0",
        "icon": "DataAnalysis",
        "plugin_type": PLUGIN_TYPE_SKILL_PYTHON,
        "manifest": {
            "module_path": "skills.finance-report-analyzer.scripts.main",
            "function_name": "main",
            "config_param": {
                "category": "finance",
                "module_path": "skills.finance-report-analyzer.scripts.main",
                "function_name": "main",
                "lazy_load": True,
                "preload_priority": 0,
            },
            "parameters": [
                {"param_name": "file", "param_type": "string", "param_desc": "财务数据文件（JSON格式）", "required": True},
                {"param_name": "period", "param_type": "string", "param_desc": "分析期间（如2024Q4）", "required": False},
                {"param_name": "compare", "param_type": "string", "param_desc": "对比数据文件路径", "required": False},
                {"param_name": "metrics", "param_type": "string", "param_desc": "分析指标：profitability,leverage,efficiency,all", "required": False},
            ],
            "dependencies": [],
        },
    },
    {
        "name": "finance-market-monitor",
        "display_name": "金融市场监控",
        "description": "监控股票/指数/外汇/加密货币行情，计算MA/MACD/RSI/BOLL/KDJ等多项技术指标。支持异常波动预警（涨跌幅/RSI超买超卖/成交量异动），自动生成交易信号。",
        "category": "finance",
        "tags": ["finance", "market", "stock", "trading", "金融", "行情"],
        "author": "system",
        "version": "1.0.0",
        "icon": "TrendCharts",
        "plugin_type": PLUGIN_TYPE_SKILL_PYTHON,
        "manifest": {
            "module_path": "skills.finance-market-monitor.scripts.main",
            "function_name": "main",
            "config_param": {
                "category": "finance",
                "module_path": "skills.finance-market-monitor.scripts.main",
                "function_name": "main",
                "lazy_load": True,
                "preload_priority": 0,
            },
            "parameters": [
                {"param_name": "symbols", "param_type": "string", "param_desc": "品种代码（逗号分隔）", "required": True},
                {"param_name": "indicators", "param_type": "string", "param_desc": "技术指标：MA/MACD/RSI/BOLL/KDJ/VOL", "required": False},
                {"param_name": "alert", "param_type": "string", "param_desc": "预警配置（JSON）", "required": False},
            ],
            "dependencies": [],
        },
    },
    {
        "name": "finance-risk-calculator",
        "display_name": "金融风险计算",
        "description": "计算VaR（风险价值）、CVaR、年化波动率、夏普比率、索提诺比率、最大回撤、Beta系数、Alpha收益等风控指标。辅助投资组合风险评估和资产配置决策。",
        "category": "finance",
        "tags": ["finance", "risk", "portfolio", "quant", "金融", "风控"],
        "author": "system",
        "version": "1.0.0",
        "icon": "Warning",
        "plugin_type": PLUGIN_TYPE_SKILL_PYTHON,
        "manifest": {
            "module_path": "skills.finance-risk-calculator.scripts.main",
            "function_name": "main",
            "config_param": {
                "category": "finance",
                "module_path": "skills.finance-risk-calculator.scripts.main",
                "function_name": "main",
                "lazy_load": True,
                "preload_priority": 0,
            },
            "parameters": [
                {"param_name": "returns", "param_type": "string", "param_desc": "日收益率序列（JSON数组）", "required": True},
                {"param_name": "benchmark", "param_type": "string", "param_desc": "基准收益率序列", "required": False},
                {"param_name": "metrics", "param_type": "string", "param_desc": "指标：var,sharpe,drawdown,volatility,all", "required": False},
                {"param_name": "confidence", "param_type": "number", "param_desc": "VaR置信水平（默认0.95）", "required": False},
            ],
            "dependencies": [],
        },
    },

    # ═══════════ 医疗健康 ═══════════
    {
        "name": "medical-record-summarizer",
        "display_name": "病历摘要生成",
        "description": "从病历文本中提取关键诊疗信息（主诉、现病史、诊断、治疗、检查结果等），自动生成SOAP/结构化/简洁三种格式的病历摘要。支持多维度提取，匿名化处理。",
        "category": "medical",
        "tags": ["medical", "healthcare", "clinical", "record", "医疗", "病历"],
        "author": "system",
        "version": "1.0.0",
        "icon": "Notebook",
        "plugin_type": PLUGIN_TYPE_SKILL_PYTHON,
        "manifest": {
            "module_path": "skills.medical-record-summarizer.scripts.main",
            "function_name": "main",
            "config_param": {
                "category": "medical",
                "module_path": "skills.medical-record-summarizer.scripts.main",
                "function_name": "main",
                "lazy_load": True,
                "preload_priority": 0,
            },
            "parameters": [
                {"param_name": "text", "param_type": "string", "param_desc": "病历文本内容", "required": True},
                {"param_name": "format", "param_type": "string", "param_desc": "摘要格式：soap/structured/brief", "required": False},
                {"param_name": "extract", "param_type": "string", "param_desc": "提取内容：all/diagnosis/treatment/lab", "required": False},
            ],
            "dependencies": [],
        },
    },
    {
        "name": "medical-drug-query",
        "display_name": "药品信息查询",
        "description": "查询药品说明书信息，提供适应症、用法用量、不良反应、禁忌症、药物相互作用等结构化数据。内置常用药品信息库，支持通用名/商品名检索。",
        "category": "medical",
        "tags": ["medical", "pharmacy", "drug", "medication", "医疗", "药品"],
        "author": "system",
        "version": "1.0.0",
        "icon": "MedicineBottle",
        "plugin_type": PLUGIN_TYPE_SKILL_PYTHON,
        "manifest": {
            "module_path": "skills.medical-drug-query.scripts.main",
            "function_name": "main",
            "config_param": {
                "category": "medical",
                "module_path": "skills.medical-drug-query.scripts.main",
                "function_name": "main",
                "lazy_load": True,
                "preload_priority": 0,
            },
            "parameters": [
                {"param_name": "drug", "param_type": "string", "param_desc": "药品名称（通用名/商品名）", "required": True},
                {"param_name": "info", "param_type": "string", "param_desc": "查询类型：all/indication/dosage/adverse/interaction/contraindication", "required": False},
            ],
            "dependencies": [],
        },
    },
    {
        "name": "medical-report-parser",
        "display_name": "医学报告解析",
        "description": "解析化验单、影像报告、体检报告等医学报告，自动提取20+常见指标项（血常规/肝功能/肾功能/血脂/血糖/肿瘤标志物），判断异常值并生成解读说明。",
        "category": "medical",
        "tags": ["medical", "lab-report", "diagnosis", "health-check", "医疗", "报告"],
        "author": "system",
        "version": "1.0.0",
        "icon": "Files",
        "plugin_type": PLUGIN_TYPE_SKILL_PYTHON,
        "manifest": {
            "module_path": "skills.medical-report-parser.scripts.main",
            "function_name": "main",
            "config_param": {
                "category": "medical",
                "module_path": "skills.medical-report-parser.scripts.main",
                "function_name": "main",
                "lazy_load": True,
                "preload_priority": 0,
            },
            "parameters": [
                {"param_name": "file", "param_type": "string", "param_desc": "报告文件路径", "required": True},
                {"param_name": "type", "param_type": "string", "param_desc": "报告类型：lab/imaging/physical", "required": False},
                {"param_name": "reference", "param_type": "string", "param_desc": "是否显示参考范围", "required": False},
            ],
            "dependencies": [],
        },
    },

    # ═══════════ 自媒体 ═══════════
    {
        "name": "media-content-planner",
        "display_name": "内容策划",
        "description": "根据主题和行业生成内容日历、选题方向、大纲框架。支持小红书/抖音/微信公众号/B站/知乎5大平台，提供教程/测评/观点/故事/盘点/合集6种内容类型模板。适配各平台发布时间策略。",
        "category": "media",
        "tags": ["media", "content", "planning", "creator", "自媒体", "策划"],
        "author": "system",
        "version": "1.0.0",
        "icon": "Calendar",
        "plugin_type": PLUGIN_TYPE_SKILL_PYTHON,
        "manifest": {
            "module_path": "skills.media-content-planner.scripts.main",
            "function_name": "main",
            "config_param": {
                "category": "media",
                "module_path": "skills.media-content-planner.scripts.main",
                "function_name": "main",
                "lazy_load": True,
                "preload_priority": 0,
            },
            "parameters": [
                {"param_name": "topic", "param_type": "string", "param_desc": "内容主题/行业领域", "required": True},
                {"param_name": "platform", "param_type": "string", "param_desc": "发布平台：xiaohongshu/douyin/wechat/bilibili/zhihu/all", "required": False},
                {"param_name": "count", "param_type": "integer", "param_desc": "生成选题数量", "required": False},
                {"param_name": "audience", "param_type": "string", "param_desc": "目标受众描述", "required": False},
            ],
            "dependencies": [],
        },
    },
    {
        "name": "media-headline-optimizer",
        "display_name": "标题优化",
        "description": "根据平台特性和文案心理学，对标题进行多维度优化。支持好奇心/数字列举/情感共鸣/对比冲突/痛点解决/紧迫感6种风格，自动适配不同平台标题规范，生成带评分的多版本标题。",
        "category": "media",
        "tags": ["media", "headline", "copywriting", "optimization", "自媒体", "标题"],
        "author": "system",
        "version": "1.0.0",
        "icon": "EditPen",
        "plugin_type": PLUGIN_TYPE_SKILL_PYTHON,
        "manifest": {
            "module_path": "skills.media-headline-optimizer.scripts.main",
            "function_name": "main",
            "config_param": {
                "category": "media",
                "module_path": "skills.media-headline-optimizer.scripts.main",
                "function_name": "main",
                "lazy_load": True,
                "preload_priority": 0,
            },
            "parameters": [
                {"param_name": "title", "param_type": "string", "param_desc": "原标题文本", "required": True},
                {"param_name": "platform", "param_type": "string", "param_desc": "目标平台：xiaohongshu/douyin/wechat/bilibili/zhihu", "required": False},
                {"param_name": "count", "param_type": "integer", "param_desc": "生成变体数量", "required": False},
                {"param_name": "style", "param_type": "string", "param_desc": "风格：curiosity/digital/emotional/contrast/pain_point/urgency/all", "required": False},
            ],
            "dependencies": [],
        },
    },
    {
        "name": "media-seo-analyzer",
        "display_name": "SEO关键词分析",
        "description": "分析内容关键词密度、词频分布，推荐长尾关键词（信息型/商业型），评估搜索竞争度，提供包括标题优化、结构优化在内的完整SEO建议。生成综合评分。",
        "category": "media",
        "tags": ["media", "seo", "keyword", "content-optimization", "自媒体", "SEO"],
        "author": "system",
        "version": "1.0.0",
        "icon": "Search",
        "plugin_type": PLUGIN_TYPE_SKILL_PYTHON,
        "manifest": {
            "module_path": "skills.media-seo-analyzer.scripts.main",
            "function_name": "main",
            "config_param": {
                "category": "media",
                "module_path": "skills.media-seo-analyzer.scripts.main",
                "function_name": "main",
                "lazy_load": True,
                "preload_priority": 0,
            },
            "parameters": [
                {"param_name": "text", "param_type": "string", "param_desc": "文章/内容文本", "required": True},
                {"param_name": "keywords", "param_type": "string", "param_desc": "目标关键词（逗号分隔）", "required": True},
                {"param_name": "mode", "param_type": "string", "param_desc": "分析模式：density/suggestion/full", "required": False},
            ],
            "dependencies": [],
        },
    },
]


def seed():
    """将行业技能包发布到插件市场（tb_plugin）。
    
    使用 PluginMarketplaceService.publish_plugin() 注册到 tb_plugin 表，
    workspace_id=None 表示官方全局插件，所有工作空间可见。
    """
    service = PluginMarketplaceService()
    published = 0
    skipped = 0
    errors = 0

    print("=" * 60)
    print("  行业技能包 → 插件市场发布")
    print("=" * 60)
    print()

    for plugin_config in INDUSTRY_PLUGINS:
        name = plugin_config["name"]
        display_name = plugin_config["display_name"]
        category = plugin_config["category"]

        try:
            # 幂等：检查是否已发布
            existing = service.plugin_repo.get_by_name(name)
            if existing:
                skipped += 1
                print(f" ⏭  [{category}] {display_name} ({name}) — 已存在，跳过")
                continue

            # 发布到市场
            result = service.publish_plugin(
                name=name,
                display_name=display_name,
                plugin_type=plugin_config["plugin_type"],
                description=plugin_config["description"],
                icon=plugin_config["icon"],
                category=category,
                tags=plugin_config["tags"],
                author=plugin_config["author"],
                version=plugin_config["version"],
                manifest=plugin_config["manifest"],
                mcp_config={},
                status="1",  # 直接上架
                workspace_id=None,  # 官方全局插件
            )
            published += 1
            plugin_id = result.get("plugin_id", "?")
            print(f" ✅ [{category}] {display_name} ({name}) → plugin_id={plugin_id}")
        except Exception as e:
            errors += 1
            print(f" ❌ [{category}] {display_name} ({name}) 发布失败: {e}")

    print()
    print("=" * 60)
    print(f"  发布完成：成功 {published} 个，跳过 {skipped} 个，失败 {errors} 个")
    print("=" * 60)
    print()
    print("按行业分类：")
    categories = {}
    for p in INDUSTRY_PLUGINS:
        cat = p["category"]
        categories.setdefault(cat, []).append(p)
    for cat, plugins in categories.items():
        cat_names = {"legal": "⚖️  法律", "finance": "💰 金融", "medical": "🏥 医疗健康", "media": "📱 自媒体"}
        print(f"  {cat_names.get(cat, cat)}（{len(plugins)}个）：")
        for p in plugins:
            print(f"    - {p['display_name']} ({p['name']})")
    print()
    print("💡 提示：")
    print("  1. 前端 插件市场 页面可浏览和安装这些技能")
    print("  2. 安装时会自动创建 tb_skill 记录和隔离运行时环境")
    print("  3. 安装后需调用 /api/admin/plugins/reload 或重启服务生效")
    print("  4. 如需移除，可在管理后台执行下架操作")


if __name__ == "__main__":
    seed()
