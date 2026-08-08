<template>
  <el-card shadow="hover">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span>最近审计日志</span>
        <el-link type="primary" @click="$router.push('/stats/audit')">查看全部 →</el-link>
      </div>
    </template>
    <el-table :data="logs" v-loading="loading" size="small">
      <el-table-column prop="username" label="用户" width="90" />
      <el-table-column prop="resource_type" label="资源" width="90" />
      <el-table-column prop="action" label="操作" width="70" />
      <el-table-column prop="status_code" label="状态" width="60" />
      <el-table-column prop="create_time" label="时间" show-overflow-tooltip />
    </el-table>
    <el-empty v-if="!loading && !logs.length" description="暂无审计记录" :image-size="60" />
  </el-card>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { auditApi } from '../api/index.js'

// 按用户名筛选（admin 选用户时传入；普通用户传入自己的 username；空=全部）
const props = defineProps({
  username: { type: String, default: '' },
})

const logs = ref([])
const loading = ref(false)

const load = async () => {
  loading.value = true
  try {
    const params = { page: 1, page_size: 5 }
    if (props.username) params.username = props.username
    const res = await auditApi.list(params)
    logs.value = res?.data?.logs || res?.logs || []
  } catch (e) {
    logs.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.username, load)
</script>
