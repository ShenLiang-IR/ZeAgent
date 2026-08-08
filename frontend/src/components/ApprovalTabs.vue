<template>
  <div class="approval-center">
    <div class="section-header">
      <h3 class="section-title">审批中心</h3>
      <span class="section-desc">{{ isAdmin ? '处理审批请求' : '跟踪审批进度' }}</span>
      <el-button size="small" text @click="refreshAll" :loading="loading" style="margin-left: auto;">刷新</el-button>
    </div>

    <el-tabs v-model="activeTab" class="approval-tabs">
      <!-- Tab 1: 我的代办（全部可见） -->
      <el-tab-pane label="我的代办" name="todo" :badge-value="todoCount" :badge="todoCount > 0 ? todoCount : null">
        <el-table :data="todoList" border size="small" v-loading="loading" empty-text="暂无待办事项" max-height="360">
          <el-table-column prop="agent_name" label="Agent 名称" width="160" />
          <el-table-column prop="version_no" label="版本" width="100">
            <template #default="{ row }">{{ row.version_no || '-' }}</template>
          </el-table-column>
          <el-table-column label="类型" width="80">
            <template #default>
              <el-tag size="small" type="warning">待审批</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="agent_description" label="描述" show-overflow-tooltip />
          <el-table-column label="提交时间" width="160">
            <template #default="{ row }">{{ row.updated_at || row.created_at || '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right" v-if="isAdmin">
            <template #default="{ row }">
              <el-button size="small" type="success" @click="approve(row)">通过</el-button>
              <el-button size="small" type="danger" @click="reject(row)">拒绝</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Tab 2: 我的审批（admin）/ 我提交的审批（普通用户） -->
      <el-tab-pane :label="isAdmin ? '我的审批' : '我提交的审批'" name="submissions" :badge-value="submissionCount" :badge="submissionCount > 0 ? submissionCount : null">
        <el-table :data="submissionList" border size="small" v-loading="loading" empty-text="暂无审批记录" max-height="360">
          <el-table-column prop="agent_name" label="Agent 名称" width="160" />
          <el-table-column prop="version_no" label="版本" width="100">
            <template #default="{ row }">{{ row.version_no || '-' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row.release_status)">{{ statusLabel(row.release_status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="agent_description" label="描述" show-overflow-tooltip />
          <el-table-column label="提交时间" width="160">
            <template #default="{ row }">{{ row.updated_at || row.created_at || '-' }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Tab 3: Tool 执行审批 -->
      <el-tab-pane label="Tool 审批" name="toolApprovals" :badge-value="toolPendingCount" :badge="toolPendingCount > 0 ? toolPendingCount : null">
        <el-table :data="toolPendingList" border size="small" v-loading="loadingTool" empty-text="暂无待审批的 Tool 调用" max-height="360">
          <el-table-column prop="dispatch_id" label="审批ID" width="220" show-overflow-tooltip />
          <el-table-column prop="tool_name" label="Tool 名称" width="200" />
          <el-table-column label="风险等级" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="riskTagType(row.risk_level)">{{ riskLabel(row.risk_level) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="tool_args" label="参数" show-overflow-tooltip>
            <template #default="{ row }">
              <code style="font-size: 12px;">{{ formatArgs(row.tool_args) }}</code>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right" v-if="isAdmin">
            <template #default="{ row }">
              <el-button size="small" type="success" @click="toolApprove(row)">通过</el-button>
              <el-button size="small" type="danger" @click="toolReject(row)">拒绝</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { approvalApi, approvalWs, toolApprovalApi } from '../api/index.js'

const isAdmin = computed(() => {
  try { const u = JSON.parse(localStorage.getItem('user_info') || 'null'); return u && u.role === 'admin' } catch { return false }
})

const activeTab = ref('todo')
const loading = ref(false)
const todoList = ref([])
const submissionList = ref([])

// Tool 审批相关
const loadingTool = ref(false)
const toolPendingList = ref([])

const todoCount = computed(() => todoList.value.length)
const submissionCount = computed(() => {
  return submissionList.value.filter(s => String(s.release_status) === '2').length
})
const toolPendingCount = computed(() => toolPendingList.value.length)

// ── Tool 审批函数 ──
const riskLabel = (level) => {
  const map = { read_only: '只读', write_safe: '安全写', destructive: '破坏性', external: '外部通信' }
  return map[level] || level
}
const riskTagType = (level) => {
  const map = { read_only: 'info', write_safe: 'warning', destructive: 'danger', external: 'danger' }
  return map[level] || 'info'
}
const formatArgs = (args) => {
  if (!args) return ''
  try { return JSON.stringify(args) } catch { return String(args) }
}

const loadToolPending = async () => {
  loadingTool.value = true
  try {
    const res = await toolApprovalApi.pending()
    toolPendingList.value = res?.data?.list || []
  } catch { toolPendingList.value = [] }
  finally { loadingTool.value = false }
}

const toolApprove = async (row) => {
  if (!row) return
  try {
    await toolApprovalApi.review(row.dispatch_id, 'approve', '审批通过')
    ElMessage.success(`Tool「${row.tool_name}」已通过`)
    await loadToolPending()
  } catch { ElMessage.error('审批失败') }
}

const toolReject = async (row) => {
  if (!row) return
  try {
    const { value: reason } = await ElMessageBox.prompt('拒绝理由（可选）', '拒绝 Tool 执行', { confirmButtonText: '确认拒绝', cancelButtonText: '取消' })
    await toolApprovalApi.review(row.dispatch_id, 'reject', reason || '审批拒绝')
    ElMessage.success(`Tool「${row.tool_name}」已拒绝`)
    await loadToolPending()
  } catch { /* cancelled */ }
}

// ── 状态映射 ──
const statusLabel = (s) => {
  const map = { '0': '已拒绝', '1': '已通过', '2': '待审批' }
  return map[String(s)] || '草稿'
}
const statusType = (s) => {
  const map = { '0': 'danger', '1': 'success', '2': 'warning' }
  return map[String(s)] || 'info'
}

// ── 数据加载 ──
const loadTodo = async () => {
  try {
    if (isAdmin.value) {
      const res = await approvalApi.pendingReviews()
      todoList.value = res?.list || []
    } else {
      const res = await approvalApi.mySubmissions('2')
      todoList.value = res?.list || []
    }
  } catch { todoList.value = [] }
}

const loadSubmissions = async () => {
  try {
    const res = await approvalApi.mySubmissions('0,1,2')
    submissionList.value = res?.list || []
  } catch { submissionList.value = [] }
}

const refreshAll = async () => {
  loading.value = true
  await Promise.all([loadTodo(), loadSubmissions(), loadToolPending()])
  loading.value = false
}

// ── 审批操作（admin）──
const approve = async (row) => {
  if (!row) return
  try {
    await approvalApi.approve(row.pr_key_id, 'approve')
    ElMessage.success(`${row.agent_name} 审批通过`)
    await refreshAll()
  } catch { ElMessage.error('审批失败') }
}

const reject = async (row) => {
  if (!row) return
  try {
    const { value: reason } = await ElMessageBox.prompt('拒绝理由（可选）', '拒绝审批', { confirmButtonText: '确认拒绝', cancelButtonText: '取消' })
    await approvalApi.approve(row.pr_key_id, 'reject', reason || '审批拒绝')
    ElMessage.success(`${row.agent_name} 已拒绝`)
    await refreshAll()
  } catch { /* cancelled */ }
}

// ── WebSocket 集成 ──
const onWsMessage = (data) => {
  if (data.type === 'approval_result' || data.type === 'new_submission') {
    refreshAll()
  }
}

let pollTimer = null
const startPoll = () => {
  pollTimer = setInterval(refreshAll, 30000)
}

onMounted(() => {
  refreshAll()
  approvalWs.on('approval', onWsMessage)
  approvalWs.connect()
  // 降级：如果 WS 未连接，使用轮询
  setTimeout(() => {
    if (!approvalWs.isConnected()) startPoll()
  }, 3000)
})

onUnmounted(() => {
  approvalWs.off('approval')
  approvalWs.disconnect()
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
})
</script>

<style scoped>
.approval-center {
  margin-top: 0;
}
.section-header {
  display: flex; align-items: baseline; gap: 12px;
  margin-bottom: 4px;
}
.section-title {
  font-size: 18px; font-weight: 700; color: #1E293B; margin: 0;
}
.section-desc {
  font-size: 13px; color: #94A3B8;
}
.approval-tabs {
  margin-top: 4px;
}
</style>
