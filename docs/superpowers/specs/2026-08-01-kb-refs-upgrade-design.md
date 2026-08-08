# ChatView 知识库引用展示升级 设计文档

创建时间：2026-08-01
状态：设计待审查
关联：2026-07-18-chat-mention-rag-design.md（原始 @ 引用设计，方案 A→B 升级）

## 一、背景

### 现状（方案 A 已落地）
- ChatView `@` 检索知识库 → 选中片段 → badge 展示 → 发送时拼入纯文本
- 格式：`【引用知识库片段】\n来源: C:\Users\...\tmpc814zv62.md\n{content}\n---\n用户问题：{text}`
- 消息渲染：`{{ msg.content }}` 纯文本，无特殊格式

### 问题
1. `doc_name` 展示原始文件路径（如 `C:\Users\Administrator\AppData\Local\Temp\tmpc814zv62.md`），不可读
2. 引用内容混入消息文本，消息列表臃肿，无交互
3. 多轮对话中引用重复传输，token 浪费

### 目标
升级到方案 B：`kb_refs` 结构化字段 + 前端友好标签渲染。

---

## 二、核心设计

### 2.1 数据模型

**ChatMessage schema 扩展**：

```python
# api/schemas/schemas.py
class ChatMessage(BaseModel):
    role: str
    content: str
    kb_refs: Optional[list[KbRef]] = None  # ← 新增

class KbRef(BaseModel):
    label: str        # 展示名，如 "投资限制"
    content: str      # 完整引用内容
    kb_id: str        # 知识库 ID
    doc_name: str     # 来源文档名
```

**前端类型**：
```typescript
interface KbRef {
  label: string   // 展示用短名
  content: string  // 完整内容（hover 弹出）
  kb_id: string
  doc_name: string
}
```

### 2.2 前端渲染效果

```
┌──────────────────────────────────────────┐
│ 我                                       │
│ ┌─────────┐ ┌─────────────┐              │
│ │@投资限制 │ │@风险评估指标 │  ← hover 弹窗│
│ └─────────┘ └─────────────┘              │
│                                          │
│ 访问 https://api.github.com/zen，        │
│ 将结果与引用的投资限制进行比较...          │
└──────────────────────────────────────────┘
```

### 2.3 LLM 上下文注入（后端）

后端接收 `kb_refs` 后，在构建 LLM prompt 时注入 system message 前缀（不展示在前端）：

```
【参考知识库】
知识库「投资限制」：
（四）投资限制
本资产管理计划财产的投资组合应遵循以下限制：
1）投资于股票等权益类资产的占计划资产总值的比例为0-100%。
...
---
用户问题：访问 https://api.github.com/zen...
```

### 2.4 label 来源

`label` 由前端在 `selectRef` 时生成，优先级：
1. `node_title`（如 "（四）投资限制"）— 去掉编号括号，取核心词
2. `doc_name` 去掉路径和扩展名（如 `tmpc814zv62.md` → `tmpc814zv62`）
3. `kb_name`（从 kbList 查得知识库名）

前端 `selectRef(chunk)` 中自动生成 label，用户可在 badge 上编辑。

---

## 三、改动清单

### 3.1 前端改动

| 文件 | 改动 |
|---|---|
| `src/views/ChatView.vue` | `send()`：selectedRefs → `kb_refs` 字段，不再拼纯文本 |
| | 消息渲染（L100）：`msg-bubble` 解析 `msg.kb_refs`，渲染 `@标签` + el-popover |
| | `selectRef()`：生成 `label`（node_title 优先） |
| `src/api/index.js` | `chatApi.send()` / `sseFetch()`：透传 `kb_refs` |

**消息渲染伪代码**：
```vue
<div class="msg-bubble">
  <div v-if="msg.kb_refs?.length" class="refs-inline">
    <el-popover v-for="ref in msg.kb_refs" trigger="hover" :width="400">
      <template #reference>
        <el-tag size="small" type="info">@{{ ref.label }}</el-tag>
      </template>
      <div style="max-height:300px;overflow-y:auto;white-space:pre-wrap">
        {{ ref.content }}
      </div>
    </el-popover>
  </div>
  <div class="msg-text">{{ msg.content }}</div>
</div>
```

### 3.2 后端改动

| 文件 | 改动 |
|---|---|
| `api/schemas/schemas.py` | 新增 `KbRef` model，`ChatMessage` 加 `kb_refs` 字段 |
| `api/chat/chat_routes.py` | `chat_stream()` 提取 `request.messages[].kb_refs`，拼入 system message |
| `api/chat/message_utils.py` | `convert_to_langchain_messages()` 处理 `kb_refs`，注入 context |
| DB 消息存储 | `save_message()` 存储 `kb_refs`；`get_messages()` 返回 `kb_refs` |

**context 注入位置**（`chat_routes.py` 约 L100 后，`langchain_messages` 构建前）：

```python
# 提取 kb_refs 构建 context prefix
kb_context = ""
for msg in request.messages:
    if msg.kb_refs:
        for ref in msg.kb_refs:
            kb_context += f"\n知识库「{ref.label}」：\n{ref.content}\n"
if kb_context:
    kb_context = f"【参考知识库】{kb_context}\n---\n"
    # 注入到 system message 最前面，或拼入第一条 user message
```

---

## 四、兼容性

| 场景 | 处理 |
|---|---|
| 旧消息（无 kb_refs） | 正常展示，无标签 |
| 旧前端 + 新后端 | 后端 `kb_refs=None` 防御，不崩溃 |
| 新前端 + 旧后端 | `kb_refs` 字段后端忽略，前端不展示标签 |
| 多片段引用 | `kb_refs` 数组支持多个 |

---

## 五、测试策略

### 前端
- `npm run build` 验证编译
- 手动测试：选 KB → @ 检索 → 选中片段 → 发送 → 验证消息气泡显示 `@标签`
- hover 标签 → 验证 popover 弹出完整内容

### 后端
- 单元测试：`ChatMessage` schema 含 `kb_refs` 的反序列化
- 集成测试：`chat_stream` 传入含 `kb_refs` 的消息，验证 LLM context 包含知识库内容
- 兼容性：不含 `kb_refs` 的消息正常处理

---

## 六、非目标（YAGNI）

- 不修改 `@` 检索逻辑（已实现，不涉及本次改动）
- 不修改 badge 列表 UI（输入框下方 badge 保持不变）
- 不做 label 的持久化编辑存储（发送后不变）
- 不改 DB schema（kb_refs 存在 message content JSON 中，无需新列）
