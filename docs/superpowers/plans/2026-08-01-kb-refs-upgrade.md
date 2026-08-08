# kb_refs 结构化引用 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将知识库引用从纯文本拼入升级为结构化 `kb_refs` 字段，前端友好渲染，后端注入 LLM 上下文。

**Architecture:** 前端 `send()` 传 `kb_refs` 数组（不被拼入 `content`），后端接收后注入 LLM context 并存入消息 JSON，前端渲染时解析 `msg.kb_refs` 显示 `@标签` + hover popover。

**Tech Stack:** Vue 3 + Element-Plus (前端), FastAPI + Pydantic v2 (后端), SQLAlchemy (DB)

## Global Constraints

- 不改 DB schema（kb_refs 存 content JSON 内，与现有 `text/reasoning_content/workflow_tasks` 同级）
- 兼容旧消息（`kb_refs` 不存在时正常展示纯文本）
- `label` 优先取 `node_title`，fallback 取 `doc_name` 去扩展名
- 改动遵循 Surgical Changes：只动必要行，匹配既有风格

---

### Task 1: 后端 schema 扩展

**Files:**
- Modify: `api/schemas/schemas.py`

**Interfaces:**
- Produces: `KbRef(BaseModel)` with `label: str, content: str, kb_id: str, doc_name: str`
- Produces: `ChatMessage.kb_refs: Optional[List[KbRef]] = None`

- [ ] **Step 1: 修改 schemas.py**

```python
# api/schemas/schemas.py
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

class KbRef(BaseModel):
    """知识库引用片段"""
    label: str       # 展示名，如 "投资限制"
    content: str     # 完整引用内容
    kb_id: str       # 知识库 ID
    doc_name: str    # 来源文档名

class ChatMessage(BaseModel):
    role: str
    content: str
    kb_refs: Optional[List[KbRef]] = None

class ChatRequest(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True
    )
    messages: List[ChatMessage]
    session_id: Optional[str] = Field(None, alias="sessionId")
    agent_id: Optional[str] = Field(None, alias="agent")
    response_mode: Optional[str] = Field(None, alias="responseMode")
    deep_thinking: Optional[bool] = Field(False, alias="deepThinking")
```

- [ ] **Step 2: 验证 schema**

```bash
cd frontend && npm run build
```

Expected: 前端 build 通过（后端 schema 改动不阻塞前端编译，仅运行时影响）。

- [ ] **Step 3: Commit**

```bash
git add api/schemas/schemas.py
git commit -m "feat: add KbRef model and kb_refs field to ChatMessage"
```

---

### Task 2: 后端 context 注入 + 消息存储

**Files:**
- Modify: `api/chat/chat_routes.py:125-153`
- Modify: `api/chat/message_utils.py:28-44`

**Interfaces:**
- Consumes: `request.messages[].kb_refs` (from Task 1)
- Produces: langchain SystemMessage with kb_refs injected
- Produces: user message stored with kb_refs in content dict

- [ ] **Step 1: 修改 message_utils.py — 注入 kb_refs 到 LLM context**

```python
# api/chat/message_utils.py — 在 convert_to_langchain_messages 开头加
def _build_kb_context(messages) -> str:
    """遍历所有消息的 kb_refs，构建知识库上下文前缀。"""
    parts = []
    for msg in messages:
        refs = None
        if isinstance(msg, dict):
            refs = msg.get('kb_refs')
        elif hasattr(msg, 'kb_refs'):
            refs = msg.kb_refs
        if not refs:
            continue
        for ref in refs:
            if isinstance(ref, dict):
                parts.append(f"知识库「{ref.get('label', '')}」：\n{ref.get('content', '')}")
            else:
                parts.append(f"知识库「{ref.label}」：\n{ref.content}")
    if parts:
        return "【参考知识库】\n" + "\n\n".join(parts) + "\n---\n"
    return ""

def convert_to_langchain_messages(request_messages):
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    kb_context = _build_kb_context(request_messages)
    langchain_messages = []
    if kb_context:
        langchain_messages.append(SystemMessage(content=kb_context))
    for msg in request_messages:
        if isinstance(msg, dict):
            role = msg.get('role', 'user')
            content = msg.get('content', '')
        else:
            role = getattr(msg, 'role', 'user')
            content = getattr(msg, 'content', '')
        if role == 'user':
            langchain_messages.append(HumanMessage(content=content))
        elif role == 'assistant':
            langchain_messages.append(AIMessage(content=content))
        elif role == 'system':
            langchain_messages.append(SystemMessage(content=content))
    return langchain_messages
```

- [ ] **Step 2: 修改 chat_routes.py — 存储 kb_refs**

在 `chat_routes.py` 保存用户消息时加入 `kb_refs`。找到保存 user 消息的代码段（约 L146 前，`agent_service.chat_stream` 调用处），将 `request.messages` 传给 agent_service。但更简单的方式是在存储 user 消息时处理。

实际看代码，user 消息在 `session_routes.py` 或 `chat_routes.py` 中通过 `chat_db.save_message` 存储，传入的是 `content` 字符串。需改为传入 dict 包含 `text` 和 `kb_refs`。

找到 chat_routes.py 中保存 user 消息的位置（chat_routes.py 约 L220 附近）：

```python
# 在 chat_routes.py generate() 内，找到 save_message 调用前，添加：
# 收集所有 user message 的 kb_refs
all_kb_refs = []
for msg in request.messages:
    if msg.role == 'user' and msg.kb_refs:
        all_kb_refs.extend([r.model_dump() if hasattr(r, 'model_dump') else r for r in msg.kb_refs])

# 修改 save_message 中 content 参数:
message_content = {
    'text': final_ai_content,
    'reasoning_content': final_ai_reasoning
}
if all_kb_refs:
    message_content['kb_refs'] = all_kb_refs
```

- [ ] **Step 3: Commit**

```bash
git add api/chat/message_utils.py api/chat/chat_routes.py
git commit -m "feat: inject kb_refs into LLM context and store in message"
```

---

### Task 3: 前端 send() → kb_refs 结构化传输

**Files:**
- Modify: `frontend/src/views/ChatView.vue:220-283`

**Interfaces:**
- Consumes: `selectedRefs` (现有状态)
- Produces: `messages[].kb_refs` 字段传给 streamChat

- [ ] **Step 1: 修改 send() 函数**

```javascript
// ChatView.vue — 修改 send() 约 L220
const send = async () => {
  if (!newMessage.value.trim() || sending.value) return
  if (!currentSession.value) await newSession()

  // 构建 kb_refs（结构化字段，不再拼纯文本）
  let content = newMessage.value
  let kbRefs = null
  if (selectedRefs.value.length > 0) {
    kbRefs = selectedRefs.value.map(r => ({
      label: r.label || r.doc_name?.replace(/^.*[\\/]/, '').replace(/\.[^.]+$/, '') || '',
      content: r.content,
      kb_id: r.kb_id || selectedKb.value,
      doc_name: r.doc_name || '',
    }))
  }

  const userMsg = { role: 'user', content, kb_refs: kbRefs }
  messages.value.push(userMsg)
  newMessage.value = ''
  selectedRefs.value = []
  sending.value = true

  // AI 消息占位
  const aiIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '' })
  scrollToBottom()

  try {
    if (chatMode.value === 'blocking') {
      const result = await chatApi.send({
        session_id: currentSession.value,
        messages: [{ role: 'user', content, kb_refs: kbRefs }],
        agent: selectedAgent.value || undefined,
        responseMode: selectedMode.value || undefined,
        deepThinking: deepThinking.value,
      })
      const aiContent = typeof result === 'string' ? result : (result?.content || result?.text || result?.message || JSON.stringify(result))
      messages.value[aiIdx].content = aiContent
      if (result?.session_id) currentSession.value = result.session_id
    } else {
      await chatApi.streamChat({
        session_id: currentSession.value,
        messages: [{ role: 'user', content, kb_refs: kbRefs }],
        agent: selectedAgent.value || undefined,
        responseMode: selectedMode.value || undefined,
        deepThinking: deepThinking.value,
      }, (data) => {
        if (data.type === 'plan_review') { reviewVisible.value = true; reviewData.value = data; return }
        if (data.content) messages.value[aiIdx].content += data.content
        if (data.session_id && data.type === 'session_info') {
          currentSession.value = data.session_id
        }
        if (data.error) messages.value[aiIdx].content += '[错误] ' + data.error
        if (data.done) sending.value = false
        scrollToBottom()
      })
    }
  } catch (e) {
    if (!messages.value[aiIdx].content) messages.value[aiIdx].content = '[错误] 后端服务不可用'
    ElMessage.error('发送失败，请确保后端服务已启动')
  } finally {
    sending.value = false
    scrollToBottom()
  }
}
```

- [ ] **Step 2: 验证编译**

```bash
cmd //c "cd /d F:\workinfo\Projects\PythonProj\install_deb_refactor\frontend && npm run build"
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/ChatView.vue
git commit -m "feat: send kb_refs as structured field instead of plain text"
```

---

### Task 4: 前端 selectRef() 生成 label

**Files:**
- Modify: `frontend/src/views/ChatView.vue:355-364`

**Interfaces:**
- Consumes: `chunk.doc_name`, `chunk.node_title`, `selectedKb`
- Produces: `selectedRefs` 中每项含 `label`

- [ ] **Step 1: 修改 selectRef() 生成友好 label**

```javascript
// ChatView.vue — 修改 selectRef() 约 L355
const selectRef = (chunk) => {
  if (!currentMention.value) return
  const m = currentMention.value
  const before = newMessage.value.slice(0, m.start)
  const after = newMessage.value.slice(m.end)
  newMessage.value = before + after
  const exists = selectedRefs.value.some(r => r.content === chunk.content)
  if (!exists) {
    // 生成友好 label：优先 node_title，其次 doc_name 去路径和扩展名
    let label = ''
    if (chunk.node_title) {
      label = chunk.node_title
        .replace(/^[（(][一二三四五六七八九十\d]+[)）]\s*/, '')  // 去编号前缀如"（四）"
        .trim()
    }
    if (!label && chunk.doc_name) {
      label = chunk.doc_name
        .replace(/^.*[\\/]/, '')         // 去路径
        .replace(/\.[^.]+$/, '')         // 去扩展名
    }
    if (!label) {
      // fallback: 从 kbList 找知识库名
      const kb = kbList.value.find(k => k.kb_id === selectedKb.value)
      label = kb?.name || '知识库'
    }
    selectedRefs.value.push({ ...chunk, kb_id: selectedKb.value, label })
  }
  closeMention()
}
```

- [ ] **Step 2: 验证编译**

```bash
cmd //c "cd /d F:\workinfo\Projects\PythonProj\install_deb_refactor\frontend && npm run build"
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/ChatView.vue
git commit -m "feat: generate friendly label from node_title or doc_name"
```

---

### Task 5: 前端消息渲染 @标签

**Files:**
- Modify: `frontend/src/views/ChatView.vue:96-101`

**Interfaces:**
- Consumes: `msg.kb_refs` (数组)
- Produces: `el-tag` + `el-popover` 渲染

- [ ] **Step 1: 修改消息渲染模板**

```vue
<!-- ChatView.vue — 修改消息渲染部分约 L96-101 -->
<div class="chat-messages" ref="chatBox">
  <div v-for="msg in messages" :key="msg.id || msg.timestamp"
       class="msg-row" :class="msg.role === 'user' ? 'msg-user' : 'msg-ai'">
    <div class="msg-avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
    <div class="msg-bubble">
      <!-- kb_refs 标签行 -->
      <div v-if="msg.kb_refs?.length" class="refs-inline">
        <el-popover
          v-for="(ref, idx) in msg.kb_refs"
          :key="idx"
          trigger="hover"
          :width="420"
          placement="top"
        >
          <template #reference>
            <el-tag size="small" type="info" class="ref-tag">@{{ ref.label }}</el-tag>
          </template>
          <div class="ref-popover-content">{{ ref.content }}</div>
        </el-popover>
      </div>
      <!-- 消息正文 -->
      <div class="msg-text">{{ msg.content }}</div>
    </div>
  </div>
  <el-empty v-if="!messages.length" description="选择或新建会话开始对话" :image-size="80" />
</div>
```

- [ ] **Step 2: 添加样式**

在 ChatView.vue 的 `<style scoped>` 末尾加：

```css
.refs-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}
.ref-tag {
  cursor: pointer;
}
.ref-popover-content {
  max-height: 300px;
  overflow-y: auto;
  white-space: pre-wrap;
  line-height: 1.7;
  font-size: 13px;
}
```

- [ ] **Step 3: 验证编译**

```bash
cmd //c "cd /d F:\workinfo\Projects\PythonProj\install_deb_refactor\frontend && npm run build"
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/ChatView.vue
git commit -m "feat: render kb_refs as @label tags with hover popover"
```

---

### Task 6: 端到端验证

**Files:**
- 无新建文件

- [ ] **Step 1: 重启后端服务器**

```bash
# 杀掉旧进程，启动新服务器
"D:/ProgramData/miniconda3/envs/install_deb_refactor/python.exe" server.py
```

- [ ] **Step 2: 前端联调测试**

```bash
# 启动前端 dev server (另一个终端)
cmd //c "cd /d F:\workinfo\Projects\PythonProj\install_deb_refactor\frontend && npm run dev"
```

手动测试流程：
1. 打开对话页 → 选择知识库 → 输入 `@投资` → 选中片段
2. badge 显示 `@投资限制`（不再是路径）
3. 输入消息 → 发送
4. 消息气泡显示 `@投资限制` 标签
5. hover 标签 → popover 弹出完整引用内容
6. 消息正文不包含 `【引用知识库片段】` 纯文本

- [ ] **Step 3: 检查 LLM 是否收到 context**

查看服务器日志，确认 system prompt 包含：
```
【参考知识库】
知识库「投资限制」：
（四）投资限制...
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: e2e verification of kb_refs structured references"
```
