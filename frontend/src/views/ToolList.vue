<template>
  <div class="page-container">
    <div class="table-toolbar">
      <span style="font-size: 16px; font-weight: 600;">内置工具列表</span>
      <div>
        <el-button @click="restoreAllDefaults" :loading="restoring">恢复全部默认</el-button>
        <el-button type="primary" @click="loadData">刷新</el-button>
      </div>
    </div>
    <el-table :data="list" v-loading="loading" border stripe>
      <el-table-column prop="name" label="工具名称" width="200" />
      <el-table-column prop="description" label="描述" show-overflow-tooltip />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag>{{ row.invoke ? 'LangChain' : 'BaseTool' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="参数数量" width="100" align="center">
        <template #default="{ row }">
          {{ row.parameters?.length || 0 }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button size="small" @click="showDetail(row)">详情</el-button>
          <el-button size="small" @click="restoreDefault(row.name)">恢复默认</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="detailVisible" title="工具详情" width="700px">
      <el-descriptions :column="1" border v-if="detail">
        <el-descriptions-item label="名称">{{ detail.name }}</el-descriptions-item>
        <el-descriptions-item label="显示名">{{ detail.display_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ detail.description }}</el-descriptions-item>
        <el-descriptions-item label="返回类型">{{ detail.return_type || '-' }}</el-descriptions-item>
        <el-descriptions-item label="返回描述">{{ detail.return_description || '-' }}</el-descriptions-item>
        <el-descriptions-item label="参数列表" v-if="detail.parameters?.length">
          <el-table :data="detail.parameters" border size="small">
            <el-table-column prop="name" label="参数名" width="150" />
            <el-table-column prop="type" label="类型" width="100" />
            <el-table-column prop="description" label="描述" show-overflow-tooltip />
            <el-table-column label="必填" width="60" align="center">
              <template #default="{ row }">
                {{ row.required ? '是' : '否' }}
              </template>
            </el-table-column>
          </el-table>
        </el-descriptions-item>
        <el-descriptions-item label="示例" v-if="detail.examples?.length">
          <pre style="white-space: pre-wrap; max-height: 200px; overflow-y: auto;">{{ JSON.stringify(detail.examples, null, 2) }}</pre>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { toolApi } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const list = ref([])
const loading = ref(false)
const detailVisible = ref(false)
const detail = ref(null)
const restoring = ref(false)

const loadData = async () => {
  loading.value = true
  try {
    const data = await toolApi.getList()
    list.value = data?.tools ?? []
  } catch (e) {
    ElMessage.warning('加载失败，请确保后端服务已启动')
  } finally {
    loading.value = false
  }
}

const showDetail = async (row) => {
  try {
    detail.value = await toolApi.getDetail(row.name)
  } catch {
    ElMessage.error('加载详情失败')
    detail.value = row
  }
  detailVisible.value = true
}

const restoreDefault = async (name) => {
  try {
    await ElMessageBox.confirm(`确认恢复工具 "${name}" 的默认配置？`, '提示', { type: 'warning' })
    await toolApi.restoreDefaults(name)
    ElMessage.success('已恢复默认')
    await loadData()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      const msg = e.response?.data?.detail || '操作失败'
      ElMessage.error(msg)
    }
  }
}

const restoreAllDefaults = async () => {
  try {
    await ElMessageBox.confirm('确认恢复所有工具的默认配置？', '提示', { type: 'warning' })
    restoring.value = true
    const res = await toolApi.restoreAllDefaults()
    const failed = res?.failed || []
    if (failed.length > 0) {
      ElMessage.warning(`恢复完成，${res?.restored?.length || 0} 个成功，${failed.length} 个失败`)
    } else {
      ElMessage.success(`全部 ${res?.restored?.length || 0} 个工具已恢复默认`)
    }
    await loadData()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      const msg = e.response?.data?.detail || '操作失败'
      ElMessage.error(msg)
    }
  } finally {
    restoring.value = false
  }
}

onMounted(loadData)
</script>
