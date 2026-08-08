<template>
  <div v-loading="loading">
    <el-card style="margin-bottom: 16px;">
      <template #header>配额状态</template>
      <el-form :inline="true" @submit.prevent="loadAll">
        <el-form-item label="工作空间">
          <el-select v-model="workspaceId" filterable placeholder="选择工作空间" style="width: 240px;" @change="onWorkspaceChange">
            <el-option v-for="ws in workspaceList" :key="ws.workspace_id" :label="ws.name + ' (ID:' + ws.workspace_id + ')'" :value="ws.workspace_id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="loadAll">查询{{ loading ? '中...' : '' }}</el-button>
          <el-button @click="loadPricing">模型单价</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="quotas" border size="small" style="margin-top: 12px;" empty-text="暂无配额记录（新工作空间会自动创建默认配额）">
        <el-table-column prop="quota_type" label="配额类型" width="140" />
        <el-table-column prop="period" label="周期" width="120" />
        <el-table-column prop="used_value" label="已用" width="120" />
        <el-table-column prop="limit_value" label="上限" width="120" />
        <el-table-column label="使用率" width="160">
          <template #default="{ row }">
            <el-progress
              :percentage="usagePercent(row)"
              :status="usagePercent(row) >= 90 ? 'exception' : usagePercent(row) >= 70 ? 'warning' : 'success'"
            />
          </template>
        </el-table-column>
        <el-table-column prop="over_limit_action" label="超限动作" width="100" />
        <el-table-column prop="status" label="状态" width="80" />
      </el-table>
    </el-card>

    <el-card style="margin-bottom: 16px;">
      <template #header>用量明细（按 workspace 聚合）</template>
      <el-table :data="usage" border size="small" empty-text="查询工作空间后显示用量">
        <el-table-column prop="date" label="日期" width="140" />
        <el-table-column prop="total_tokens" label="总 token" width="120" />
        <el-table-column prop="prompt_tokens" label="prompt" width="120" />
        <el-table-column prop="completion_tokens" label="completion" width="120" />
        <el-table-column prop="cost_usd" label="成本($)" width="120" />
        <el-table-column prop="dispatch_count" label="调度数" width="100" />
      </el-table>
    </el-card>

    <el-card>
      <template #header>模型单价表</template>
      <el-table :data="pricingList" border size="small" empty-text="点击'模型单价'按钮加载">
        <el-table-column prop="model" label="模型" width="180" />
        <el-table-column label="输入单价 ($/1k tokens)" width="200">
          <template #default="{ row }">{{ row.input }}</template>
        </el-table-column>
        <el-table-column label="输出单价 ($/1k tokens)" width="200">
          <template #default="{ row }">{{ row.output }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { usageApi } from '../api/index.js'
import { ElMessage } from 'element-plus'

const workspaceId = ref(null)
const workspaceList = ref([])
const quotas = ref([])
const usage = ref([])
const pricingList = ref([])
const loading = ref(false)

const usagePercent = (row) => {
  if (!row.limit_value) return 0
  return Math.min(100, Math.round((row.used_value / row.limit_value) * 100))
}

const loadWorkspaces = async () => {
  try {
    const token = localStorage.getItem('auth_token') || ''
    const res = await fetch('/api/auth/workspaces', { headers: { Authorization: token } })
    const data = await res.json()
    workspaceList.value = data?.list || []
    // 自动选择第一个工作空间
    if (workspaceList.value.length > 0 && !workspaceId.value) {
      workspaceId.value = workspaceList.value[0].workspace_id
    }
  } catch (e) {
    console.log('加载工作空间列表失败')
  }
}

const onWorkspaceChange = () => {
  if (workspaceId.value) loadAll()
}

const loadAll = async () => {
  if (!workspaceId.value) {
    ElMessage.warning('请选择工作空间')
    return
  }
  loading.value = true
  try {
    await Promise.all([loadQuota(), loadWorkspaceUsage()])
  } finally {
    loading.value = false
  }
}

const loadQuota = async () => {
  try {
    const res = await usageApi.quota(workspaceId.value)
    quotas.value = res?.data?.quotas || res?.quotas || []
  } catch (e) {
    ElMessage.error('查询配额失败：' + (e.message || ''))
  }
}

const loadWorkspaceUsage = async () => {
  try {
    const res = await usageApi.workspaceUsage(workspaceId.value, { group_by: 'day' })
    usage.value = res?.data?.usage || res?.usage || []
  } catch (e) {
    ElMessage.error('查询用量失败：' + (e.message || ''))
  }
}

const loadPricing = async () => {
  try {
    const res = await usageApi.pricing()
    const pricing = res?.data?.pricing || res?.pricing || {}
    pricingList.value = Object.entries(pricing).map(([model, p]) => ({
      model,
      input: p.input,
      output: p.output,
    }))
  } catch (e) {
    ElMessage.error('查询单价失败：' + (e.message || ''))
  }
}

onMounted(async () => {
  await loadWorkspaces()
  if (workspaceId.value) loadAll()
  loadPricing()
})
</script>
