# ChatView 引用知识库片段（方案 A MVP）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 ChatView 对话页引用知识库片段功能（方案 A MVP，前端拼入 message，后端零改动）。

**Architecture:** ChatView.vue 新增知识库下拉 + 检索 Dialog + 引用 badge 列表 + send() 拼入逻辑；复用现有 ragApi.retrieve / ragApi.kbList；后端 /api/chat/stream 零改动。

**Tech Stack:** Vue 3 + Element Plus + Vite（前端）；现有 FastAPI + RAGSystem（后端，本次不动）。

## Global Constraints

- 前端无单测框架（refactor.md 10.5 已说明），测试用 vite build（编译验证）+ playwright（行为验证）替代 TDD 单测
- 后端零改动，现有 38 个 RAG 测试不动
- 复用现有 ragApi（retrieve/kbList 已实现并验证）
- 设计文档：docs/superpowers/specs/2026-07-18-chat-mention-rag-design.md
- Python 解释器：D:/ProgramData/miniconda3/envs/install_deb_refactor/python.exe
- 前端目录：frontend/，构建命令 npm run build
- 后端启动：python -m uvicorn server:app --port 8072（测试时需要，用于 ragApi 调用）

## File Structure

- **Modify:** `frontend/src/views/ChatView.vue`（所有改动集中此文件：知识库下拉 + 检索 Dialog + badge 列表 + send 拼入）
- **不新建文件**（YAGNI，复用现有 ragApi + Element Plus 组件）
- **不动后端**（方案 A 零改动）

---

## Task 1: 加载知识库列表 + 下拉 UI

**Files:**
- Modify: `frontend/src/views/ChatView.vue`（import 加 ragApi + 状态 kbList/selectedKb + loadKbList + onMounted 调用 + 模板下拉）

**Interfaces:**
- Consumes: `ragApi.kbList()`（已实现，返回 `{list: [{kb_id, name, persist_directory, ...}]}`）
- Produces: `kbList`（知识库数组）、`selectedKb`（选中 kb_id 字符串），供 Task 2 检索 Dialog 使用

- [ ] **Step 1: 修改 import 加 ragApi**

`frontend/src/views/ChatView.vue` 现有第 65 行：
```js
import { chatApi, modeApi } from '../api'
```
改为：
```js
import { chatApi, modeApi, ragApi } from '../api'
```

- [ ] **Step 2: 添加 kbList/selectedKb + 检索参数状态**

在 `frontend/src/views/ChatView.vue` 的 `const deepThinking = ref(false)` 行后添加：
```js
const kbList = ref([])
const selectedKb = ref('')
const retrieveTopK = ref(5)
const retrieveStrategy = ref('hybrid')
```

- [ ] **Step 3: 添加 loadKbList 方法**

在 `frontend/src/views/ChatView.vue` 的 `loadSubagents` 方法后添加：
```js
const loadKbList = async () => {
  try {
    const res = await ragApi.kbList()
    kbList.value = res.list || []
  } catch (e) {
    console.log('KbList load failed (RAG API may be offline)')
  }
}
```

- [ ] **Step 4: onMounted 调用 loadKbList**

在 `frontend/src/views/ChatView.vue` 的 `onMounted` 内（已有 loadSessions/loadSubagents/loadModes）添加 `loadKbList()`：
```js
onMounted(() => {
  loadSessions()
  loadSubagents()
  loadModes()
  loadKbList()
  // ... 原有 agent/mode 预选逻辑
})
```

- [ ] **Step 5: 模板加知识库下拉 + K/策略紧凑控件**

在 `frontend/src/views/ChatView.vue` 模板中，agent 下拉（`selectedAgent` 的 el-select）后添加：
```html
<el-select v-model="selectedKb" placeholder="选择知识库（@ 引用目标）" clearable filterable style="width: 100%; margin-bottom: 10px;">
  <el-option v-for="kb in kbList" :key="kb.kb_id" :label="kb.name" :value="kb.kb_id" />
</el-select>
<div style="display: flex; gap: 8px; margin-bottom: 10px;">
  <el-input-number v-model="retrieveTopK" :min="1" :max="20" size="small" style="width: 110px;" />
  <el-select v-model="retrieveStrategy" size="small" style="flex: 1;">
    <el-option label="混合" value="hybrid" />
    <el-option label="语义" value="semantic" />
    <el-option label="关键词" value="keyword" />
  </el-select>
</div>
```

- [ ] **Step 6: vite build 验证编译**

Run: `npm run build`（在 frontend/ 目录）
Expected: `✓ built in <时间>` 无错误

- [ ] **Step 7: 启动后端 + 前端，playwright 验证下拉显示**

启动后端：`D:/ProgramData/miniconda3/envs/install_deb_refactor/python.exe -m uvicorn server:app --port 8072`
启动前端：`npm run dev`（在 frontend/ 目录）
playwright 导航到 `http://localhost:3000/chat`，snapshot 验证左侧会话卡片有"选择知识库"下拉，且含 kb_contact（合同文本）选项。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/ChatView.vue
git commit -m "feat(chat): add knowledge base dropdown in ChatView"
```

---

## Task 2: @ 触发检索 + 候选浮层（方案 C 核心）

**Files:**
- Modify: `frontend/src/views/ChatView.vue`（@ 检测逻辑 + 候选浮层 + doRetrieve/selectRef）

**Interfaces:**
- Consumes: `ragApi.retrieve({query, kb_id, top_k, strategy})`（返回 `{chunks, total_chunks, latency_ms}`）；Task 1 的 `selectedKb/retrieveTopK/retrieveStrategy`
- Produces: `mentionResults`（候选片段）、`selectRef(chunk)`（供 Task 3 badge 用）

- [ ] **Step 1: 添加 @ 触发状态**

在 `retrieveStrategy` 状态后添加：
```js
const mentionVisible = ref(false)
const mentionQuery = ref('')
const mentionResults = ref([])
const mentionLoading = ref(false)
const mentionActiveIndex = ref(0)
const currentMention = ref(null)
let mentionTimer = null
```

- [ ] **Step 2: 添加 detectMention 方法（@ 检测）**

在 `loadKbList` 后添加。检测光标前最近的 @，提取 @ 到空格/换行/光标的文本作为查询词：
```js
const detectMention = (text, cursorPos) => {
  const before = text.slice(0, cursorPos)
  const atIdx = before.lastIndexOf('@')
  if (atIdx === -1) return null
  const afterAt = before.slice(atIdx + 1)
  if (afterAt.includes(' ') || afterAt.includes('\n')) return null
  if (afterAt.length === 0) return { start: atIdx, query: '', end: cursorPos }
  return { start: atIdx, query: afterAt, end: cursorPos }
}
```

- [ ] **Step 3: 添加 onInputChange 方法（textarea input 处理）**

在 `detectMention` 后添加。监听 textarea input，检测 @，debounce 触发检索：
```js
const onInputChange = (e) => {
  const text = e.target.value
  const cursorPos = e.target.selectionStart
  const mention = detectMention(text, cursorPos)
  if (!mention) {
    mentionVisible.value = false
    currentMention.value = null
    return
  }
  currentMention.value = mention
  mentionQuery.value = mention.query
  if (mentionTimer) clearTimeout(mentionTimer)
  if (mention.query.length === 0) {
    mentionVisible.value = true
    mentionResults.value = []
    return
  }
  mentionTimer = setTimeout(() => doRetrieve(mention.query), 300)
}
```

- [ ] **Step 4: 添加 doRetrieve + selectRef + closeMention 方法**

在 `onInputChange` 后添加。doRetrieve 调 ragApi.retrieve 填候选；selectRef 选中后清除 textarea 里 @query 文本 + 加入 selectedRefs；closeMention 关闭浮层：
```js
const doRetrieve = async (query) => {
  if (!query.trim() || !selectedKb.value) return
  mentionLoading.value = true
  try {
    const res = await ragApi.retrieve({
      query, kb_id: selectedKb.value,
      top_k: retrieveTopK.value, strategy: retrieveStrategy.value,
    })
    mentionResults.value = res.chunks || []
    mentionActiveIndex.value = 0
    mentionVisible.value = true
  } catch (e) {
    ElMessage.error('检索失败: ' + (e.message || ''))
  } finally {
    mentionLoading.value = false
  }
}

const selectRef = (chunk) => {
  if (!currentMention.value) return
  // 从 textarea 移除 @query 文本
  const m = currentMention.value
  const before = newMessage.value.slice(0, m.start)
  const after = newMessage.value.slice(m.end)
  newMessage.value = before + after
  // 加入 selectedRefs（去重）
  const exists = selectedRefs.value.some(r => r.content === chunk.content)
  if (!exists) selectedRefs.value.push({ ...chunk, kb_id: selectedKb.value })
  closeMention()
}

const closeMention = () => {
  mentionVisible.value = false
  currentMention.value = null
  mentionResults.value = []
}
```

- [ ] **Step 5: textarea 绑定 input 事件 + 候选浮层**

修改 `frontend/src/views/ChatView.vue` 的消息输入框（现有第 19 行 el-input），加 `@input="onInputChange"`。在输入框下方加候选浮层（absolute 定位）：
```html
<el-input v-model="newMessage" placeholder="输入消息... 输入 @ 触发知识库引用" type="textarea" :rows="3"
  style="margin-bottom: 10px;" @keydown.enter.ctrl="send" @input="onInputChange" />
<!-- @ 候选浮层 -->
<div v-if="mentionVisible" style="position: relative;">
  <div style="position: absolute; left: 0; right: 0; top: 0; z-index: 999;
       background: #fff; border: 1px solid #dcdfe6; border-radius: 4px;
       box-shadow: 0 2px 12px rgba(0,0,0,0.1); max-height: 280px; overflow-y: auto;">
    <div v-if="mentionLoading" style="padding: 12px; color: #999;">检索中...</div>
    <div v-else-if="mentionResults.length === 0" style="padding: 12px; color: #999;">
      {{ mentionQuery ? '无相关片段' : '输入查询词...' }}
    </div>
    <div v-else>
      <div v-for="(chunk, idx) in mentionResults" :key="idx"
           @click="selectRef(chunk)"
           :style="{ padding: '8px 12px', cursor: 'pointer', borderBottom: '1px solid #f0f0f0',
                     background: idx === mentionActiveIndex ? '#f5f7fa' : '' }">
        <div style="font-size: 12px; color: #999;">{{ chunk.doc_name }}</div>
        <div style="font-size: 13px; color: #333;">{{ chunk.content.slice(0, 80) }}</div>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 6: vite build 验证编译**

Run: `npm run build`（在 frontend/ 目录）
Expected: `✓ built` 无错误

- [ ] **Step 7: playwright 验证 @ 触发检索**

启动后端 + 前端，playwright 导航 `/chat` → 选知识库 kb_contact → 在输入框输入 `@合同金额` → 等待 1s → snapshot 验证浮层显示候选片段（doc_name + content 预览）。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/ChatView.vue
git commit -m "feat(chat): @ mention triggers RAG retrieve with candidate popover"
```

---

## Task 3: 引用 badge 列表 + selectRef 选中

**Files:**
- Modify: `frontend/src/views/ChatView.vue`（selectedRefs 状态 + removeRef 方法 + badge 列表模板）

**Interfaces:**
- Consumes: Task 2 的 `selectRef(chunk)` 填充的 `selectedRefs`
- Produces: `selectedRefs`（已选片段数组），供 Task 4 send() 拼入

- [ ] **Step 1: 添加 selectedRefs 状态 + removeRef 方法**

在 `currentMention` 状态后添加：
```js
const selectedRefs = ref([])

const removeRef = (index) => {
  selectedRefs.value.splice(index, 1)
}
```

- [ ] **Step 2: 模板加 badge 列表（输入框下方，发送按钮上方）**

在 textarea 候选浮层后、发送按钮前添加：
```html
<div v-if="selectedRefs.length > 0" style="margin-bottom: 10px; display: flex; flex-wrap: wrap; gap: 6px;">
  <el-popover v-for="(ref, idx) in selectedRefs" :key="idx" placement="top" :width="400" trigger="click">
    <template #reference>
      <el-tag closable @close="removeRef(idx)" style="cursor: pointer;">
        {{ ref.doc_name }}
      </el-tag>
    </template>
    <div style="max-height: 300px; overflow-y: auto; white-space: pre-wrap; line-height: 1.6;">
      {{ ref.content }}
    </div>
  </el-popover>
</div>
```

- [ ] **Step 3: vite build 验证**

Run: `npm run build`
Expected: `✓ built` 无错误

- [ ] **Step 4: playwright 验证 badge 展示 + 删除**

承接 Task 2 Step 7：输入 `@合同金额` → 浮层出现 → 点击候选项 → 验证 badge 出现（doc_name）→ 点击 badge X → badge 消失 → 点击 badge → popover 显示片段全文。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/ChatView.vue
git commit -m "feat(chat): show selected references as badges with popover"
```

---

## Task 4: send() 方案 A 拼入 message + 清空引用

**Files:**
- Modify: `frontend/src/views/ChatView.vue`（send() 改造）

**Interfaces:**
- Consumes: Task 3 的 `selectedRefs`
- Produces: 拼入引用的 user message（方案 A）

- [ ] **Step 1: 改造 send() 方法**

在 `send()` 开头（现有 `const userMsg` 前）添加引用拼入。原 `const msg = newMessage.value` 改为 `const msg = content`：
```js
const send = async () => {
  if (!newMessage.value.trim() || sending.value) return
  if (!currentSession.value) newSession()

  let content = newMessage.value
  if (selectedRefs.value.length > 0) {
    const refsText = selectedRefs.value.map(r =>
      `来源: ${r.doc_name}\n${r.content}`
    ).join('\n\n')
    content = `【引用知识库片段】\n${refsText}\n\n---\n用户问题：${content}`
  }

  const userMsg = { role: 'user', content }
  messages.value.push(userMsg)
  const msg = content
  newMessage.value = ''
  selectedRefs.value = []
  sending.value = true
  const aiIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '' })
  scrollToBottom()

  try {
    if (chatMode.value === 'blocking') {
      const result = await chatApi.send({
        session_id: currentSession.value,
        messages: [{ role: 'user', content: msg }],
        agent: selectedAgent.value || undefined,
        responseMode: selectedMode.value || undefined,
        deepThinking: deepThinking.value,
      })
      const aiContent = typeof result === 'string' ? result : (result?.content || result?.message || JSON.stringify(result))
      messages.value[aiIdx].content = aiContent
      if (result?.session_id) currentSession.value = result.session_id
    } else {
      await chatApi.streamChat({
        session_id: currentSession.value,
        messages: [{ role: 'user', content: msg }],
        agent: selectedAgent.value || undefined,
        responseMode: selectedMode.value || undefined,
        deepThinking: deepThinking.value,
      }, (data) => {
        if (data.type === 'plan_review') { reviewVisible.value = true; reviewData.value = data; return }
        if (data.content) messages.value[aiIdx].content += data.content
        if (data.session_id && data.type === 'session_info') currentSession.value = data.session_id
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

- [ ] **Step 2: vite build 验证**

Run: `npm run build`（在 frontend/ 目录）
Expected: `✓ built` 无错误

- [ ] **Step 3: 端到端验证**

启动后端 + 前端 + ollama。playwright：导航 `/chat` → 新建会话 → 选 kb_contact → 输入 `@合同金额` → 选片段 → 输入"金额是多少" → 发送 → 验证 AI 回复含金额信息 → 验证 badge 清空。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/ChatView.vue
git commit -m "feat(chat): inject selected refs into user message (Plan A)"
```

---

## Self-Review

**Spec coverage:** spec 二（@ 触发+badge）→ Task 2+3 ✓；三（方案 A 拼入）→ Task 4 ✓；五（组件改造）→ Task 1-4 ✓；六（数据流）→ Task 1→2→3→4 ✓；七（错误处理）→ Task 1 下拉禁用 + Task 2 浮层提示 ✓；九（边界）→ 多引用/清空/去重 ✓

**Placeholder scan:** 无 TBD/TODO，所有 step 含实际代码 ✓

**Type consistency:** selectedRefs 结构 {kb_id, doc_name, content} 全链路一致 ✓；mentionResults/chunks 结构 {content, doc_name} 一致 ✓

## Execution Handoff

计划已保存到 `docs/superpowers/plans/2026-07-18-chat-mention-rag.md`。两种执行方式：

**1. Subagent-Driven（推荐）** - 每个 Task dispatch 新 subagent，任务间审查，快速迭代

**2. Inline Execution** - 本会话内执行，批量 + 检查点

选哪种？
