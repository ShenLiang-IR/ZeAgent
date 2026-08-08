# ChatView AI 执行步骤时间轴 设计文档

创建时间：2026-08-01
状态：设计已确认，待实现

## 一、背景与目标

### 现状
后端在 PLANNING 模式下已发送丰富的任务事件（`execution_event/plan`、`task_started`、`task_completed`、`task_failed`、`execution_event/tool_start`），但前端流式回调中完全忽略这些事件，只消费 `content`、`error`、`done`。

用户无法感知 AI 的多步骤执行过程。

### 目标
在 AI 回复气泡内嵌时间轴组件，实时展示每个步骤的名称和状态，hover 显示详情（agent、耗时、工具调用、输出摘要）。

### 非目标（YAGNI）
- 不做独立面板/侧边栏
- 不做步骤间依赖箭头
- 不做可折叠/展开
- 不改后端（数据已就绪）
- 仅在 PLANNING 模式且 tasks_count > 1 时显示

---

## 二、数据模型

### 后端已有事件（零改动）

| SSE 事件 | 关键字段 |
|---|---|
| `execution_event/plan` | `tasks[{id, agent, description}]`、`tasks_count`、`execution_mode` |
| `task_started` | `task_id`、`task_name`、`agent` |
| `task_completed` | `task_id`、`duration`、`output`、`tool_calls` |
| `task_failed` | `task_id`、`error`、`duration` |
| `execution_event/tool_start` | `tool_name`、`input`、`agent_name` |
| `thinking` | `reasoning_content` |

### 前端消息扩展

```typescript
interface WorkflowStep {
  id: string
  name: string          // task_name / description
  agent: string
  status: 'pending' | 'running' | 'done' | 'failed'
  startTime?: number
  duration?: number
  output?: string
  error?: string
  toolCalls?: Array<{ name: string; input: string }>
}

// AI 消息扩展
interface AiMessage {
  role: 'assistant'
  content: string
  workflowSteps?: WorkflowStep[]  // ← 新增
}
```

---

## 三、渲染效果

```
┌─────────────────────────────────────────────────────┐
│ AI                                                  │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ⏳ 检索投资限制                                │ │
│ │ 🔄 访问 GitHub Zen API                         │ │
│ │ ⏳ 比较分析结果                                │ │
│ │ ⏳ 写入 0801.md                                │ │
│ └─────────────────────────────────────────────────┘ │
│ 分析结果：...                                       │
└─────────────────────────────────────────────────────┘
```

- 步骤名用 `task_name` 或 `description`
- 状态图标：`⏳` pending → `🔄` running → `✅` done / `❌` failed
- 完成时追加耗时：`✅ 1.2s`
- hover 弹出详情（`el-popover`）：agent、耗时、工具列表、输出/错误

---

## 四、改动范围

| 文件 | 改动 |
|---|---|
| `frontend/src/views/ChatView.vue` | SSE 回调新增事件处理 + 模板新增时间轴 + AI 消息新增 `workflowSteps` 字段 |

---

## 五、触发条件

```javascript
// 在 SSE 回调中：
if (data.execution_event?.event_type === 'plan') {
  const tasks = data.execution_event.data.workflow?.tasks
  if (tasks?.length > 1) {
    // 初始化 workflowSteps
    messages.value[aiIdx].workflowSteps = tasks.map(t => ({
      id: t.id,
      name: t.description || t.agent || t.id,
      agent: t.agent || '',
      status: 'pending',
      toolCalls: [],
    }))
  }
}
```

---

## 六、测试策略

- `npm run build` 验证编译
- 手动测试：发送复杂任务触发 PLANNING 模式 → 观察时间轴实时更新
