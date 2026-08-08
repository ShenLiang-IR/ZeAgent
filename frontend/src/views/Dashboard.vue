<template>
  <div class="page-container">
    <el-row :gutter="20">
      <el-col :span="6" v-for="card in statCards" :key="card.title">
        <el-card shadow="hover">
          <div style="display: flex; align-items: center; gap: 16px;">
            <el-icon :size="40" :color="card.color">
              <component :is="card.icon" />
            </el-icon>
            <div>
              <div style="font-size: 24px; font-weight: bold;">{{ card.value }}</div>
              <div style="color: #999;">{{ card.title }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card style="margin-top: 20px;" v-loading="loading">
      <template #header>系统信息</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="LLM 模型">{{ config?.llm?.default?.model || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="LLM 地址">{{ config?.llm?.default?.base_url || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="Agent 后端">{{ config?.agent?.backend || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="递归限制">{{ config?.agent?.recursion_limit || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="执行类型">{{ config?.agent?.execution?.type || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="最大并行">{{ config?.agent?.execution?.parallel_tasks?.max_concurrency || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="Checkpoint">{{ config?.checkpoint?.backend || 'memory' }}</el-descriptions-item>
        <el-descriptions-item label="沙箱">{{ config?.sandbox?.enabled ? '已启用' : '未启用' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { systemApi, agentApi, mcpApi, toolApi, skillApi } from '../api'

const config = ref(null)
const loading = ref(true)
const statCards = ref([
  { title: 'Agent 数量', value: '-', icon: 'Monitor', color: '#409EFF' },
  { title: 'MCP 数量', value: '-', icon: 'Connection', color: '#67C23A' },
  { title: '工具数量', value: '-', icon: 'Tools', color: '#E6A23C' },
  { title: 'Skill 数量', value: '-', icon: 'MagicStick', color: '#F56C6C' },
])

onMounted(async () => {
  try {
    config.value = await systemApi.getConfig()
  } catch (e) {
    console.log('Dashboard: config not available (server may be offline)')
  }
  // 获取实际统计数量
  try {
    const d = await agentApi.getList()
    statCards.value[0].value = d?.total ?? d?.agents?.length ?? 0
  } catch (e) {}
  try {
    const d = await mcpApi.page({ pageNum: 1, pageSize: 1 })
    statCards.value[1].value = d?.data?.total ?? d?.data?.list?.length ?? 0
  } catch (e) {}
  try {
    const d = await toolApi.getList()
    statCards.value[2].value = d?.total ?? d?.tools?.length ?? 0
  } catch (e) {}
  try {
    const d = await skillApi.getList()
    statCards.value[3].value = d?.data?.total ?? d?.data?.skills?.length ?? 0
  } catch (e) {}
  loading.value = false
})
</script>
