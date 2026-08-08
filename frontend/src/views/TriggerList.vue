<template>
  <div class="page-container">
    <div class="table-toolbar">
      <span style="font-size: 16px; font-weight: 600;">触发器管理</span>
      <div>
        <el-button @click="loadData">刷新</el-button>
        <el-button type="primary" @click="showCreate">新建</el-button>
      </div>
    </div>

    <el-table :data="list" v-loading="loading" border stripe>
      <el-table-column prop="trigger_id" label="触发器 ID" width="200" />
      <el-table-column prop="trigger_name" label="名称" width="150" />
      <el-table-column prop="trigger_type" label="类型" width="100">
        <template #default="{ row }">
          <el-tag :type="typeTagColor(row.trigger_type)">{{ row.trigger_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="target_mode" label="调度模式" width="100" />
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-switch
            :model-value="row.enabled === '1'"
            @change="(val) => toggleEnabled(row, val)"
          />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="320">
        <template #default="{ row }">
          <el-button size="small" @click="showEdit(row)">编辑</el-button>
          <el-button size="small" type="success" @click="testTrigger(row)">测试</el-button>
          <el-button size="small" type="info" @click="showLogs(row)">日志</el-button>
          <el-button size="small" type="danger" @click="deleteRow(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 创建/编辑弹窗 -->
    <el-dialog v-model="editVisible" :title="editForm.trigger_id ? '编辑触发器' : '新建触发器'" width="720px">
      <el-form :model="editForm" label-width="120px">
        <el-form-item label="触发器 ID">
          <el-input
            v-model="editForm.trigger_id"
            placeholder="TRG_xxx"
            :disabled="!!editForm.trigger_id"
          />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="editForm.trigger_name" />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="editForm.trigger_type">
            <el-radio label="cron">定时 Cron</el-radio>
            <el-radio label="webhook">Webhook</el-radio>
            <el-radio label="file_watch">文件监听</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="目标 Agent IDs">
          <el-input v-model="editForm.target_agent_ids" placeholder="逗号分隔，如 agt_a,agt_b" />
        </el-form-item>
        <el-form-item label="调度模式">
          <el-select v-model="editForm.target_mode">
            <el-option label="并行" value="parallel" />
            <el-option label="顺序" value="sequential" />
            <el-option label="DAG" value="dag" />
          </el-select>
        </el-form-item>
        <el-form-item label="消息模板">
          <el-input
            v-model="editForm.message_template"
            type="textarea"
            :rows="3"
            placeholder="如：生成每日报告，日期：{triggered_at}"
          />
        </el-form-item>
        <el-form-item label="配置 JSON">
          <el-input
            v-model="editForm.config"
            type="textarea"
            :rows="6"
            :placeholder="configPlaceholder"
          />
        </el-form-item>
        <el-form-item label="workspace_id">
          <el-input v-model.number="editForm.workspace_id" type="number" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="saveTrigger" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 日志抽屉/弹窗 -->
    <el-dialog v-model="logsVisible" title="触发器执行历史" width="720px">
      <el-table :data="logs" border>
        <el-table-column prop="log_id" label="日志 ID" width="180" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusColor(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="dispatch_id" label="dispatch_id" width="200" show-overflow-tooltip />
        <el-table-column prop="duration_ms" label="耗时(ms)" width="100" />
        <el-table-column prop="error" label="错误" show-overflow-tooltip />
        <el-table-column prop="create_time" label="触发时间" width="180" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { triggerApi } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const list = ref([])
const loading = ref(false)
const editVisible = ref(false)
const editForm = ref({
  trigger_id: '',
  trigger_name: '',
  trigger_type: 'cron',
  config: '',
  target_agent_ids: '',
  target_mode: 'parallel',
  message_template: '',
  workspace_id: 1,
})
const saving = ref(false)
const logsVisible = ref(false)
const logs = ref([])

// 不同类型的配置 JSON 示例（占位符）
const configPlaceholder = computed(() => {
  switch (editForm.value.trigger_type) {
    case 'cron':
      return '{"cron": "0 9 * * *", "timezone": "Asia/Shanghai"}'
    case 'webhook':
      return '{"secret": "your_hmac_secret", "allowed_ips": ["10.0.0.0/8"]}'
    case 'file_watch':
      return '{"watch_path": "data/knowledge/", "event_types": ["added","modified"], "debounce_ms": 5000, "glob": "*.md"}'
    default:
      return '{}'
  }
})

const typeTagColor = (type) => ({
  cron: 'primary',
  webhook: 'success',
  file_watch: 'warning',
}[type] || 'info')

const statusColor = (status) => ({
  completed: 'success',
  failed: 'danger',
  running: 'primary',
  skipped: 'info',
}[status] || 'info')

const loadData = async () => {
  loading.value = true
  try {
    // 默认 workspace_id=1（多租户前端后续可加切换）
    const data = await triggerApi.list(1)
    list.value = Array.isArray(data) ? data : (data?.triggers || data?.data?.triggers || [])
  } catch (e) {
    ElMessage.warning('加载失败，请确保后端服务已启动')
  } finally {
    loading.value = false
  }
}

const showCreate = () => {
  editForm.value = {
    trigger_id: '',
    trigger_name: '',
    trigger_type: 'cron',
    config: '',
    target_agent_ids: '',
    target_mode: 'parallel',
    message_template: '',
    workspace_id: 1,
  }
  editVisible.value = true
}

const showEdit = (row) => {
  editForm.value = { ...row }
  editVisible.value = true
}

const saveTrigger = async () => {
  saving.value = true
  try {
    if (editForm.value.trigger_id && list.value.find((t) => t.trigger_id === editForm.value.trigger_id)) {
      // 更新
      await triggerApi.update(editForm.value.trigger_id, editForm.value)
      ElMessage.success('更新成功')
    } else {
      // 创建
      await triggerApi.create(editForm.value)
      ElMessage.success('创建成功')
    }
    editVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error('保存失败：' + (e.message || ''))
  } finally {
    saving.value = false
  }
}

const toggleEnabled = async (row, val) => {
  try {
    if (val) {
      await triggerApi.enable(row.trigger_id)
      ElMessage.success('已启用')
    } else {
      await triggerApi.disable(row.trigger_id)
      ElMessage.success('已禁用')
    }
    row.enabled = val ? '1' : '0'
  } catch (e) {
    ElMessage.error('切换失败')
  }
}

const testTrigger = async (row) => {
  try {
    const data = await triggerApi.test(row.trigger_id)
    const logId = data?.log_id || data?.data?.log_id
    ElMessage.success(`已触发，log_id: ${logId}`)
  } catch (e) {
    ElMessage.error('触发失败：' + (e.message || ''))
  }
}

const deleteRow = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除触发器 ${row.trigger_id}?`, '确认', {
      type: 'warning',
    })
    await triggerApi.delete(row.trigger_id)
    ElMessage.success('删除成功')
    loadData()
  } catch (e) {
    if (e === 'cancel' || e?.message === 'cancel') return
    ElMessage.error('删除失败：' + (e.message || ''))
  }
}

const showLogs = async (row) => {
  try {
    const data = await triggerApi.getLogs(row.trigger_id, 50)
    logs.value = Array.isArray(data) ? data : (data?.logs || data?.data?.logs || [])
    logsVisible.value = true
  } catch (e) {
    ElMessage.error('加载日志失败：' + (e.message || ''))
  }
}

onMounted(loadData)
</script>
