<template>
  <div class="page-container">
    <div class="table-toolbar">
      <span style="font-size: 16px; font-weight: 600;">可观测性 — Langfuse Tracing</span>
      <el-button type="primary" @click="openExternal">在新窗口打开 Langfuse</el-button>
    </div>
    <el-card style="margin-top: 16px;" v-loading="loading">
      <template #header>最近 Trace（{{ traces.length }}）</template>
      <el-table :data="traces" border size="small">
        <el-table-column prop="timestamp" label="时间" width="180">
          <template #default="{ row }">{{ row.timestamp?.substring(0, 19) }}</template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="200" />
        <el-table-column label="Session" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag v-if="row.session_id" size="small" type="success">{{ row.session_id.substring(0, 20) }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="User" width="120">
          <template #default="{ row }">{{ row.user_id || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" @click="openTrace(row.id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="error" style="color: #f56c6c; margin-top: 8px;">{{ error }}</div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import http from '../api'

const traces = ref([])
const loading = ref(true)
const error = ref('')
const langfuseUrl = ref('http://127.0.0.1:3300')

const openExternal = () => window.open(langfuseUrl.value, '_blank')
const openTrace = (id) => window.open(`${langfuseUrl.value}/trace/${id}`, '_blank')

onMounted(async () => {
  try {
    const cfg = await http.get('/admin/observability/langfuse')
    if (cfg?.data?.host) langfuseUrl.value = cfg.data.host
    const res = await http.get('/admin/observability/langfuse/traces?limit=20')
    traces.value = res?.data?.traces || []
    error.value = res?.data?.error || ''
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
})
</script>
