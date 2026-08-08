<template>
  <div class="page-container">
    <div class="table-toolbar">
      <span style="font-size: 16px; font-weight: 600;">外部工具管理</span>
      <el-button type="primary" @click="showCreate">新增工具</el-button>
    </div>
    <el-table :data="list" v-loading="loading" border stripe>
      <el-table-column prop="name" label="名称" width="180" />
      <el-table-column prop="display_name" label="显示名" width="150" />
      <el-table-column prop="method" label="方法" width="80" />
      <el-table-column prop="api_base_url" label="API 地址" show-overflow-tooltip />
      <el-table-column prop="api_endpoint" label="端点" width="150" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'danger'">
            {{ row.enabled ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="可见性" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="visTag(row).type" size="small">{{ visTag(row).label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button size="small" @click="showEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row.name)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="formVisible" :title="isEdit ? '编辑工具' : '新增工具'" width="700px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="名称" v-if="!isEdit"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="显示名"><el-input v-model="form.display_name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="API 地址"><el-input v-model="form.api_base_url" /></el-form-item>
        <el-form-item label="API 端点"><el-input v-model="form.api_endpoint" /></el-form-item>
        <el-form-item label="请求方法">
          <el-select v-model="form.method" style="width: 120px;">
            <el-option label="GET" value="GET" />
            <el-option label="POST" value="POST" />
            <el-option label="PUT" value="PUT" />
            <el-option label="DELETE" value="DELETE" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="可见性">
          <el-select v-model="form.visibility" style="width: 200px">
            <el-option label="个人（仅自己可见）" value="private" />
            <el-option label="空间（本空间成员可见）" value="workspace" />
            <el-option label="全局（全系统可见可调度）" value="public" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" @click="save" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { externalToolApi } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const list = ref([])
const loading = ref(false)
const formVisible = ref(false)
const isEdit = ref(false)
const form = ref({})
const saving = ref(false)

const emptyForm = () => ({
  name: '', display_name: '', description: '',
  api_base_url: '', api_endpoint: '', method: 'POST', enabled: true,
  visibility: 'private',
})

// 三层可见性 → 标签（兼容旧 is_public 字段）
const visTag = (row) => {
  const v = row.visibility || (row.is_public === 1 ? 'public' : 'workspace')
  if (v === 'public') return { type: 'success', label: '全局' }
  if (v === 'private') return { type: 'info', label: '个人' }
  return { type: 'warning', label: '空间' }
}

const loadData = async () => {
  loading.value = true
  try {
    const data = await externalToolApi.getList()
    list.value = data?.tools ?? []
  } catch (e) {
    ElMessage.warning('加载失败，请确保后端服务已启动')
  } finally {
    loading.value = false
  }
}

const showCreate = () => {
  isEdit.value = false
  form.value = emptyForm()
  formVisible.value = true
}

const showEdit = (row) => {
  isEdit.value = true
  form.value = {
    ...row,
    visibility: row.visibility || (row.is_public === 1 ? 'public' : 'workspace'),
  }
  formVisible.value = true
}

const save = async () => {
  saving.value = true
  try {
    if (isEdit.value) {
      await externalToolApi.update(form.value.name, form.value)
    } else {
      await externalToolApi.create(form.value)
    }
    ElMessage.success('保存成功')
    formVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const handleDelete = async (name) => {
  try {
    await ElMessageBox.confirm(`确认删除工具 "${name}"？`, '提示', { type: 'warning' })
    await externalToolApi.delete(name)
    ElMessage.success('删除成功')
    loadData()
  } catch {}
}

onMounted(loadData)
</script>
