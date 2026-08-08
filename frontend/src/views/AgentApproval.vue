<template>
  <div class="page-container">
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span>Agent 审批列表（{{ total }} 个待审批）</span>
          <el-button @click="loadPending" :loading="loading">刷新</el-button>
        </div>
      </template>
      <el-table :data="items" border size="small" v-loading="loading" empty-text="暂无待审批 Agent">
        <el-table-column prop="agent_name" label="Agent 名称" width="180" />
        <el-table-column prop="agent_description" label="描述" show-overflow-tooltip />
        <el-table-column label="模型" width="140">
          <template #default="{ row }">{{ row.model_id || '-' }}</template>
        </el-table-column>
        <el-table-column label="工作空间" width="100">
          <template #default="{ row }">{{ row.workspace_id || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="success" @click="approve(row)">通过</el-button>
            <el-button size="small" type="danger" @click="reject(row)">拒绝</el-button>
            <el-button size="small" @click="showDetail = row; detailVisible = true">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="detailVisible" title="Agent 详情" width="600px">
      <el-descriptions v-if="showDetail" :column="1" border>
        <el-descriptions-item label="名称">{{ showDetail.agent_name }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ showDetail.agent_description || '-' }}</el-descriptions-item>
        <el-descriptions-item label="模型">{{ showDetail.model_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="提示词">
          <pre style="max-height: 200px; overflow: auto; white-space: pre-wrap;">{{ showDetail.system_prompt || '-' }}</pre>
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button type="success" @click="approve(showDetail); detailVisible = false">通过</el-button>
        <el-button type="danger" @click="reject(showDetail); detailVisible = false">拒绝</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const items = ref([])
const total = ref(0)
const loading = ref(false)
const detailVisible = ref(false)
const showDetail = ref(null)

const loadPending = async () => {
  loading.value = true
  try {
    const token = localStorage.getItem('auth_token') || ''
    const res = await fetch('/api/admin/agents/pending-reviews', { headers: { Authorization: token } })
    const data = await res.json()
    items.value = data?.list || []
    total.value = data?.total || 0
  } finally {
    loading.value = false
  }
}

const approve = async (row) => {
  if (!row) return
  const token = localStorage.getItem('auth_token') || ''
  try {
    await fetch(`/api/admin/agents/${row.pr_key_id}/approve`, {
      method: 'POST',
      headers: { Authorization: token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'approve', reason: '' })
    })
    ElMessage.success(`${row.agent_name} 审批通过`)
    await loadPending()
  } catch (e) {
    ElMessage.error('审批失败')
  }
}

const reject = async (row) => {
  if (!row) return
  try {
    const { value: reason } = await ElMessageBox.prompt('拒绝理由（可选）', '拒绝审批', { confirmButtonText: '确认拒绝', cancelButtonText: '取消' })
    const token = localStorage.getItem('auth_token') || ''
    await fetch(`/api/admin/agents/${row.pr_key_id}/approve`, {
      method: 'POST',
      headers: { Authorization: token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'reject', reason: reason || '审批拒绝' })
    })
    ElMessage.success(`${row.agent_name} 已拒绝`)
    await loadPending()
  } catch { /* cancelled */ }
}

onMounted(loadPending)
</script>
