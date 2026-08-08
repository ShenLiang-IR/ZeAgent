"""批量发布内置 skills 到插件市场。

运行：python scripts/migration/seed_builtin_skills.py（项目根执行）

幂等设计：已存在的同名插件会跳过。
"""
import sys
from pathlib import Path

# 项目根 = 本脚本上三级目录（脚本位于 scripts/migration/ 下）
agent_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(agent_dir))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ── 内置 skills 清单 ──
BUILTIN_SKILLS = [
    {
        "name": "http-request",
        "display_name": "HTTP 请求",
        "description": "发送 HTTP 请求（GET/POST/PUT/DELETE），支持自定义 headers、body、超时。类似 Dify 的 HTTP 节点。",
        "category": "网络请求",
        "tags": ["http", "api", "网络"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "JSON 格式响应，包含 status_code、headers、body",
        },
    },
    {
        "name": "code-runner",
        "display_name": "代码执行器",
        "description": "执行 Python 代码片段并返回输出。支持 stdin 输入，限制执行时间。适用于 Agent 动态生成并运行代码。",
        "category": "开发工具",
        "tags": ["python", "代码", "执行"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "JSON 格式结果，包含 stdout、stderr、exit_code、duration_ms",
        },
    },
    {
        "name": "base64-tool",
        "display_name": "Base64 编解码",
        "description": "Base64 编码/解码工具，支持文本和文件。编码时输出 Base64 字符串，解码时还原原始内容。",
        "category": "编码转换",
        "tags": ["base64", "编码", "解码"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "Base64 编码/解码结果",
        },
    },
    {
        "name": "regex-tester",
        "display_name": "正则表达式测试器",
        "description": "正则表达式测试工具。匹配、提取、替换文本中的模式，返回 JSON 结果。支持分组捕获。",
        "category": "文本处理",
        "tags": ["regex", "正则", "文本"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "JSON 格式结果，包含匹配结果、分组、位置",
        },
    },
    {
        "name": "csv-tool",
        "display_name": "CSV 数据处理",
        "description": "CSV 文件处理工具。读取、筛选、转换 CSV 数据为 JSON，支持列选择和条件过滤。",
        "category": "数据处理",
        "tags": ["csv", "数据", "表格"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "JSON 格式的 CSV 数据，包含 rows 和 count",
        },
    },
    {
        "name": "datetime-tool",
        "display_name": "日期时间工具",
        "description": "日期时间工具。获取当前时间、时间格式转换、时间差计算。支持多种时区。",
        "category": "实用工具",
        "tags": ["datetime", "时间", "日期"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "JSON 格式的日期时间信息",
        },
    },
    {
        "name": "hash-tool",
        "display_name": "哈希计算工具",
        "description": "哈希计算工具。计算文本或文件的 MD5/SHA1/SHA256/SHA512 哈希值。",
        "category": "编码转换",
        "tags": ["hash", "md5", "sha256", "加密"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "哈希值和输入信息",
        },
    },
    {
        "name": "uuid-generator",
        "display_name": "UUID 生成器",
        "description": "UUID 生成工具。生成 UUID v4/v5，支持批量生成和格式化输出。",
        "category": "实用工具",
        "tags": ["uuid", "唯一ID", "生成"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "UUID 列表",
        },
    },
    {
        "name": "text-diff",
        "display_name": "文本差异比较",
        "description": "文本差异比较工具。比较两段文本的差异，输出行级别的增删改。类似 git diff 的效果。",
        "category": "文本处理",
        "tags": ["diff", "文本", "比较"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "差异结果，包含 diff 列表和统计",
        },
    },
    {
        "name": "markdown-to-html",
        "display_name": "Markdown 转 HTML",
        "description": "将 Markdown 转换为 HTML。支持标题、列表、代码块、表格、链接、图片等常用语法。",
        "category": "内容处理",
        "tags": ["markdown", "html", "转换"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "HTML 格式内容",
        },
    },
    # ── 办公类 ──
    {
        "name": "db-query",
        "display_name": "数据库查询",
        "description": "执行 SQL 查询并返回 JSON 结果。支持 MySQL/PostgreSQL，只读模式安全限制。",
        "category": "办公",
        "tags": ["sql", "数据库", "查询"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "JSON 格式查询结果，包含 columns、rows、count",
        },
    },
    {
        "name": "ppt-generator",
        "display_name": "PPT 生成器",
        "description": "根据 JSON 数据生成 PowerPoint 演示文稿。支持标题页、内容页、要点列表。",
        "category": "办公",
        "tags": ["ppt", "演示", "office"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "生成的 .pptx 文件路径",
        },
    },
    {
        "name": "excel-tool",
        "display_name": "Excel 处理",
        "description": "读取/创建/编辑 .xlsx 文件，支持多工作表。读取输出 JSON，写入接受 JSON 数据。",
        "category": "办公",
        "tags": ["excel", "xlsx", "表格"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "读取: JSON 数据; 写入: 文件路径",
        },
    },
    {
        "name": "email-sender",
        "display_name": "邮件发送",
        "description": "通过 SMTP 发送邮件，支持 HTML 内容、附件、多收件人。适用于通知、报告推送场景。",
        "category": "办公",
        "tags": ["email", "smtp", "通知"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "发送状态和收件人数",
        },
    },
    {
        "name": "doc-converter",
        "display_name": "文档格式转换",
        "description": "文档格式转换工具。支持 CSV↔JSON、Markdown→HTML 等常见格式互转。",
        "category": "办公",
        "tags": ["格式转换", "csv", "json", "markdown"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "转换后的内容或文件路径",
        },
    },
    {
        "name": "pdf-extractor",
        "display_name": "PDF 文本提取",
        "description": "从 PDF 文件中提取文本内容，支持多页、保留段落结构。输出纯文本或 JSON。",
        "category": "办公",
        "tags": ["pdf", "文本提取", "文档"],
        "author": "system",
        "version": "1.0",
        "plugin_type": "tool",
        "manifest": {
            "return_description": "提取的文本内容或按页分段的 JSON",
        },
    },
]


def main():
    from services.plugin_marketplace_service import PluginMarketplaceService

    svc = PluginMarketplaceService()
    published = 0
    skipped = 0

    for skill in BUILTIN_SKILLS:
        name = skill["name"]
        # 检查是否已存在
        existing = svc.plugin_repo.get_by_name(name)
        if existing:
            print(f"  跳过（已存在）: {name}")
            skipped += 1
            continue

        try:
            svc.publish_plugin(
                name=name,
                display_name=skill["display_name"],
                plugin_type=skill["plugin_type"],
                description=skill["description"],
                category=skill["category"],
                tags=skill["tags"],
                author=skill["author"],
                version=skill["version"],
                manifest=skill["manifest"],
                status="1",
            )
            print(f"  发布成功: {name}")
            published += 1
        except Exception as e:
            print(f"  发布失败: {name} — {e}")

    print(f"\n完成：发布 {published} 个，跳过 {skipped} 个，总计 {len(BUILTIN_SKILLS)} 个内置 skills")


if __name__ == "__main__":
    print("=" * 60)
    print("内置 Skills 批量注册到插件市场")
    print("=" * 60)
    main()
    print("=" * 60)
