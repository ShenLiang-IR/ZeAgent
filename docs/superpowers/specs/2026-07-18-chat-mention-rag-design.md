# ChatView 引用知识库片段 设计文档

创建时间：2026-07-18
状态：设计草案，待用户审查
关联：2026-07-16-rag-enhanced-design.md（RAG 模块）、2026-07-16-context-injection-optimization-design.md（context 注入优化，方案 B 复用）

## 一、背景与目标

### 现状
- RAG 能力（文档解析/向量化/检索）在独立页面 RagView.vue，与对话流割裂
- ChatView.vue 对话页无法直接引用已 ingest 的知识库片段
- 后端 /api/rag/retrieve 已就绪（query + kb_id + top_k 输出 chunks，约 60ms）
- 前端 ragApi.retrieve 已实现并验证

### 目标
在对话聊天输入框引用知识库片段，让 LLM 基于明确引用回答，减少幻觉，提高可追溯性。

### 非目标（YAGNI）
- 不做 AgenticRAG 自动检索（已有独立模块，本次不碰）
- 不做跨知识库联合检索（单次引用只查一个 kb）
- 不做引用片段持久化存储（发送后引用随消息走，不单独存）
- 不引入富文本编辑器（textarea 保持纯文本，引用用 badge 展示）

## 二、交互模式：@ 触发 + badge 列表（方案 C）

textarea 内输入 @ 字符触发检索，选中片段后用 badge 展示在输入框下方（不嵌入文本流，无富文本依赖）。比按钮+Dialog 体验好，比 chip 嵌入文本流简单。

### ChatView 左侧会话卡片新增元素
1. 知识库下拉 el-select（复用 /api/rag/kb 的 kbList，filterable，@ 检索目标 kb）
2. 返回数量 K + 检索策略（紧凑控件，@ 触发检索时用）

### @ 触发检索流程（textarea 内监听）
- 监听 textarea input 事件 + 光标位置
- 用户输入 @ 后，捕获 @ 到下一个空格/换行之间的文本作为查询词
- debounce 300ms 后调 ragApi.retrieve（查询词 + selectedKb + topK + strategy）
- 弹出候选浮层（textarea 下方，absolute 定位）
- 候选项：doc_name + content 前 80 字预览（可上下键导航 + Enter 选中）
- 选中片段：从 textarea 移除 @查询词，片段加入 selectedRefs，关闭浮层
- 取消：按 Esc、输入空格、或 @ 后无查询词时提示输入查询词

### 引用 badge 列表（输入框下方）
- 每个 badge：doc_name + 删除 X
- 点击 badge 弹出 el-popover 显示片段全文
- badge 可多个（支持多片段引用）

## 三、方案 A：片段拼入 message（MVP，后端零改动）

### 拼入格式
send() 时，若 selectedRefs 非空，把片段内容拼入 user message：
- 第一行：【引用知识库片段】
- 每个片段：来源: {doc_name} 换行 {content}
- 分隔线：---
- 最后：用户问题：{newMessage}

### 后端改动
零改动。/api/chat/stream 接收的 messages 不变，LLM 直接看到引用内容。

### 优点
- 快速落地，验证价值
- 不依赖后端，前端独立完成

### 缺点
- 引用片段在历史消息里重复传输（多轮对话时 token 浪费）
- 引用来源不可独立追溯（混在 message 文本里）

## 四、方案 B 升级：references 字段 + context 注入

### 请求 schema 扩展
chatApi.streamChat / chatApi.send 增加 references 字段，结构为列表，每项含 kb_id、doc_name、content。

### 后端 context 注入
- AgentService.chat / chat_stream 接收 references
- 把 references 注入 system prompt 的 context 段（或单独的 system context message）
- 复用已有 context injection 优化机制（见 2026-07-16-context-injection-optimization-design.md，services/multi_agent_service.py 已实现 consumer-side truncation 防 token 膨胀）
- 引用片段走同样的截断逻辑（单片段 >2000 字截断，总 token 超阈值按优先级裁剪）

### 前端 send() 改造
方案 B 时，send() 不拼入 message，改为传 references：selectedRefs 映射为 references 列表传给 streamChat。

### 优点
- 历史消息干净（references 独立，不混入 message 文本）
- 引用可独立追溯（后端可记录哪些引用被用过）
- 复用已有 context injection 优化，token 受控

### 升级路径
1. 方案 A 先落地（前端拼入，后端零改）验证用户价值
2. 升级方案 B：前端 send() 改传 references + 后端 AgentService 加 references 注入
3. badge 列表 UI 不变，用户无感升级

## 五、组件改造（ChatView.vue）

### 新增响应式状态
- kbList：知识库列表（/api/rag/kb）
- selectedKb：当前选中的知识库（@ 检索目标）
- selectedRefs：已选引用片段列表，每项含 kb_id、doc_name、content
- retrieveTopK / retrieveStrategy：检索参数（默认 5 / hybrid）
- mentionPanelVisible：@ 候选浮层可见性
- mentionResults：@ 候选片段列表
- mentionLoading：@ 检索中
- currentMention：当前 @ 信息（{start, query, end}），用于选中后清除文本

### 新增方法
- loadKbList()：onMounted 调用，复用 ragApi.kbList()
- detectMention(text, cursorPos)：检测光标前最近的 @，返回 {start, query, end} 或 null
- onInputChange(e)：textarea input 事件处理，调 detectMention，有 @ 则 debounce 300ms 调 doRetrieve
- doRetrieve(query)：调 ragApi.retrieve(query + selectedKb + topK + strategy)，填充 mentionResults，显示浮层
- selectRef(chunk)：选中片段 → 从 textarea 移除 currentMention 文本，片段加入 selectedRefs，关闭浮层
- closeMentionPanel()：关闭浮层（Esc/外部点击触发）
- removeRef(index)：从 selectedRefs 删除
- send() 改造：方案 A 拼入 message；方案 B 传 references

### 模板新增
- 知识库下拉 + K + 策略（会话卡片内，agent 下拉下方）
- 引用 badge 列表（输入框下方，发送按钮上方）
- @ 候选浮层（textarea 下方，absolute 定位，含候选列表 + 上下键导航）

## 六、数据流

1. onMounted 调用 loadKbList()（新增，复用 ragApi）
2. 用户选 kb（@ 检索目标）
3. 用户在 textarea 输入 @ + 查询词 → onInputChange → detectMention 提取 {start, query, end}
4. debounce 300ms → doRetrieve(query) → ragApi.retrieve → mentionResults → 显示浮层
5. 用户上下键导航 + Enter 选中 → selectRef(chunk) → 从 textarea 移除 @query 文本 + 片段加入 selectedRefs + 关闭浮层
6. badge 列表展示 selectedRefs（输入框下方）
7. 用户输入消息 + 点发送 → send()：
   - 方案 A：selectedRefs 拼入 user message content
   - 方案 B：selectedRefs 作为 references 字段传给 streamChat
8. 发送后清空 selectedRefs

## 七、错误处理

| 场景 | 处理 |
|------|------|
| kbList 为空 | 禁用引用片段按钮，tooltip 提示先在 /rag 创建知识库 |
| 未选 kb 点引用 | ElMessage.warning 提示请先选择知识库 |
| 检索无结果 | 候选表格显示无相关片段，Dialog 保持打开 |
| 检索失败（网络/后端） | ElMessage.error，Dialog 保持打开 |
| 片段过长（>2000 字） | 截断 + badge 标记已截断 |
| selectedRefs 为空发送 | 走原有 send 逻辑，不拼入引用 |

## 八、测试策略

### 前端（无单测框架，refactor.md 10.5 已说明）
- vite build 验证编译
- playwright 端到端：选 kb + 检索 + 勾选片段 + 发送 + 验证 AI 回复含引用上下文

### 后端
- 方案 A：零改动，现有 38 个 RAG 测试不动
- 方案 B：新增 references 注入测试（AgentService 接收 references 后 system prompt 含 context）

## 九、边界情况

- 多个引用：badge 列表支持多个，发送时全部拼入/传 references
- 引用与 agent：引用是消息级，与 agent 选择独立（可同时用）
- 历史消息：方案 A 引用会随 message 存储；方案 B 引用独立，历史干净
- 知识库切换：切换 kb 不影响已选 selectedRefs（已选片段保留）
- 重复片段：同一片段多次引用时去重（按 doc_name + content hash）
