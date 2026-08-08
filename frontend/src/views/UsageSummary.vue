<template>
  <el-card shadow="hover">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span>配额状态</span>
        <el-link type="primary" @click="$router.push('/stats/usage')">查看详情 →</el-link>
      </div>
    </template>
    <div v-loading="loading">
      <div v-for="q in quotas" :key="q.quota_type + (q.period || '')" style="margin-bottom: 14px;">
        <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px;">
          <span>{{ q.quota_type }} <span style="color:#999;">({{ q.period }})</span></span>
          <span>{{ q.used_value }} / {{ q.limit_value }}</span>
        </div>
        <el-progress
          :percentage="usagePercent(q)"
          :status="usagePercent(q) >= 90 ? 'exception' : usagePercent(q) >= 70 ? 'warning' : 'success'"
          :stroke-width="14"
        />
      </div>
      <el-empty v-if="!loading && !quotas.length" description="暂无配额记录" :image-size="60" />
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { usageApi } from '../api/index.js'

// 按 workspace 筛选（admin 选用户时传该用户 workspace_id；普通用户传自己；null=当前用户）
const props = defineProps({
  workspaceId: { type: Number, default: null },
})

const quotas = ref([])
const loading = ref(false)
const currentUser = computed(() => {
  try { return JSON.parse(localStorage.getItem('user_info') || 'null') } catch { return null }
})

const usagePercent = (q) => {
  if (!q.limit_value) return 0
  return Math.min(100, Math.round((q.used_value / q.limit_value) * 100))
}

const load = async () => {
  loading.value = true
  try {
    const wsId = props.workspaceId || currentUser.value?.workspace_id || 1
    const res = await usageApi.quota(wsId)
    quotas.value = res?.data?.quotas || res?.quotas || []
  } catch (e) {
    quotas.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.workspaceId, load)
</script>
