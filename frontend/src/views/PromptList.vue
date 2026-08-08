<template>
  <div class="page-container">
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span>Prompt 模板管理</span>
          <el-button type="primary" @click="openCreate">新建模板</el-button>
        </div>
      </template>
      <el-table :data="templates" v-loading="loading" border>
        <el-table-column prop="name" label="名称" width="150" />
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column prop="content" label="内容（含 {{var}}）" show-overflow-tooltip />
        <el-table-column prop="description" label="说明" width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="220">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="success" @click="openRender(row)">渲染测试</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑模板' : '新建模板'" width="700px">
      <el-form label-width="100px">
        <el-form-item label="名称"><el-input v-model="form.name" :disabled="editing" placeholder="唯一标识，便于引用" /></el-form-item>
        <el-form-item label="版本"><el-input v-model="form.version" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" /></el-form-item>
        <el-form-item label="内容">
          <el-input type="textarea" v-model="form.content" :rows="8" placeholder="支持 {{var}} 变量占位，如：你好 {{name}}，欢迎来到 {{place}}" />
        </el-form-item>
        <el-form-item label="变量列表">
          <el-input v-model="variablesStr" placeholder="逗号分隔，如 name,place,task" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 渲染测试对话框 -->
    <el-dialog v-model="renderDialogVisible" title="渲染测试" width="700px">
      <el-form label-width="100px">
        <el-form-item label="模板">{{ renderForm.name }}</el-form-item>
        <el-form-item label="变量 JSON">
          <el-input type="textarea" v-model="renderForm.variablesStr" :rows="5" placeholder='{"name":"Alice","task":"coding"}' />
        </el-form-item>
        <el-form-item label="渲染结果">
          <el-input type="textarea" v-model="renderResult" :rows="6" readonly />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renderDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="doRender" :loading="rendering">渲染</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { promptApi } from '../api'
import { ElMessage } from 'element-plus'

const templates = ref([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editing = ref(false)
const form = ref({ name: '', version: '1.0.0', description: '', content: '' })
const variablesStr = ref('')
const renderDialogVisible = ref(false)
const renderForm = ref({ name: '', variablesStr: '{}' })
const renderResult = ref('')
const rendering = ref(false)

const loadData = async () => {
  loading.value = true
  try {
    const res = await promptApi.list()
    templates.value = res.data?.templates || res.templates || []
  } catch (e) {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editing.value = false
  form.value = { name: '', version: '1.0.0', description: '', content: '' }
  variablesStr.value = ''
  dialogVisible.value = true
}

const openEdit = (row) => {
  editing.value = true
  form.value = { ...row, pr_key_id: row.pr_key_id }
  variablesStr.value = (() => {
    try { return JSON.parse(row.variables || '[]').join(',') } catch { return '' }
  })()
  dialogVisible.value = true
}

const save = async () => {
  saving.value = true
  try {
    const variables = variablesStr.value.split(',').map(s => s.trim()).filter(Boolean)
    const params = { ...form.value, variables }
    if (editing.value) {
      await promptApi.update(form.value.pr_key_id, {
        content: params.content, variables: params.variables,
        version: params.version, description: params.description
      })
    } else {
      await promptApi.create(params)
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const openRender = (row) => {
  renderForm.value = { name: row.name, variablesStr: '{}' }
  renderResult.value = ''
  renderDialogVisible.value = true
}

const doRender = async () => {
  rendering.value = true
  try {
    const variables = JSON.parse(renderForm.value.variablesStr || '{}')
    const res = await promptApi.render({ name: renderForm.value.name, variables })
    renderResult.value = res.data?.rendered ?? res.rendered ?? ''
  } catch (e) {
    ElMessage.error('渲染失败：检查 JSON 格式')
  } finally {
    rendering.value = false
  }
}

onMounted(loadData)
</script>
