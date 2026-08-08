<template>
  <div style="padding: 20px;">
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 18px; font-weight: bold;">工作空间管理</span>
          <el-button type="primary" @click="openCreateDialog">新建工作空间</el-button>
        </div>
      </template>
      <el-table :data="workspaces" border size="small">
        <el-table-column prop="workspace_id" label="ID" width="60" />
        <el-table-column prop="name" label="名称" width="150" />
        <el-table-column prop="description" label="描述" show-overflow-tooltip />
        <el-table-column prop="owner_name" label="所有者" width="120" />
        <el-table-column prop="user_count" label="用户数" width="80" />
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'danger'">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="viewUsers(row)">用户</el-button>
            <el-button size="small" @click="openEditDialog(row)">编辑</el-button>
            <el-button size="small" type="danger" :disabled="row.workspace_id === 1" @click="doDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑 dialog -->
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑工作空间' : '新建工作空间'" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item v-if="!editingId" label="所有者">
          <el-select v-model="form.owner_id" placeholder="选择用户" filterable style="width: 100%;">
            <el-option v-for="u in allUsers" :key="u.id" :label="u.username + ' (' + u.id + ')'" :value="u.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="doSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- 空间用户 dialog -->
    <el-dialog v-model="usersVisible" :title="`工作空间「${currentWs?.name}」用户`" width="600px">
      <div style="margin-bottom: 10px;">
        <el-select v-model="bindUserId" placeholder="选择用户" filterable size="small" style="width: 200px;">
          <el-option v-for="u in allUsers" :key="u.id" :label="u.username + ' (' + u.id + ')'" :value="u.id" />
        </el-select>
        <el-checkbox v-model="bindIsOwner" style="margin: 0 8px;">所有者</el-checkbox>
        <el-button size="small" type="primary" @click="doBindUser">绑定</el-button>
      </div>
      <el-table :data="wsUsers" border size="small">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="role" label="角色" width="80" />
        <el-table-column label="所有者" width="80"><template #default="{ row }">{{ row.is_owner ? '是' : '否' }}</template></el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminRbacApi } from '../api/index.js'

const workspaces = ref([])
const dialogVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)
const form = ref({ name: '', description: '', owner_id: null })
const usersVisible = ref(false)
const currentWs = ref(null)
const wsUsers = ref([])
const bindUserId = ref(1)
const bindIsOwner = ref(false)
const allUsers = ref([])

const loadAllUsers = async () => {
  try {
    const res = await adminRbacApi.users()
    allUsers.value = res.list || []
  } catch (e) { console.log('load users failed') }
}

const loadWorkspaces = async () => {
  try {
    const res = await adminRbacApi.workspaces()
    workspaces.value = res.list || []
  } catch (e) { ElMessage.error('加载失败: ' + e.message) }
}

const openCreateDialog = () => {
  editingId.value = null
  form.value = { name: '', description: '', owner_id: null }
  dialogVisible.value = true
}

const openEditDialog = (row) => {
  editingId.value = row.workspace_id
  form.value = { name: row.name, description: row.description, owner_id: row.owner_id }
  dialogVisible.value = true
}

const doSave = async () => {
  if (!form.value.name) { ElMessage.warning('名称必填'); return }
  saving.value = true
  try {
    if (editingId.value) {
      await adminRbacApi.updateWorkspace(editingId.value, { name: form.value.name, description: form.value.description })
    } else {
      await adminRbacApi.createWorkspace(form.value.name, form.value.description, form.value.owner_id)
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    loadWorkspaces()
  } catch (e) { ElMessage.error(e.message) } finally { saving.value = false }
}

const doDelete = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除工作空间「${row.name}」？`, '提示', { type: 'warning' })
    await adminRbacApi.deleteWorkspace(row.workspace_id)
    ElMessage.success('删除成功')
    loadWorkspaces()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e.message || '删除失败') }
}

const viewUsers = async (row) => {
  currentWs.value = row
  usersVisible.value = true
  try {
    const res = await adminRbacApi.workspaceUsers(row.workspace_id)
    wsUsers.value = res.list || []
  } catch (e) { ElMessage.error('获取用户失败: ' + e.message) }
}

const doBindUser = async () => {
  if (!currentWs.value) return
  try {
    await adminRbacApi.bindUser(currentWs.value.workspace_id, bindUserId.value, bindIsOwner.value)
    ElMessage.success('绑定成功')
    const res = await adminRbacApi.workspaceUsers(currentWs.value.workspace_id)
    wsUsers.value = res.list || []
  } catch (e) { ElMessage.error(e.message) }
}

onMounted(() => { loadWorkspaces(); loadAllUsers() })
</script>
