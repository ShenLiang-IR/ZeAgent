"""初始化记忆提取 prompt 模板到 tb_prompt_template（提示词管理可编辑）。

跑一次后，前端 系统管理 > 提示词管理 可见 name=memory_extract_prompt 的模板，
可直接编辑 content 覆盖代码默认值（支持 {{user_input}} / {{assistant_response}} 变量）。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.prompt_template import PromptTemplate
from sqlalchemy import select

# 模板清单：name -> (template_id, content, variables, description)
TEMPLATES = [
    {
        "name": "memory_extract_prompt",
        "template_id": "PT_memory_extract",
        "version": "1.1.0",
        "content": """从以下对话提取结构化记忆，按类别输出 JSON 数组（无则输出 []）：
用户: {{user_input}}
助手: {{assistant_response}}

类别：preference(用户偏好) / fact(客观事实) / relation(实体关系) / event(事件/任务)
每项格式: {"type":"类别","content":"内容","importance":0.0-1.0}
规则：
- preference：用户对回复方式/内容风格的【指令性要求】或【反复表达的倾向】，不论具体措辞
  （如"只要代码不要解释""简洁点""用中文回复""别废话直接给结果"），提取为 preference，importance 0.7~0.8
  ；用户明确表达稳定喜好（如"我喜欢吃辣""我偏好低风险"）importance>=0.8
- 重要：区分"要求 AI 如何回复"(preference) vs "请求 AI 做什么"(event)。
  "用 python 写递归"是 event（请求做事），不是 preference（除非用户明确说"我喜欢/偏好 python"）
- event 记录用户做过/请求做的事 + 关键内容摘要（如"写了水仙花数程序：打印100-999水仙花数"），importance>=0.8（持久化，便于后续跨会话召回具体内容）
- fact 记录客观信息/知识点（如"李白是唐朝诗人"），importance>=0.8（持久化）
- relation 涉及两个实体/人物关系时提取（如"李白-杜甫-同时代诗人/好友"），importance>=0.8（持久化）
- event 按需提取
只输出 JSON 数组，不要解释。""",
        "variables": '["user_input", "assistant_response"]',
        "description": "记忆提取：从对话提取 preference/fact/relation/event 结构化记忆。preference 规则通用化（判断指令性/倾向信号，非穷举关键词）。支持 {{user_input}} {{assistant_response}} 变量占位。",
    },
    {
        "name": "preference_summary_prompt",
        "template_id": "PT_pref_summary",
        "content": """从以下用户历史会话总结用户的偏好画像，输出 JSON 数组（无则输出 []）：
{{conversation_history}}

每项格式: {"type":"preference","content":"偏好内容","importance":0.0-1.0}
规则：
- 从用户多次提及/反复选择/明确表达中总结稳定偏好（如"偏好辣食""倾向低风险""常用 python"）
- 隐式偏好（从行为推断）importance 0.8，显式偏好（用户明说）importance 0.9
- 所有偏好 importance>=0.8（存长期记忆，跨会话个性化）
- 只总结有证据的偏好，不要编造
- 每个偏好一条，content 简洁（如"偏好辣食""倾向低风险投资"）
只输出 JSON 数组。""",
        "variables": '["conversation_history"]',
        "description": "偏好总结 cron：从用户历史会话总结偏好画像存长期记忆（自动捕获隐式偏好，单轮提取漏掉的）。支持 {{conversation_history}} 变量。",
    },
]


def seed():
    with get_config_session() as session:
        for t in TEMPLATES:
            existing = session.scalar(
                select(PromptTemplate).where(PromptTemplate.name == t["name"])
            )
            new_version = t.get("version", "1.0.0")
            if existing:
                # 版本不同则更新（content/description/version），让 seed 能升级现有模板
                if existing.version != new_version:
                    existing.content = t["content"]
                    existing.description = t["description"]
                    existing.version = new_version
                    session.commit()
                    print(f"模板 {t['name']} 已更新到 v{new_version} (id={existing.pr_key_id})")
                else:
                    print(f"模板 {t['name']} 已存在 v={existing.version} (id={existing.pr_key_id})，跳过")
                continue
            tpl = PromptTemplate(
                template_id=t["template_id"],
                name=t["name"],
                content=t["content"],
                variables=t["variables"],
                version=new_version,
                description=t["description"],
                workspace_id=None,
                enabled="1",
            )
            session.add(tpl)
            session.commit()
            print(f"已插入 {t['name']} 模板 (id={tpl.pr_key_id})")
        print("现在可在 前端 系统管理 > 提示词管理 编辑 content 覆盖默认值。")


if __name__ == "__main__":
    seed()
