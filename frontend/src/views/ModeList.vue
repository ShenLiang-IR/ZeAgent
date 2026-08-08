<template>
  <div class="page-container">
    <div class="table-toolbar">
      <span style="font-size: 16px; font-weight: 600;">模式管理</span>
      <div style="display: flex; gap: 8px;">
        <el-button @click="loadData">刷新</el-button>
        <el-button type="primary" @click="openCreate">新建模式</el-button>
      </div>
    </div>
    <el-table :data="list" v-loading="loading" border stripe>
      <el-table-column prop="mode_name" label="名称" width="180" />
      <el-table-column prop="mode_description" label="描述" show-overflow-tooltip />
      <el-table-column prop="recommended_agents" label="推荐 Agent" width="150" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openPreview(row)">预览</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建/编辑弹窗 -->
    <el-dialog v-model="formVisible" :title="editing ? '编辑模式' : '新建模式'" width="640px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="名称" required>
          <el-input v-model="form.mode_name" :disabled="editing" placeholder="如 concise" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.mode_description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="Prompt 后缀" required>
          <el-input v-model="form.system_prompt" type="textarea" :rows="5" placeholder="追加到 system_prompt 的模式指引" />
        </el-form-item>
        <el-form-item label="推荐 Agent">
          <el-input v-model="form.recommended_agents" placeholder="推荐使用的 Agent（逗号分隔）" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 预览弹窗 -->
    <el-dialog v-model="previewVisible" title="模式预览" width="640px">
      <el-form label-width="120px">
        <el-form-item label="Prompt 后缀">
          <el-input v-model="previewForm.system_prompt_suffix" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="测试文本" required>
          <el-input v-model="previewForm.test_text" type="textarea" :rows="3" placeholder="输入测试文本" />
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="previewing" @click="runPreview" style="margin-bottom: 12px;">执行预览</el-button>
      <el-divider />
      <div v-if="previewResult" style="background: #F1F5F9; padding: 12px; border-radius: 4px; white-space: pre-wrap;">{{ previewResult }}</div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { modeApi } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const list = ref([])
const loading = ref(false)
const formVisible = ref(false)
const editing = ref(false)
const saving = ref(false)
const form = ref({})
const previewVisible = ref(false)
const previewing = ref(false)
const previewForm = ref({ system_prompt_suffix: '', test_text: '' })
const previewResult = ref('')

const loadData = async () => {
  loading.value = true
  try {
    const data = await modeApi.getList()
    list.value = data?.data?.modes || data?.modes || []
  } catch (e) {
    ElMessage.warning('加载失败，请确保后端服务已启动')
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editing.value = false
  form.value = { mode_name: '', mode_description: '', system_prompt: '', recommended_agents: '', enabled: true }
  formVisible.value = true
}

const openEdit = (row) => {
  editing.value = true
  form.value = { ...row }
  formVisible.value = true
}

const save = async () => {
  if (!form.value.mode_name || !form.value.system_prompt) {
    ElMessage.warning('请填写名称和 Prompt 后缀')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await modeApi.update(form.value.mode_name, form.value)
    } else {
      await modeApi.create(form.value)
    }
    ElMessage.success(editing.value ? '更新成功' : '创建成功')
    formVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    saving.value = false
  }
}

const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除模式 "${row.mode_name}"？`, '提示', { type: 'warning' })
    await modeApi.delete(row.mode_name)
    ElMessage.success('删除成功')
    loadData()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error('删除失败')
  }
}

const openPreview = (row) => {
  previewForm.value = { system_prompt_suffix: row.system_prompt || '', test_text: '' }
  previewResult.value = ''
  previewVisible.value = true
}

const runPreview = async () => {
  if (!previewForm.value.test_text.trim() || !previewForm.value.system_prompt_suffix.trim()) {
    ElMessage.warning('请填写 Prompt 后缀和测试文本')
    return
  }
  previewing.value = true
  previewResult.value = ''
  try {
    const data = await modeApi.preview(previewForm.value)
    previewResult.value = data?.data?.response || data?.response || JSON.stringify(data)
  } catch (e) {
    previewResult.value = '[错误] ' + (e.response?.data?.detail || e.message)
  } finally {
    previewing.value = false
  }
}

onMounted(loadData)
</script>
