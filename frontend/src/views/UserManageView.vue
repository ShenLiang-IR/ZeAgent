<template>
  <div style="padding: 20px;">
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 18px; font-weight: bold;">用户与权限管理</span>
          <el-button type="warning" @click="changePwdVisible = true">修改密码</el-button>
        </div>
      </template>
      <el-tabs v-model="activeTab">
        <!-- Tab 1: 用户管理 -->
        <el-tab-pane label="用户管理" name="users">
          <div style="margin: 10px 0;">
            <el-button type="primary" size="small" @click="openUserDialog()">新增用户</el-button>
          </div>
          <el-table :data="users" border size="small">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="username" label="用户名" width="120" />
            <el-table-column prop="phone" label="手机号" width="130" />
            <el-table-column prop="role" label="角色" width="80" />
            <el-table-column prop="status" label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.status === 'active' ? 'success' : 'danger'">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="工作空间" width="120">
              <template #default="{ row }">
                {{ workspaces.find(w => w.workspace_id === row.workspace_id)?.name || row.workspace_id }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="240">
              <template #default="{ row }">
                <el-button size="small" @click="openUserDialog(row)">编辑</el-button>
                <el-button size="small" :type="row.status === 'active' ? 'danger' : 'success'" @click="toggleStatus(row)">
                  {{ row.status === 'active' ? '禁用' : '启用' }}
                </el-button>
                <el-button size="small" type="danger" @click="doDeleteUser(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- Tab 2: 用户角色管理 -->
        <el-tab-pane label="用户角色管理" name="userRoles">
          <div style="margin: 15px 0;">
            <span>选择用户：</span>
            <el-select v-model="selectedUserId" placeholder="选择用户" filterable style="width: 200px;" @change="loadUserRoles">
              <el-option v-for="u in users" :key="u.id" :label="u.username + ' (' + u.id + ')'" :value="u.id" />
            </el-select>
          </div>
          <div v-if="selectedUserId" style="margin: 15px 0;">
            <span>角色（勾选分配）：</span>
            <div style="margin-top: 10px;">
              <el-checkbox v-for="r in roles" :key="r.role_id" v-model="r._checked" style="margin: 8px 20px;" @change="onRoleToggle(r)">
                {{ r.role_name }} ({{ r.role_code }})
              </el-checkbox>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 3: 用户权限管理（角色权限勾选） -->
        <el-tab-pane label="用户权限管理" name="rolePerms">
          <div style="margin: 15px 0; display: flex; align-items: center; gap: 10px;">
            <span>选择角色：</span>
            <el-select v-model="selectedRoleId" placeholder="选择角色" style="width: 200px;" @change="loadRolePermissions">
              <el-option v-for="r in roles" :key="r.role_id" :label="r.role_name + ' (' + r.role_code + ')' + (r.is_system ? ' [系统]' : '')" :value="r.role_id" />
            </el-select>
            <el-button type="primary" size="small" @click="openRoleDialog()">新建角色</el-button>
            <el-button size="small" @click="openRoleDialog(currentRole)" :disabled="!currentRole">编辑角色</el-button>
            <el-button type="danger" size="small" @click="doDeleteRole" :disabled="!currentRole || currentRole?.is_system">删除角色</el-button>
          </div>
          <div v-if="selectedRoleId && groupedPermissions.length" style="margin-top: 15px;">
            <div v-for="group in groupedPermissions" :key="group.type" style="margin-bottom: 15px;">
              <div style="font-weight: bold; margin-bottom: 8px; color: #409eff;">{{ group.type }}</div>
              <el-checkbox v-for="p in group.perms" :key="p.permission_id" v-model="p._checked" style="margin: 6px 20px;" @change="onPermToggle(p)">
                {{ p.domain }} ({{ p.permission_code }})
              </el-checkbox>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 修改密码 dialog -->
    <el-dialog v-model="changePwdVisible" title="修改密码" width="400px">
      <el-form label-width="100px">
        <el-form-item label="旧密码"><el-input v-model="pwdForm.old" type="password" show-password /></el-form-item>
        <el-form-item label="新密码"><el-input v-model="pwdForm.new" type="password" show-password /></el-form-item>
        <el-form-item label="确认密码"><el-input v-model="pwdForm.confirm" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="changePwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdLoading" @click="doChangePassword">确认</el-button>
      </template>
    </el-dialog>

    <!-- 用户新建/编辑 dialog -->
    <el-dialog v-model="userDialogVisible" :title="editingUserId ? '编辑用户' : '新建用户'" width="500px">
      <el-form :model="userForm" label-width="100px">
        <el-form-item label="用户名">
          <el-input v-model="userForm.username" :disabled="editingUserId !== null" placeholder="创建后不可改" />
        </el-form-item>
        <el-form-item label="手机号"><el-input v-model="userForm.phone" /></el-form-item>
        <el-form-item v-if="!editingUserId" label="密码">
          <el-input v-model="userForm.password" type="password" placeholder="初始密码" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="userForm.role" style="width: 100%;">
            <el-option label="普通用户 (user)" value="user" />
            <el-option label="管理员 (admin)" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="工作空间">
          <el-select v-model="userForm.workspace_id" placeholder="选择工作空间" style="width: 100%;">
            <el-option v-for="ws in workspaces" :key="ws.workspace_id" :label="ws.name" :value="ws.workspace_id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveUser" :loading="userSaving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 角色新建/编辑 dialog -->
    <el-dialog v-model="roleDialogVisible" :title="editingRoleId ? '编辑角色' : '新建角色'" width="450px">
      <el-form :model="roleForm" label-width="90px">
        <el-form-item label="角色名称"><el-input v-model="roleForm.role_name" placeholder="如：数据分析师" /></el-form-item>
        <el-form-item label="角色代码"><el-input v-model="roleForm.role_code" placeholder="如：data_analyst" :disabled="!!editingRoleId" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="roleForm.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="roleSaving" @click="doSaveRole">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { adminRbacApi, authApi } from '../api/index.js'

const activeTab = ref('users')
const users = ref([])

// 用户管理（新增/编辑/删除）
const userDialogVisible = ref(false)
const editingUserId = ref(null)
const userSaving = ref(false)
const userForm = ref({ username: '', phone: '', password: '', role: 'user', workspace_id: 1 })
const workspaces = ref([])  // 工作空间列表（用于名称选择）
const roles = ref([])
const permissions = ref([])
const selectedUserId = ref(null)
const selectedRoleId = ref(null)
const currentRole = ref(null)
const changePwdVisible = ref(false)
const pwdLoading = ref(false)
const pwdForm = ref({ old: '', new: '', confirm: '' })
const roleDialogVisible = ref(false)
const editingRoleId = ref(null)
const roleSaving = ref(false)
const roleForm = ref({ role_name: '', role_code: '', description: '' })

// 按 resource_type 分组的权限
const groupedPermissions = computed(() => {
  const groups = {}
  for (const p of permissions.value) {
    const t = p.resource_type
    if (!groups[t]) groups[t] = { type: t, perms: [] }
    groups[t].perms.push(p)
  }
  return Object.values(groups)
})

const loadUsers = async () => {
  try {
    const res = await adminRbacApi.users()
    users.value = res.list || []
  } catch (e) { ElMessage.error('加载用户失败: ' + e.message) }
}

const loadWorkspaces = async () => {
  try {
    const res = await adminRbacApi.workspaces()
    workspaces.value = res.list || []
  } catch (e) { /* 降级，不影响主流程 */ }
}

const loadRoles = async () => {
  try {
    const res = await adminRbacApi.roles()
    roles.value = (res.list || []).map(r => ({ ...r, _checked: false }))
  } catch (e) { ElMessage.error('加载角色失败: ' + e.message) }
}

const loadPermissions = async () => {
  try {
    const res = await adminRbacApi.permissions()
    permissions.value = (res.list || []).map(p => ({ ...p, _checked: false }))
  } catch (e) { ElMessage.error('加载权限失败: ' + e.message) }
}

// Tab 2: 加载用户当前角色，勾选
const loadUserRoles = async () => {
  if (!selectedUserId.value) return
  try {
    const res = await adminRbacApi.userPermissions(selectedUserId.value)
    const userRoles = res.roles || []
    roles.value.forEach(r => { r._checked = userRoles.includes(r.role_code) })
  } catch (e) { ElMessage.error('加载用户角色失败: ' + e.message) }
}

// Tab 2: 勾选/取消角色
const onRoleToggle = async (role) => {
  if (!selectedUserId.value) return
  try {
    if (role._checked) {
      await adminRbacApi.assignRole(selectedUserId.value, role.role_code, 1)
      ElMessage.success('已分配角色: ' + role.role_name)
    } else {
      await adminRbacApi.removeRole(selectedUserId.value, role.role_code)
      ElMessage.success('已移除角色: ' + role.role_name)
    }
  } catch (e) { ElMessage.error(e.message); role._checked = !role._checked }
}

// Tab 3: 加载角色当前权限，勾选
const loadRolePermissions = async () => {
  if (!selectedRoleId.value) return
  // 设置 currentRole
  currentRole.value = roles.value.find(r => r.role_id === selectedRoleId.value) || null
  try {
    const res = await adminRbacApi.rolePermissions(selectedRoleId.value)
    const rolePermIds = (res.list || []).map(p => p.permission_id)
    permissions.value.forEach(p => { p._checked = rolePermIds.includes(p.permission_id) })
  } catch (e) { ElMessage.error('加载角色权限失败: ' + e.message) }
}

// 角色新建/编辑
const openRoleDialog = (role = null) => {
  if (role) {
    editingRoleId.value = role.role_id
    roleForm.value = { role_name: role.role_name, role_code: role.role_code, description: role.description || '' }
  } else {
    editingRoleId.value = null
    roleForm.value = { role_name: '', role_code: '', description: '' }
  }
  roleDialogVisible.value = true
}

const doSaveRole = async () => {
  if (!roleForm.value.role_name || !roleForm.value.role_code) {
    ElMessage.warning('角色名称和代码必填'); return
  }
  roleSaving.value = true
  try {
    if (editingRoleId.value) {
      await adminRbacApi.updateRole(editingRoleId.value, { role_name: roleForm.value.role_name, description: roleForm.value.description })
    } else {
      await adminRbacApi.createRole(roleForm.value.role_name, roleForm.value.role_code, roleForm.value.description)
    }
    ElMessage.success('保存成功')
    roleDialogVisible.value = false
    await loadRoles()
  } catch (e) { ElMessage.error(e.message) } finally { roleSaving.value = false }
}

const doDeleteRole = async () => {
  if (!currentRole.value || currentRole.value.is_system) return
  try {
    const { ElMessageBox } = await import('element-plus')
    await ElMessageBox.confirm(`确认删除角色「${currentRole.value.role_name}」？`, '提示', { type: 'warning' })
    await adminRbacApi.deleteRole(currentRole.value.role_id)
    ElMessage.success('删除成功')
    selectedRoleId.value = null
    currentRole.value = null
    await loadRoles()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e.message || '删除失败') }
}

// Tab 3: 勾选/取消权限
const onPermToggle = async (perm) => {
  if (!selectedRoleId.value) return
  try {
    if (perm._checked) {
      await adminRbacApi.assignPermission(selectedRoleId.value, perm.permission_id)
      ElMessage.success('已分配权限: ' + perm.permission_code)
    } else {
      await adminRbacApi.removePermission(selectedRoleId.value, perm.permission_id)
      ElMessage.success('已移除权限: ' + perm.permission_code)
    }
  } catch (e) { ElMessage.error(e.message); perm._checked = !perm._checked }
}

// Tab 1: 切换用户状态
const toggleStatus = async (row) => {
  try {
    await adminRbacApi.updateStatus(row.id, row.status === 'active' ? 'disabled' : 'active')
    ElMessage.success('状态已更新')
    loadUsers()
  } catch (e) { ElMessage.error(e.message) }
}

// 用户新增/编辑/删除
const openUserDialog = (row = null) => {
  if (row) {
    editingUserId.value = row.id
    userForm.value = { username: row.username, phone: row.phone, password: '', role: row.role, workspace_id: row.workspace_id || 1 }
  } else {
    editingUserId.value = null
    userForm.value = { username: '', phone: '', password: '', role: 'user', workspace_id: 1 }
  }
  userDialogVisible.value = true
}

const saveUser = async () => {
  if (!userForm.value.username || !userForm.value.phone) { ElMessage.warning('用户名和手机号必填'); return }
  if (!editingUserId.value && !userForm.value.password) { ElMessage.warning('请输入初始密码'); return }
  userSaving.value = true
  try {
    if (editingUserId.value) {
      await adminRbacApi.updateUser(editingUserId.value, {
        phone: userForm.value.phone,
        role: userForm.value.role,
        workspace_id: userForm.value.workspace_id,
      })
      ElMessage.success('更新成功')
    } else {
      await adminRbacApi.createUser({
        username: userForm.value.username,
        phone: userForm.value.phone,
        password: userForm.value.password,
        role: userForm.value.role,
        workspace_id: userForm.value.workspace_id,
      })
      ElMessage.success('创建成功')
    }
    userDialogVisible.value = false
    loadUsers()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    userSaving.value = false
  }
}

const doDeleteUser = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除用户「${row.username || row.phone}」？此操作不可恢复`, '提示', { type: 'warning' })
    await adminRbacApi.deleteUser(row.id)
    ElMessage.success('删除成功')
    loadUsers()
  } catch (e) { if (e !== 'cancel') ElMessage.error(e.message || '删除失败') }
}

// 修改密码
const doChangePassword = async () => {
  if (pwdForm.value.new !== pwdForm.value.confirm) { ElMessage.error('两次密码不一致'); return }
  pwdLoading.value = true
  try {
    await authApi.changePassword(pwdForm.value.old, pwdForm.value.new)
    ElMessage.success('密码修改成功')
    changePwdVisible.value = false
    pwdForm.value = { old: '', new: '', confirm: '' }
  } catch (e) { ElMessage.error(e.message) } finally { pwdLoading.value = false }
}

onMounted(() => { loadUsers(); loadWorkspaces(); loadRoles(); loadPermissions() })
</script>
