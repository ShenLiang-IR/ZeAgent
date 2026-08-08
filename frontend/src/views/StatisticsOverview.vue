<template>
  <div class="page-container">
    <!-- 用户筛选（admin 可见，跨 tab 影响 配额；普通用户看自己）-->
    <div v-if="isAdmin" style="margin-bottom: 16px; display: flex; align-items: center; gap: 12px;">
      <span style="color: #64748B;">按用户筛选：</span>
      <el-select v-model="selectedUserId" placeholder="全部用户" clearable style="width: 220px;" @change="onUserChange">
        <el-option label="全部用户（admin 视角）" value="" />
        <el-option v-for="u in userList" :key="u.id" :label="u.username + (u.role === 'admin' ? ' (admin)' : '')" :value="String(u.id)" />
      </el-select>
      <span v-if="selectedUserId" style="color: #999; font-size: 13px;">当前筛选：{{ userList.find(u => String(u.id) === selectedUserId)?.username }}</span>
    </div>
    <div v-else style="margin-bottom: 16px; color: #999; font-size: 13px;">
      我的统计（{{ currentUser?.username }}）
    </div>

    <!-- tab 布局：工具链 / 审计 / 配额 -->
    <el-tabs v-model="activeTab">
      <!-- 工具链：资源数量统计 -->
      <el-tab-pane label="工具链" name="toolchain">
        <el-row :gutter="20" v-loading="loading">
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
        <el-card style="margin-top: 20px;" shadow="never">
          <template #header>说明</template>
          <div style="color: #64748B; font-size: 13px; line-height: 1.8;">
            工具链统计展示当前可用的 Agent / MCP / 工具 / Skill 数量。<br/>
            普通用户查看自己工作空间资源，admin 默认查看全部（可切换工作空间查看不同空间资源）。
          </div>
        </el-card>
      </el-tab-pane>

      <!-- 审计：5 维度报表饼图（admin） -->
      <el-tab-pane v-if="isAdmin" label="审计" name="audit">
        <AuditReport />
      </el-tab-pane>

      <!-- 配额：配额使用进度（admin） -->
      <el-tab-pane v-if="isAdmin" label="配额" name="quota">
        <UsageSummary :workspace-id="filterWorkspaceId" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { agentApi, mcpApi, toolApi, skillApi, adminRbacApi } from '../api/index.js'
import AuditReport from './AuditReport.vue'
import UsageSummary from './UsageSummary.vue'

const activeTab = ref('toolchain')
const loading = ref(true)

// 用户筛选（admin 可选用户看其统计，普通用户固定看自己）
const isAdmin = computed(() => {
  try { const u = JSON.parse(localStorage.getItem('user_info') || 'null'); return u?.role === 'admin' } catch { return false }
})
const currentUser = computed(() => {
  try { return JSON.parse(localStorage.getItem('user_info') || 'null') } catch { return null }
})
const userList = ref([])
const selectedUserId = ref('')  // '' = 全部用户
const filterWorkspaceId = ref(null)  // 传给 UsageSummary

const loadUsers = async () => {
  if (!isAdmin.value) return
  try {
    const res = await adminRbacApi.users()
    userList.value = res?.data?.users || res?.users || res?.list || []
  } catch (e) {
    userList.value = []
  }
}

const onUserChange = (val) => {
  if (!val) {
    filterWorkspaceId.value = null  // 全部用户
  } else {
    const u = userList.value.find(x => String(x.id) === val)
    filterWorkspaceId.value = u?.workspace_id || null
  }
}

const statCards = ref([
  { title: 'Agent 数量', value: '-', icon: 'Monitor', color: '#409EFF' },
  { title: 'MCP 数量', value: '-', icon: 'Connection', color: '#67C23A' },
  { title: '工具数量', value: '-', icon: 'Tools', color: '#E6A23C' },
  { title: 'Skill 数量', value: '-', icon: 'MagicStick', color: '#F56C6C' },
])

// 加载工具链统计（响应 filterWorkspaceId 变化重新加载，支持按用户筛选）
const loadToolchain = async () => {
  loading.value = true
  statCards.value.forEach(c => { c.value = '-' })
  // null（全部用户）→ undefined：axios 忽略，后端 None=全部空间聚合
  const ws = filterWorkspaceId.value || undefined
  try {
    const d = await agentApi.getList({ workspace_id: ws, skip: 0, limit: 1 })
    statCards.value[0].value = d?.total ?? d?.agents?.length ?? 0
  } catch (e) {}
  try {
    const d = await mcpApi.page({ pageNo: 1, pageSize: 1 }, ws ? { params: { workspace_id: ws } } : undefined)
    statCards.value[1].value = d?.data?.total ?? d?.data?.list?.length ?? 0
  } catch (e) {}
  try {
    // 工具数量 = 该空间 Agent 绑定的去重外部工具数（T-A 方案）
    const d = await toolApi.getStats(filterWorkspaceId.value)
    statCards.value[2].value = d?.data?.total ?? 0
  } catch (e) {}
  try {
    const d = await skillApi.getList({ workspace_id: ws })
    statCards.value[3].value = d?.data?.total ?? d?.data?.skills?.length ?? 0
  } catch (e) {}
  loading.value = false
}

// admin 切换用户 / 普通用户首次设值时，filterWorkspaceId 变化 → 重新加载
watch(filterWorkspaceId, () => { loadToolchain() })

onMounted(async () => {
  // 普通用户：固定看自己统计（设值会触发 watch 自动加载）；admin：加载用户列表后手动加载（filterWorkspaceId 保持 null=全部用户）
  if (!isAdmin.value) {
    filterWorkspaceId.value = currentUser.value?.workspace_id || 1
  } else {
    await loadUsers()
    await loadToolchain()
  }
})
</script>
