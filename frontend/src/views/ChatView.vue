<template>
  <div class="chat-page">
    <!-- 左侧：会话历史（可折叠） -->
    <aside v-show="showSidebar" class="chat-sidebar">
      <div class="sidebar-head">
        <el-button type="primary" size="small" :icon="Plus" circle @click="newSession" title="新建会话" />
      </div>
      <div class="session-list">
        <div v-for="s in sessions" :key="s.session_id"
             class="session-item" :class="{ active: s.session_id === currentSession }"
             @click="selectSession(s.session_id)">
          <template v-if="editingSession === s.session_id">
            <div class="session-rename" @click.stop>
              <el-input v-model="editingTitle" size="small" placeholder="输入新标题"
                        @keydown.enter="saveRename(s)" @keydown.esc="cancelRename" />
              <el-button size="small" type="primary" @click="saveRename(s)">保存</el-button>
            </div>
          </template>
          <template v-else>
            <div class="session-row">
              <div class="session-title" @dblclick.stop="startRename(s)">{{ s.title || (s.session_id && s.session_id.slice(0, 12)) }}</div>
              <div class="session-actions">
                <el-icon class="session-action" @click.stop="startRename(s)" title="重命名"><Edit /></el-icon>
                <el-icon class="session-action del" @click.stop="deleteSessionById(s)" title="删除"><Delete /></el-icon>
              </div>
            </div>
            <div class="session-meta">
              <span class="session-time">{{ s.created_at || s.last_message_at || '' }}</span>
              <span v-if="s.message_count" class="session-count">{{ s.message_count }} 条</span>
            </div>
          </template>
        </div>
        <el-empty v-if="!sessions.length" description="暂无会话" :image-size="60" />
      </div>
    </aside>

    <!-- 右侧：对话区 -->
    <main class="chat-main">
      <div class="chat-toolbar">
        <div class="toolbar-left">
          <el-button text size="small" class="sidebar-toggle" @click="showSidebar = !showSidebar" :title="showSidebar ? '折叠会话列表' : '展开会话列表'">
            <el-icon><Fold v-if="showSidebar" /><Expand v-else /></el-icon>
          </el-button>
          <span class="chat-title">
            对话 <span v-if="currentSession" class="session-id">#{{ currentSession.slice(0, 8) }}</span>
          </span>
        </div>
        <el-button text size="small" @click="showConfig = !showConfig">
          {{ showConfig ? '收起配置' : '展开配置' }}
        </el-button>
      </div>

      <el-collapse-transition>
        <div v-show="showConfig" class="config-panel">
          <el-row :gutter="10">
            <el-col :span="8">
              <el-select v-model="selectedAgent" placeholder="Agent（可选）" clearable filterable size="small" style="width: 100%">
                <el-option v-for="a in subagents" :key="a.agent_id" :label="a.name" :value="String(a.agent_id)" />
              </el-select>
            </el-col>
            <el-col :span="8">
              <el-select v-model="selectedKb" placeholder="知识库（@引用）" clearable filterable size="small" style="width: 100%">
                <el-option v-for="kb in kbList" :key="kb.kb_id" :label="kb.name" :value="kb.kb_id" />
              </el-select>
            </el-col>
            <el-col :span="8">
              <el-select v-model="selectedMode" placeholder="模式（可选）" clearable filterable size="small" style="width: 100%">
                <el-option v-for="m in modes" :key="m.key" :label="m.name" :value="m.key" />
              </el-select>
            </el-col>
          </el-row>
          <el-row :gutter="10" style="margin-top: 8px;">
            <el-col :span="6">
              <el-input-number v-model="retrieveTopK" :min="1" :max="20" size="small" style="width: 100%" />
            </el-col>
            <el-col :span="6">
              <el-select v-model="retrieveStrategy" size="small" style="width: 100%">
                <el-option label="混合" value="hybrid" />
                <el-option label="语义" value="semantic" />
                <el-option label="关键词" value="keyword" />
                <el-option label="自适应" value="adaptive" />
              </el-select>
            </el-col>
            <el-col :span="6">
              <el-select v-model="chatMode" size="small" style="width: 100%">
                <el-option label="实时流式" value="streaming" />
                <el-option label="等待完整" value="blocking" />
              </el-select>
            </el-col>
            <el-col :span="6">
              <el-switch v-model="deepThinking" active-text="深度思考" size="small" />
            </el-col>
          </el-row>
        </div>
      </el-collapse-transition>

      <div class="chat-messages" ref="chatBox">
        <div v-for="msg in messages" :key="msg.id || msg.timestamp"
             class="msg-row" :class="msg.role === 'user' ? 'msg-user' : 'msg-ai'">
          <div class="msg-avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
          <div class="msg-bubble" :class="{ 'msg-filtered': msg.filtered }">
            <div v-if="msg.kb_refs?.length" class="refs-inline">
              <el-popover
                v-for="(ref, idx) in msg.kb_refs"
                :key="idx"
                trigger="hover"
                :width="420"
                placement="top"
              >
                <template #reference>
                  <el-tag size="small" type="info" class="ref-tag">{{ ref.label }}</el-tag>
                </template>
                <div class="ref-popover-content">{{ ref.content }}</div>
              </el-popover>
            </div>
            <!-- 已上传文件标识 -->
            <div v-if="msg.files?.length" class="refs-inline">
              <el-popover
                v-for="(f, idx) in msg.files"
                :key="idx"
                trigger="hover"
                :width="500"
                placement="top"
              >
                <template #reference>
                  <el-tag size="small" type="success" class="ref-tag">
                    <el-icon style="margin-right: 3px;"><Document /></el-icon>{{ f.name }}
                  </el-tag>
                </template>
                <div class="ref-popover-content" style="max-height: 400px;">{{ f.content }}</div>
              </el-popover>
            </div>
            <!-- AI 思考过程（planning 模式） -->
            <div v-if="msg.reasoningText" class="reasoning-box">
              <div class="reasoning-toggle" @click="msg._reasoningOpen = !msg._reasoningOpen">
                💭 AI 任务规划 {{ msg._reasoningOpen ? '▲' : '▼' }}
              </div>
              <div v-if="msg._reasoningOpen" class="reasoning-content">{{ msg.reasoningText }}</div>
            </div>
            <!-- workflow 时间轴 -->
            <WorkflowTimeline :workflow-steps="msg.workflowSteps" />
            <div class="msg-text">{{ formatMessageContent(msg.content) }}</div>
          </div>
        </div>
        <el-empty v-if="!messages.length" description="选择或新建会话开始对话" :image-size="80" />
      </div>

      <div class="chat-input-area">
        <!-- 已选文件列表 -->
        <div v-if="uploadedFiles.length" class="refs-row">
          <el-tag
            v-for="(f, idx) in uploadedFiles" :key="idx"
            closable size="small" type="success"
            @close="removeFile(idx)"
            style="margin-right: 6px; margin-bottom: 4px;"
          >
            <el-icon style="margin-right: 4px;"><Document /></el-icon>
            {{ f.name }} ({{ formatFileSize(f.size) }})
          </el-tag>
        </div>
        <div v-if="selectedRefs.length" class="refs-row">
          <el-tag v-for="(ref, idx) in selectedRefs" :key="idx" closable size="small" @close="removeRef(idx)" style="margin-right: 6px; margin-bottom: 4px;">
            <el-popover trigger="hover" placement="top" :width="400">
              <template #reference><span style="cursor: pointer;">{{ ref.label || ref.doc_name }}</span></template>
              <div style="max-height: 300px; overflow-y: auto; white-space: pre-wrap; line-height: 1.6;">{{ ref.content }}</div>
            </el-popover>
          </el-tag>
        </div>
        <div class="input-row">
          <div class="input-wrap">
            <el-input ref="messageInput" v-model="newMessage" placeholder="输入消息... 输入 @ 触发知识库引用" type="textarea" :rows="3" resize="none" class="msg-textarea" @input="onInputChange" @keydown="onMentionKeydown" @keydown.esc="closeMention" @keydown.enter.ctrl="send" @blur="blurCloseMention" />
            <div v-if="mentionVisible" class="mention-pop">
              <div v-if="mentionLoading" class="mention-hint">检索中...</div>
              <div v-else-if="!mentionResults.length" class="mention-hint">输入查询词检索片段</div>
              <div v-else>
                <div v-for="(chunk, idx) in mentionResults" :key="idx" class="mention-item" :class="{ active: idx === mentionActiveIndex }" @mousedown.prevent="selectRef(chunk)">
                  <div class="mention-name">{{ kbName || '知识库' }}_#{{ idx + 1 }}<span v-if="formatCitation(chunk)" class="mention-cite"> · {{ formatCitation(chunk) }}</span></div>
                  <div class="mention-content">{{ chunk.content.slice(0, 80) }}</div>
                </div>
              </div>
            </div>
            <div class="send-actions">
              <el-upload
                :show-file-list="false"
                :auto-upload="false"
                :on-change="handleFileChange"
                accept=".txt,.md,.csv,.json,.xml,.yaml,.yml,.log,.py,.js,.html,.css,.sql,.cfg,.ini,.conf,.toml"
              >
                <el-button circle class="upload-btn" title="上传文档（txt/md/csv/json 等文本文件）">
                  <el-icon :size="16"><Upload /></el-icon>
                </el-button>
              </el-upload>
              <el-button type="primary" :icon="Top" circle class="send-btn" :loading="sending" @click="send" title="发送 (Ctrl+Enter)" />
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
  <PlanReviewDialog v-model="reviewVisible" :data="reviewData" />
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { chatApi, modeApi, ragApi } from '../api'
import PlanReviewDialog from '../components/PlanReviewDialog.vue'
import WorkflowTimeline from '../components/WorkflowTimeline.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Delete, Fold, Expand, Plus, Top, Upload, Document } from '@element-plus/icons-vue'
import { formatCitation } from '../utils/citation.js'

const route = useRoute()
const sessions = ref([])
const messages = ref([])
const currentSession = ref('')
const newMessage = ref('')
const sending = ref(false)
const reviewVisible = ref(false)
const reviewData = ref(null)
const chatBox = ref(null)
const messageInput = ref(null)
const subagents = ref([])
const selectedAgent = ref('')
const chatMode = ref('streaming')
const selectedMode = ref('')
const modes = ref([])
const deepThinking = ref(false)
const kbList = ref([])
const selectedKb = ref('')
const kbName = computed(() => {
  const kb = kbList.value.find(k => k.kb_id === selectedKb.value)
  return kb?.name || '知识库'
})
const retrieveTopK = ref(5)
const retrieveStrategy = ref('hybrid')
const mentionVisible = ref(false)
const mentionQuery = ref('')
const mentionResults = ref([])
const mentionLoading = ref(false)
const mentionActiveIndex = ref(0)
const currentMention = ref(null)
const selectedRefs = ref([])
const uploadedFiles = ref([])  // { name, size, content }
const pendingReads = ref([])  // { name: string, promise: Promise }——send() 需等待所有读取完成后才发送。用 name 匹配而非索引，因异步读取完成顺序可能与选择顺序不一致
const showConfig = ref(false)
const showSidebar = ref(false)
const editingSession = ref(null)
const editingTitle = ref('')
let mentionTimer = null

const loadSessions = async () => {
  try {
    const data = await chatApi.getSessions()
    let list = data?.sessions || data?.data || (Array.isArray(data) ? data : [])
    // 默认只显示 10 条最近的会话
    sessions.value = list.slice(0, 10)
  } catch (e) {
    console.log('Sessions load failed (server may be offline)')
  }
}

const newSession = async () => {
  // 调后端 createSession 创建真实 DB session，避免前端临时 id 导致点历史 404
  try {
    const data = await chatApi.createSession({ title: '' })  // 空 title，后端首条消息后 auto_title
    const sid = data?.session_id || data?.id || data?.pr_key_id
    if (sid) {
      currentSession.value = sid
      messages.value = []
      await loadSessions()
      return
    }
  } catch (e) {
    console.log('createSession failed, fallback to temp id:', e.message || '')
  }
  // fallback：后端不可用时用临时 id（不持久，仅当前会话）
  currentSession.value = 'session_' + Date.now()
  messages.value = []
  sessions.value.unshift({ session_id: currentSession.value, created_at: new Date().toLocaleString() })
}

const planToTextFromTasks = (tasks, mode) => {
  if (!tasks?.length) return ''
  return tasks.map((t, i) =>
    tasks.length === 1
      ? t.description || ''
      : `任务${i + 1}（${t.agent || 'agent'}）：${t.description || ''}`
  ).join('\n')
}

const restoreWorkflowFromHistory = (msg) => {
  if (msg.role !== 'assistant') return msg
  let content = msg.content
  if (!content) return msg
  // 兼容 JSON 字符串格式（旧版存储）
  if (typeof content === 'string' && content.startsWith('{') && content.includes('"workflow_tasks"')) {
    try { content = JSON.parse(content) } catch { return msg }
  }
  if (typeof content !== 'object') return msg
  const tasks = content.workflow_tasks
  if (!Array.isArray(tasks) || tasks.length === 0) return msg
  return {
    ...msg,
    content,  // 保持 content 为已解析的对象（formatMessageContent 会提取 text）
    workflowSteps: tasks.map((t, i) => ({
      id: t.id,
      name: tasks.length === 1 ? (t.agent || t.id) : `${t.agent || t.id} · 任务${i + 1}`,
      description: t.description || '',
      agent: t.agent || '',
      status: t.status || 'done',
      toolCalls: [],
      duration: null,
      output: t.result || null,
      error: t.error || null,
    })),
    reasoningText: planToTextFromTasks(tasks, content.workflow_mode),
  }
}

const restoreFilesFromHistory = (msg) => {
  // 从历史消息 content 中还原 files 字段，使文件名标签在历史会话中也可用
  if (msg.role !== 'user' || !msg.content || typeof msg.content !== 'string') return msg
  if (!msg.files && msg.content.includes('【用户上传了文件「')) {
    const files = []
    const re = /【用户上传了文件「(.+?)」，内容如下】/g
    let match
    while ((match = re.exec(msg.content)) !== null) {
      files.push({ name: match[1], size: 0, content: '' })
    }
    if (files.length) return { ...msg, files }
  }
  return msg
}

const selectSession = async (id) => {
  currentSession.value = id
  try {
    const data = await chatApi.getMessages(id)
    let msgs = data?.messages || data?.data || (Array.isArray(data) ? data : [])
    // 从 DB 历史还原 workflowSteps / reasoningText
    msgs = msgs.map(m => restoreWorkflowFromHistory(m))
    // 从历史消息中还原 files 字段（用于显示文件名标签 + 悬停弹窗）
    msgs = msgs.map(m => restoreFilesFromHistory(m))
    messages.value = msgs
  } catch {
    messages.value = []
  }
  scrollToBottom()
}

const send = async () => {
  const hasText = newMessage.value.trim().length > 0
  // 等待所有待完成的文件读取 Promise，修复 FileReader 异步读取与 send() 之间的竞态条件
  if (pendingReads.value.length > 0) {
    try {
      await Promise.all(pendingReads.value.map(p => p.promise))
    } catch (e) {
      ElMessage.error('文件读取失败，请重试')
      pendingReads.value = []
      return
    }
    pendingReads.value = []
  }
  const hasFiles = uploadedFiles.value.length > 0
  if ((!hasText && !hasFiles) || sending.value) return
  if (!currentSession.value) await newSession()

  // 构建 kb_refs（结构化字段，不再拼纯文本）
  let content = newMessage.value
  // 文件内容：拼到消息最前面（自然语言格式，LLM 能明确识别）
  const uploadedSnapshots = uploadedFiles.value.length > 0 ? uploadedFiles.value.map(f => ({ name: f.name, size: f.size, content: f.content })) : null
  if (uploadedFiles.value.length > 0) {
    const fileBlocks = uploadedFiles.value.map(f =>
      `【用户上传了文件「${f.name}」，内容如下】\n\n${f.content}`
    ).join('\n\n---\n\n')
    if (content) {
      content = fileBlocks + '\n\n---\n\n【用户的问题】\n' + content
    } else {
      content = fileBlocks + '\n\n请根据以上文件内容给出分析和回答。'
    }
  }
  let kbRefs = null
  if (selectedRefs.value.length > 0) {
    kbRefs = selectedRefs.value.map(r => ({
      label: r.label || r.doc_name?.replace(/^.*[\\/]/, '').replace(/\.[^.]+$/, '') || '',
      content: r.content,
      kb_id: r.kb_id || selectedKb.value,
      doc_name: r.doc_name || '',
    }))
  }
  // 兜底：用户未从弹窗选中但消息中有 #xxx# 占位符 → 自动检索知识库
  if (!kbRefs && selectedKb.value) {
    const matches = [...content.matchAll(/#([^#\n]{1,50})#/g)]
    if (matches.length > 0) {
      console.log('[send] 检测到 #占位符# 但 selectedRefs 为空，自动检索知识库...')
      const autoRefs = []
      for (const m of matches) {
        const query = m[1].trim()
        if (!query) continue
        try {
          const res = await ragApi.retrieve({
            query, kb_id: selectedKb.value, top_k: 1, strategy: 'semantic',
          })
          if (res?.chunks?.length > 0) {
            const chunk = res.chunks[0]
            autoRefs.push({
              label: query,
              content: chunk.content,
              kb_id: selectedKb.value,
              doc_name: chunk.doc_name || '',
            })
          }
        } catch (e) { console.error('[send] 自动检索失败:', query, e) }
      }
      if (autoRefs.length > 0) kbRefs = autoRefs
    }
  }
  console.log('[send] selectedRefs:', selectedRefs.value.length, 'kbRefs:', kbRefs ? `${kbRefs.length} refs` : 'null', 'files:', uploadedFiles.value.map(f => f.name))

  const userMsg = { role: 'user', content, kb_refs: kbRefs, files: uploadedSnapshots }
  messages.value.push(userMsg)
  const msg = content
  newMessage.value = ''
  selectedRefs.value = []
  uploadedFiles.value = []
  sending.value = true
  // AI 消息占位（流式实时追加 content，用索引访问 reactive proxy 触发更新）
  const aiIdx = messages.value.length
  messages.value.push({ role: 'assistant', content: '' })
  scrollToBottom()

  try {
    if (chatMode.value === 'blocking') {
      // 阻塞模式：非流式 /chat，等完整回复
      const result = await chatApi.send({
        session_id: currentSession.value,
        messages: [{ role: 'user', content: msg, kb_refs: kbRefs }],
        agent: selectedAgent.value || undefined,
        responseMode: selectedMode.value || undefined,
        deepThinking: deepThinking.value,
      })
      const aiContent = typeof result === 'string' ? result : (result?.content || result?.text || result?.message || JSON.stringify(result))
      messages.value[aiIdx].content = aiContent
      if (result?.session_id) currentSession.value = result.session_id
    } else {
      // 流水模式：流式 /chat/stream，实时追加
      await chatApi.streamChat({
        session_id: currentSession.value,
        messages: [{ role: 'user', content: msg, kb_refs: kbRefs }],
        agent: selectedAgent.value || undefined,
        responseMode: selectedMode.value || undefined,
        deepThinking: deepThinking.value,
      }, (data) => {
        if (data.type === 'plan_review') { reviewVisible.value = true; reviewData.value = data; return }
        // ——— workflow 时间轴事件 ———
        if (data.execution_event) {
          const ev = data.execution_event
          const etype = ev.event_type
          const edata = ev.data || {}
          if (etype === 'plan') {
            const tasks = edata.workflow?.tasks
            if (tasks?.length > 0) {
              // 保存原始计划描述到 reasoningText（思考过程折叠区用）
              messages.value[aiIdx].reasoningText = planToText(edata.workflow)
              messages.value[aiIdx].workflowSteps = tasks.map(t => ({
                id: t.id,
                // 短名：单任务用 agent 名，多任务用 "Agent · 任务N"
                name: tasks.length === 1 ? (t.agent || t.id) : `${t.agent || t.id} · 任务${tasks.indexOf(t) + 1}`,
                // hover 时展示完整描述
                description: t.description || '',
                agent: t.agent || '',
                status: 'pending',
                toolCalls: [],
              }))
            }
          }
          if (etype === 'tool_start') {
            let steps = messages.value[aiIdx].workflowSteps
            if (!steps) {
              messages.value[aiIdx].workflowSteps = []
              steps = messages.value[aiIdx].workflowSteps
            }
            // planning 模式：追加到当前 running 步骤（task_started 已设置 status='running'）
            const target = steps.find(s => s.status === 'running')
            if (target) {
              if (!target.toolCalls) target.toolCalls = []
              target.toolCalls.push({
                name: edata.tool_name || '',
                input: JSON.stringify(edata.input || {}).slice(0, 200),
              })
            } else {
              // REACT 模式（无 task_started）：前一个 running 标记 done，创建新步骤
              steps.forEach(s => { if (s.status === 'running') s.status = 'done' })
              steps.push({
                id: 'tool_' + Date.now() + '_' + steps.length,
                name: edata.tool_name || '工具调用',
                agent: edata.agent_name || '',
                status: 'running',
                toolCalls: [{
                  name: edata.tool_name || '',
                  input: JSON.stringify(edata.input || {}).slice(0, 200),
                }],
              })
            }
          }
          if (etype === 'task_started' || etype === 'task_completed' || etype === 'task_failed') {
            const steps = messages.value[aiIdx].workflowSteps
            if (steps) {
              const step = steps.find(s => s.id === edata.task_id)
              if (step) {
                if (etype === 'task_started') step.status = 'running'
                else if (etype === 'task_completed') { step.status = 'done'; step.duration = edata.duration; step.output = edata.output }
                else if (etype === 'task_failed') { step.status = 'failed'; step.duration = edata.duration; step.error = edata.error }
              }
            }
          }
        }
        // content 开始流式时，标记所有 running 步骤为 done（REACT 模式兜底）
        if (data.content && messages.value[aiIdx].workflowSteps) {
          messages.value[aiIdx].workflowSteps.forEach(s => {
            if (s.status === 'running') s.status = 'done'
          })
        }
        if (data.content) messages.value[aiIdx].content += data.content
        if (data.filtered) {
          messages.value[aiIdx].filtered = true
          ElMessage.warning('内容安全审查：消息被拦截')
        }
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

const loadSubagents = async () => {
  try {
    const data = await chatApi.getSubagents()
    subagents.value = data?.subagents || data?.data || (Array.isArray(data) ? data : [])
  } catch (e) {
    console.log('Subagents load failed (server may be offline)')
  }
}

const loadKbList = async () => {
  try {
    const res = await ragApi.kbList()
    kbList.value = res.list || []
  } catch (e) {
    console.log('KbList load failed (RAG API may be offline)')
  }
}

const detectMention = (text, cursorPos) => {
  const before = text.slice(0, cursorPos)
  const atIdx = before.lastIndexOf('@')
  if (atIdx === -1) return null
  const afterAt = before.slice(atIdx + 1)
  if (afterAt.includes(' ') || afterAt.includes('\n')) return null
  if (afterAt.length === 0) return { start: atIdx, query: '', end: cursorPos }
  return { start: atIdx, query: afterAt, end: cursorPos }
}

const onInputChange = (value) => {
  // Element Plus el-input @input 传 value（字符串），不是原生 event
  if (value == null) return
  // 用 ref 获取内部 textarea DOM 读光标位置
  const textarea = messageInput.value?.ref
  const text = value
  const cursorPos = textarea ? textarea.selectionStart : text.length
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
  const m = currentMention.value
  const before = newMessage.value.slice(0, m.start)
  const after = newMessage.value.slice(m.end)

  // 获取知识库名
  const kb = kbList.value.find(k => k.kb_id === selectedKb.value)
  const kbName = kb?.name || '知识库'

  // shortName 优先用用户搜索关键词（体现用户意图），其次 node_title，最后 doc_name
  let shortName = (m.query || '').trim()
  if (!shortName && chunk.node_title) {
    shortName = chunk.node_title
      .replace(/^[（(][一二三四五六七八九十\d]+[)）]\s*/, '')
      .trim()
  }
  if (!shortName && chunk.doc_name) {
    shortName = chunk.doc_name
      .replace(/^.*[\\/]/, '')
      .replace(/\.[^.]+$/, '')
  }
  if (!shortName) shortName = kbName

  // 插入占位符 #shortName#，保持句子完整
  newMessage.value = before + '#' + shortName + '#' + after

  // 生成完整标签：知识库名@搜索关键词
  const fullLabel = kbName + '@' + shortName

  const exists = selectedRefs.value.some(r => r.content === chunk.content)
  if (!exists) {
    selectedRefs.value.push({ ...chunk, kb_id: selectedKb.value, label: fullLabel })
  }
  closeMention()
}

const planToText = (workflow) => {
  // 将 plan 的 tasks 转成思考过程文本
  if (!workflow?.tasks?.length) return ''
  const mode = workflow.mode || 'sequential'
  return workflow.tasks.map((t, i) =>
    workflow.tasks.length === 1
      ? t.description || ''
      : `任务${i + 1}（${t.agent || 'agent'}）：${t.description || ''}`
  ).join('\n')
}

const formatMessageContent = (content) => {
  // 后端 planning 模式存 JSON 结构体：提取 text 字段展示，隐藏 metadata
  if (!content) return content
  // Case A: MySQL JSON 类型返回已解析的 JS 对象（Axios 自动 parse）
  if (typeof content === 'object' && content.text) {
    return content.text
  }
  // Case B: 普通字符串
  if (typeof content === 'string') {
    // JSON 字符串（旧版或序列化场景）
    if (content.startsWith('{') && content.includes('"text"')) {
      try {
        const parsed = JSON.parse(content)
        return parsed.text || content
      } catch { /* fall through */ }
    }
    // 有文件附件的用户消息：只显示用户输入的文字部分（去掉文件内容块）
    // 新格式：【用户上传了文件「xxx」，内容如下】...【用户的问题】...
    if (content.includes('【用户上传了文件「')) {
      const qMarker = '【用户的问题】\n'
      const qIdx = content.indexOf(qMarker)
      if (qIdx >= 0) {
        let afterQ = content.slice(qIdx + qMarker.length)
        // 去掉后端附加的沙箱提示（如有）
        const hintIdx = afterQ.indexOf('\n\n---\n💡')
        if (hintIdx >= 0) afterQ = afterQ.slice(0, hintIdx)
        return afterQ.trim() || '（已上传文件）'
      }
      return '（已上传文件）'
    }
    // 旧格式兼容：[文件:xxx]
    if (content.startsWith('[文件:') && content.includes('\n---\n')) {
      const idx = content.lastIndexOf('\n---\n')
      return content.slice(idx + 5).trim() || content
    }
    // 纯文件内容（没有文字部分）→ 显示简短提示
    if (content.startsWith('[文件:')) {
      return '（已上传文件）'
    }
  }
  return content
}

const closeMention = () => {
  mentionVisible.value = false
  currentMention.value = null
  mentionResults.value = []
}

const onMentionKeydown = (e) => {
  if (!mentionVisible.value || !mentionResults.value.length) return
  if (e.key === 'Enter' && !e.ctrlKey) {
    e.preventDefault()
    selectRef(mentionResults.value[mentionActiveIndex.value])
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    mentionActiveIndex.value = Math.max(0, mentionActiveIndex.value - 1)
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    mentionActiveIndex.value = Math.min(
      mentionResults.value.length - 1,
      mentionActiveIndex.value + 1
    )
  }
}

const blurCloseMention = () => {
  setTimeout(closeMention, 200)
}

const removeRef = (index) => {
  selectedRefs.value.splice(index, 1)
}

// ── 文件上传 ──
const MAX_FILE_SIZE = 5 * 1024 * 1024  // 5MB
const formatFileSize = (bytes) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
const handleFileChange = (uploadFile) => {
  const file = uploadFile.raw  // el-upload on-change 传入 UploadFile 对象，raw 是原生 File
  if (!file) return
  if (file.size > MAX_FILE_SIZE) {
    ElMessage.warning(`文件「${file.name}」超过 5MB 限制，请拆分后上传`)
    return
  }
  const readPromise = new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      const content = e.target.result
      uploadedFiles.value.push({ name: file.name, size: file.size, content })
      resolve()
    }
    reader.onerror = () => {
      const errMsg = `读取文件「${file.name}」失败`
      ElMessage.error(errMsg)
      reject(new Error(errMsg))
    }
    reader.readAsText(file, 'UTF-8')
  })
  pendingReads.value.push({ name: file.name, promise: readPromise })
}
const removeFile = (index) => {
  const removed = uploadedFiles.value.splice(index, 1)[0]
  // 同步清理对应的 pendingRead（按 name 匹配，因异步读取完成顺序可能与选择顺序不一致）
  if (removed) {
    const i = pendingReads.value.findIndex(p => p.name === removed.name)
    if (i >= 0) pendingReads.value.splice(i, 1)
  }
}

const startRename = (s) => {
  editingSession.value = s.session_id
  editingTitle.value = s.title || ''
}
const saveRename = async (s) => {
  const title = editingTitle.value.trim()
  if (!title) { editingSession.value = null; return }
  try {
    await chatApi.updateSession(s.session_id, { title })
    s.title = title
  } catch (e) {
    ElMessage.error('重命名失败: ' + (e.message || ''))
  }
  editingSession.value = null
}
const cancelRename = () => { editingSession.value = null }

const deleteSessionById = async (s) => {
  try {
    await ElMessageBox.confirm(`删除会话「${s.title || s.session_id?.slice(0, 8)}」？`, '提示', { type: 'warning' })
  } catch { return }
  try {
    await chatApi.deleteSession(s.session_id)
    if (currentSession.value === s.session_id) {
      currentSession.value = ''
      messages.value = []
    }
    await loadSessions()
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.message || ''))
  }
}

const scrollToBottom = () => {
  nextTick(() => {
    if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
  })
}

const loadModes = async () => {
  try {
    const data = await modeApi.getModes()
    modes.value = data?.modes || []
  } catch (e) {
    console.log('Modes load failed')
  }
}

onMounted(() => {
  loadSessions()
  loadSubagents()
  loadModes()
  loadKbList()
  // 支持从 Agent 管理页跳转预选：/chat?agent=7
  const q = route.query.agent
  if (q) selectedAgent.value = String(q)
  // 支持模式预选：/chat?mode=xxx
  const m = route.query.mode
  if (m) selectedMode.value = String(m)
})
</script>

<style scoped>
.chat-page {
  display: flex;
  gap: 16px;
  height: calc(100vh - 100px);
  padding: 0;
}
/* 左侧会话列表 */
.chat-sidebar {
  width: 260px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 12px;
  border: 1px solid #E2E8F0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.sidebar-head {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 12px 14px;
  border-bottom: 1px solid #F1F5F9;
}
.sidebar-toggle {
  color: #1E293B;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}
.session-item {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: background 0.2s;
  border: 1px solid transparent;
}
.session-item:hover {
  background: #F1F5F9;
}
.session-item.active {
  background: #EEF2FF;
  border-color: #C7D2FE;
}
.session-title {
  font-size: 13px;
  font-weight: 500;
  color: #1E293B;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
}
.session-time {
  font-size: 11px;
  color: #94A3B8;
}
.session-count {
  font-size: 11px;
  color: #64748B;
  background: #F1F5F9;
  border-radius: 10px;
  padding: 0 6px;
}
/* 右侧对话区 */
.chat-main {
  flex: 1;
  background: #fff;
  border-radius: 12px;
  border: 1px solid #E2E8F0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid #F1F5F9;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chat-title {
  font-size: 14px;
  font-weight: 600;
  color: #1E293B;
}
.session-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
}
.session-actions {
  display: none;
  gap: 4px;
  flex-shrink: 0;
}
.session-item:hover .session-actions {
  display: flex;
}
.session-action {
  cursor: pointer;
  color: #64748B;
  font-size: 14px;
  padding: 2px;
  border-radius: 4px;
  transition: all 0.2s;
}
.session-action:hover {
  color: #409eff;
  background: #EEF2FF;
}
.session-action.del:hover {
  color: #f56c6c;
  background: #fef0f0;
}
.session-rename {
  display: flex;
  gap: 6px;
  align-items: center;
}
.session-id {
  color: #64748B;
  font-weight: 400;
  font-size: 12px;
}
.config-panel {
  padding: 12px 16px;
  background: #fafbfc;
  border-bottom: 1px solid #F1F5F9;
}
/* 消息区 */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  background: #F8FAFC;
}
.msg-row {
  display: flex;
  margin-bottom: 16px;
  gap: 10px;
}
.msg-user {
  flex-direction: row-reverse;
}
.msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}
.msg-user .msg-avatar {
  background: linear-gradient(135deg, #6366F1, #818CF8);
  color: #fff;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.25);
}
.msg-ai .msg-avatar {
  background: linear-gradient(135deg, #22D3EE, #06B6D4);
  color: #fff;
  box-shadow: 0 2px 8px rgba(34, 211, 238, 0.25);
}
.msg-bubble {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-user .msg-bubble {
  background: #EEF2FF;
  color: #1E293B;
  border-top-right-radius: 4px;
}
.msg-ai .msg-bubble {
  background: #fff;
  color: #1E293B;
  border: 1px solid #E2E8F0;
  border-top-left-radius: 4px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
/* 输入区 */
.chat-input-area {
  border-top: 1px solid #F1F5F9;
  padding: 14px 20px;
  background: #fff;
}
.refs-row {
  margin-bottom: 8px;
}
.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.input-wrap {
  flex: 1;
  position: relative;
}
.msg-textarea :deep(.el-textarea__inner) {
  padding-right: 84px;  /* 给上传和发送两个按钮留空间 */
}
.send-btn {
  position: absolute;
  right: 8px;
  bottom: 8px;
  z-index: 10;
  background: linear-gradient(135deg, #6366F1, #818CF8) !important;
  border: none !important;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3) !important;
  transition: all 0.25s ease;
}
.send-btn:hover {
  transform: scale(1.08);
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.4) !important;
}
.send-actions {
  position: absolute;
  right: 8px;
  bottom: 8px;
  display: flex;
  gap: 6px;
  align-items: center;
  z-index: 10;
}
.send-actions .send-btn {
  position: static;
}
.upload-btn {
  background: #F1F5F9 !important;
  border: 1px dashed #CBD5E1 !important;
  color: #64748B !important;
  transition: all 0.2s ease;
}
.upload-btn:hover {
  border-color: #6366F1 !important;
  color: #6366F1 !important;
  background: #EEF2FF !important;
}
.mention-pop {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  z-index: 2000;
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.1);
  max-height: 250px;
  overflow-y: auto;
  margin-bottom: 4px;
}
.mention-hint {
  padding: 12px;
  color: #999;
  text-align: center;
  font-size: 13px;
}
.mention-item {
  padding: 8px 12px;
  cursor: pointer;
  border-bottom: 1px solid #f5f5f5;
}
.mention-item:hover, .mention-item.active {
  background: #F1F5F9;
}
.mention-name {
  font-weight: 600;
  font-size: 12px;
  color: #409eff;
}
.mention-cite {
  font-weight: 400;
  color: #909399;
}
.mention-content {
  font-size: 12px;
  color: #64748B;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.reasoning-box { margin-bottom: 6px; }
.reasoning-toggle {
  cursor: pointer; font-size: 12px; color: #909399; user-select: none;
  padding: 2px 0;
}
.reasoning-toggle:hover { color: #409EFF; }
.reasoning-content {
  font-size: 12px; color: #64748B; white-space: pre-wrap; line-height: 1.6;
  background: #F8F9FB; padding: 6px 10px; border-radius: 4px; margin-top: 4px;
  max-height: 200px; overflow-y: auto;
}
.input-hint {
  margin-top: 6px;
  font-size: 11px;
  color: #94A3B8;
  text-align: right;
}
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
.msg-filtered {
  background: #FFF7F0 !important;
  border: 1px solid #F56C6C;
}
</style>
