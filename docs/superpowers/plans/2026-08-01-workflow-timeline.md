# AI 执行步骤时间轴 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** ChatView AI 回复气泡内嵌时间轴，PLANNING 多任务模式下实时展示步骤名称+状态，hover 看详情。

**Architecture:** SSE 回调中收集 `execution_event/plan`、`task_*`、`execution_event/tool_start` 事件，更新 AI 消息的 `workflowSteps` 数组。模板渲染 `el-timeline` 组件。

**Tech Stack:** Vue 3 + Element-Plus（`el-timeline`、`el-popover`）

## Global Constraints

- 仅改 `frontend/src/views/ChatView.vue`
- 后端零改动
- 仅 `tasks_count > 1` 时显示时间轴
- 不改现有 CSS 结构

---

### Task 1: SSE 回调扩展 — 收集 workflow 事件

**Files:**
- Modify: `frontend/src/views/ChatView.vue:288-297`

- [ ] **Step 1: 扩展 SSE 回调处理 task 事件**

在流式 SSE 回调（约 L288）中，`data.content` 处理之后增加：

```javascript
// 在 streamChat 回调中 data.content 处理之后、data.error 之前加入：
// ——— workflow 时间轴事件 ———
if (data.execution_event) {
  const ev = data.execution_event
  const etype = ev.event_type
  const edata = ev.data || {}

  // plan 事件：初始化 workflowSteps
  if (etype === 'plan') {
    const tasks = edata.workflow?.tasks
    if (tasks?.length > 1) {
      messages.value[aiIdx].workflowSteps = tasks.map(t => ({
        id: t.id,
        name: t.description || t.agent || t.id,
        agent: t.agent || '',
        status: 'pending',
        toolCalls: [],
      }))
    }
  }

  // tool_start：追加到对应 task 的 toolCalls
  if (etype === 'tool_start') {
    const steps = messages.value[aiIdx].workflowSteps
    if (steps) {
      // 找到当前 running 的 task（或最后一个）
      const target = steps.find(s => s.status === 'running') || steps[steps.length - 1]
      if (target) {
        if (!target.toolCalls) target.toolCalls = []
        target.toolCalls.push({
          name: edata.tool_name || '',
          input: JSON.stringify(edata.input || {}).slice(0, 200),
        })
      }
    }
  }
}

// task_started / task_completed / task_failed 事件
if (data.event?.startsWith('task_')) {
  const steps = messages.value[aiIdx].workflowSteps
  if (!steps) return  // 不是多任务模式，忽略
  const td = data.data || {}
  const taskId = td.task_id
  const step = steps.find(s => s.id === taskId)
  if (!step) return

  if (data.event === 'task_started') {
    step.status = 'running'
  } else if (data.event === 'task_completed') {
    step.status = 'done'
    step.duration = td.duration
    step.output = td.output
  } else if (data.event === 'task_failed') {
    step.status = 'failed'
    step.duration = td.duration
    step.error = td.error
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
git commit -m "feat: collect workflow step events in SSE callback"
```

---

### Task 2: 模板 — 时间轴渲染

**Files:**
- Modify: `frontend/src/views/ChatView.vue:96-117`（消息气泡区域）

- [ ] **Step 1: 在 AI 消息气泡中添加时间轴**

在 `msg.kb_refs` 的 `refs-inline` 之后、`msg.content` 之前，插入时间轴：

```vue
<div class="msg-bubble">
  <!-- kb_refs 标签 -->
  <div v-if="msg.kb_refs?.length" class="refs-inline">
    <el-popover v-for="(ref, idx) in msg.kb_refs" :key="idx" trigger="hover" :width="420" placement="top">
      <template #reference>
        <el-tag size="small" type="info" class="ref-tag">{{ ref.label }}</el-tag>
      </template>
      <div class="ref-popover-content">{{ ref.content }}</div>
    </el-popover>
  </div>
  <!-- workflow 时间轴 -->
  <div v-if="msg.workflowSteps?.length" class="workflow-timeline">
    <div v-for="step in msg.workflowSteps" :key="step.id" class="timeline-step">
      <span class="step-icon">
        {{ step.status === 'done' ? '✅' : step.status === 'failed' ? '❌' : step.status === 'running' ? '🔄' : '⏳' }}
      </span>
      <el-popover trigger="hover" :width="380" placement="right">
        <template #reference>
          <span class="step-name">{{ step.name }}</span>
        </template>
        <div class="step-detail">
          <div v-if="step.agent"><b>Agent:</b> {{ step.agent }}</div>
          <div v-if="step.duration != null"><b>耗时:</b> {{ step.duration }}s</div>
          <div v-if="step.toolCalls?.length">
            <b>工具调用:</b>
            <div v-for="(tc, i) in step.toolCalls" :key="i" class="tool-call">
              • {{ tc.name }}: {{ tc.input }}
            </div>
          </div>
          <div v-if="step.output"><b>输出:</b> {{ step.output }}</div>
          <div v-if="step.error" style="color: #F56C6C"><b>错误:</b> {{ step.error }}</div>
        </div>
      </el-popover>
      <span v-if="step.duration != null" class="step-duration">{{ step.duration }}s</span>
    </div>
  </div>
  <!-- 消息正文 -->
  <div class="msg-text">{{ msg.content }}</div>
</div>
```

- [ ] **Step 2: 验证编译**

```bash
cmd //c "cd /d F:\workinfo\Projects\PythonProj\install_deb_refactor\frontend && npm run build"
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/ChatView.vue
git commit -m "feat: render workflow timeline in AI message bubble"
```

---

### Task 3: 样式

**Files:**
- Modify: `frontend/src/views/ChatView.vue`（`<style scoped>` 末尾）

- [ ] **Step 1: 添加时间轴样式**

在 `</style>` 前追加：

```css
.workflow-timeline {
  margin-bottom: 8px;
  padding: 6px 0;
  border-bottom: 1px dashed #E4E7ED;
}
.timeline-step {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  font-size: 13px;
  line-height: 1.8;
}
.step-icon {
  flex-shrink: 0;
  width: 18px;
  text-align: center;
}
.step-name {
  cursor: pointer;
  color: #409EFF;
  flex: 1;
}
.step-name:hover {
  text-decoration: underline;
}
.step-duration {
  flex-shrink: 0;
  font-size: 11px;
  color: #909399;
}
.step-detail {
  font-size: 13px;
  line-height: 1.7;
}
.tool-call {
  margin-left: 8px;
  font-size: 12px;
  color: #606266;
  word-break: break-all;
}
```

- [ ] **Step 2: 最终构建验证**

```bash
cmd //c "cd /d F:\workinfo\Projects\PythonProj\install_deb_refactor\frontend && npm run build"
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/ChatView.vue
git commit -m "style: add workflow timeline CSS"
```
