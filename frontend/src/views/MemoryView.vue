<template>
  <div style="padding: 16px;">
    <el-tabs v-model="activeTab" type="border-card">
      <!-- 概览 -->
      <el-tab-pane label="概览" name="overview">
        <div style="display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px;">
          <el-card v-for="c in statCards" :key="c.label" shadow="hover" style="min-width: 140px;">
            <div style="color: #64748B; font-size: 13px;">{{ c.label }}</div>
            <div style="font-size: 26px; font-weight: 600; color: #1d4ed8; margin-top: 4px;">{{ c.value }}</div>
          </el-card>
        </div>

        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px;">
          <span style="font-weight: 600;">定时任务</span>
          <el-button type="primary" size="small" :loading="consolidating" @click="doConsolidate">
            手动触发合并
          </el-button>
          <el-button size="small" @click="loadOverview">刷新</el-button>
        </div>
        <el-table :data="cronJobs" border size="small" style="width: 100%;">
          <el-table-column prop="name" label="任务" min-width="180" />
          <el-table-column label="启用" width="90">
            <template #default="{ row }">
              <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '开' : '关' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="cron" label="Cron" width="140" />
        </el-table>

        <el-collapse style="margin-top: 16px;">
          <el-collapse-item title="配置快照（只读，改 config/agent_config.json 后重启生效）" name="cfg">
            <pre style="background: #F1F5F9; padding: 12px; border-radius: 4px; font-size: 12px; overflow: auto;">{{ JSON.stringify(configSnap, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </el-tab-pane>

      <!-- 浏览 -->
      <el-tab-pane label="浏览" name="browse">
        <el-form :inline="true" style="margin-bottom: 12px;">
          <el-form-item label="用户">
            <el-select v-model="filters.user_id" filterable clearable placeholder="选择用户" style="width: 160px;">
              <el-option v-for="u in userList" :key="u.id" :label="u.username" :value="String(u.id)" />
            </el-select>
          </el-form-item>
          <el-form-item label="记忆层">
            <el-select v-model="filters.tier" style="width: 120px;" @change="onTierChange">
              <el-option label="瞬时记忆" value="immediate" />
              <el-option label="短期记忆" value="short_term" />
              <el-option label="长期记忆" value="long_term" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="workspaceList.length" label="空间">
            <el-select v-model="filters.workspace_id" clearable placeholder="全部空间" style="width: 160px;" @change="onTierChange">
              <el-option v-for="w in workspaceList" :key="w.workspace_id" :label="w.name || ('空间 ' + w.workspace_id)" :value="String(w.workspace_id)" />
            </el-select>
          </el-form-item>
          <el-form-item label="会话">
            <el-input v-model="filters.session_id" placeholder="session_id" clearable style="width: 140px;" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="filters.mtype" placeholder="全部" clearable style="width: 130px;">
              <el-option v-for="t in types" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
          <el-form-item label="关键词">
            <el-input v-model="filters.q" placeholder="content 子串" clearable style="width: 160px;" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="loadList">查询</el-button>
            <el-button @click="resetFilters">重置</el-button>
            <el-button type="danger" :disabled="!filters.user_id" @click="clearUser">清空该用户</el-button>
          </el-form-item>
        </el-form>

        <el-table :data="list" v-loading="listLoading" border size="small" style="width: 100%;">
          <el-table-column label="内容" min-width="240">
            <template #default="{ row }">
              <span>{{ row.content }}</span>
              <el-tag v-if="row.metadata && row.metadata.conflict_decision" size="small" type="warning" style="margin-left: 6px;">
                {{ row.metadata.conflict_decision }} ← {{ (row.metadata.conflict_merged_from || '').slice(0, 8) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="type" label="类型" width="100" />
          <el-table-column label="重要度" width="80">
            <template #default="{ row }">{{ (row.importance ?? 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="用户" width="110">
            <template #default="{ row }">{{ resolveUsername(row.user_id) }}</template>
          </el-table-column>
          <el-table-column label="创建" width="160">
            <template #default="{ row }">{{ fmt(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" @click="doDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          style="margin-top: 12px; justify-content: flex-end; display: flex;"
          v-model:current-page="page.current"
          :page-size="page.size"
          :total="page.total"
          layout="total, prev, pager, next"
          @current-change="loadList"
        />
      </el-tab-pane>

      <!-- 召回试用 -->
      <el-tab-pane label="召回试用" name="recall">
        <el-form :inline="true" style="margin-bottom: 12px;">
          <el-form-item label="查询">
            <el-input v-model="recall.query" placeholder="如：用户偏好" style="width: 240px;" />
          </el-form-item>
          <el-form-item label="用户">
            <el-select v-model="recall.user_id" filterable clearable placeholder="选择用户" style="width: 160px;">
              <el-option v-for="u in userList" :key="u.id" :label="u.username" :value="String(u.id)" />
            </el-select>
          </el-form-item>
          <el-form-item label="条数">
            <el-input-number v-model="recall.limit" :min="1" :max="50" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="recallLoading" @click="doRecall">召回</el-button>
          </el-form-item>
        </el-form>
        <el-table :data="recallResults" border size="small">
          <el-table-column label="内容" min-width="240"><template #default="{ row }">{{ row.content }}</template></el-table-column>
          <el-table-column prop="type" label="类型" width="100" />
          <el-table-column label="重要度" width="80"><template #default="{ row }">{{ (row.importance ?? 0).toFixed(2) }}</template></el-table-column>
          <el-table-column label="用户" width="110">
            <template #default="{ row }">{{ resolveUsername(row.user_id) }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!recallLoading && !recallResults.length" description="输入查询词后召回" />
      </el-tab-pane>

      <!-- 配置 -->
      <el-tab-pane label="配置" name="config">
        <el-alert type="info" :closable="false" style="margin-bottom: 12px;">
          运行时配置当前只读。修改 <code>config/agent_config.json</code> 的 <code>memory</code> 段后重启生效；冲突检测/合并/召回阈值在此查看。
        </el-alert>
        <pre style="background: #F1F5F9; padding: 12px; border-radius: 4px; font-size: 12px; overflow: auto;">{{ JSON.stringify(configSnap, null, 2) }}</pre>
      </el-tab-pane>
    </el-tabs>

    <!-- 编辑弹窗 -->
    <el-dialog v-model="editVisible" title="编辑记忆" width="560px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="内容">
          <el-input v-model="editForm.content" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="重要度">
          <el-input-number v-model="editForm.importance" :min="0" :max="1" :step="0.1" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="doSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http, { memoryApi } from '../api/index.js'

const activeTab = ref('overview')

// 用户列表（用于按用户名联想筛选）
const userList = ref([])
const loadUsers = async () => {
  try {
    const res = await http.get('/admin/users')
    const d = res.data || res
    userList.value = d.list || d.users || (Array.isArray(d) ? d : [])
  } catch (e) {
    console.log('Users load failed:', e.message || '')
  }
}

// 概览
const stats = ref({})
const cronJobs = ref([])
const configSnap = ref({})
const consolidating = ref(false)

const statCards = computed(() => {
  const s = stats.value || {}
  const lt = s.long_term || {}
  return [
    { label: '瞬时记忆', value: s.immediate?.count ?? '-' },
    { label: '短期记忆', value: s.short_term?.count ?? '-' },
    { label: '长期记忆', value: lt.count ?? '-' },
    { label: '总计', value: s.total ?? '-' },
    { label: '向量后端', value: lt.vector_backend || '无' },
  ]
})

const loadOverview = async () => {
  try {
    const res = await memoryApi.stats()
    const d = res.data || res
    stats.value = d.stats || {}
    cronJobs.value = d.cron_jobs || []
    configSnap.value = d.config || {}
  } catch (e) {
    ElMessage.error('加载概览失败: ' + (e.message || ''))
  }
}

const doConsolidate = async () => {
  try {
    await ElMessageBox.confirm('手动触发合并相似长期记忆？该操作会修改/删除记忆。', '提示', { type: 'warning' })
  } catch { return }
  consolidating.value = true
  try {
    const res = await memoryApi.consolidate()
    const d = res.data || res
    ElMessage.success(`合并完成：users=${d.users}, pairs=${d.pairs}, merged=${d.merged}`)
    await loadOverview()
  } catch (e) {
    ElMessage.error('合并失败: ' + (e.message || ''))
  } finally {
    consolidating.value = false
  }
}

// 浏览
const types = ['preference', 'fact', 'task', 'event', 'note', 'context', 'skill', 'error', 'relation']
const filters = ref({ user_id: '', session_id: '', mtype: '', q: '', tier: 'long_term', workspace_id: '' })
const list = ref([])
const listLoading = ref(false)
const page = ref({ current: 1, size: 20, total: 0 })
const workspaceList = ref([])

const loadWorkspaces = async () => {
  try {
    const res = await memoryApi.workspaces()
    const d = res.data || res
    workspaceList.value = d.workspaces || []
  } catch (e) {
    console.log('workspaces load failed:', e.message || '')
  }
}

const onTierChange = () => {
  page.value.current = 1
  loadList()
}

const loadList = async () => {
  listLoading.value = true
  try {
    const params = {
      limit: page.value.size,
      offset: (page.value.current - 1) * page.value.size,
      tier: filters.value.tier,
    }
    if (filters.value.user_id) params.user_id = filters.value.user_id
    if (filters.value.session_id) params.session_id = filters.value.session_id
    if (filters.value.mtype) params.mtype = filters.value.mtype
    if (filters.value.q) params.q = filters.value.q
    if (filters.value.workspace_id) params.workspace_id = filters.value.workspace_id
    const res = await memoryApi.list(params)
    const d = res.data || res
    list.value = d.items || []
    page.value.total = d.total || 0
  } catch (e) {
    ElMessage.error('加载列表失败: ' + (e.message || ''))
  } finally {
    listLoading.value = false
  }
}

const resetFilters = () => {
  filters.value = { user_id: '', session_id: '', mtype: '', q: '', tier: 'long_term', workspace_id: '' }
  page.value.current = 1
  loadList()
}

// 编辑
const editVisible = ref(false)
const editSaving = ref(false)
const editForm = ref({ id: '', content: '', importance: 0.5 })
const openEdit = (row) => {
  editForm.value = { id: row.id, content: row.content, importance: row.importance ?? 0.5 }
  editVisible.value = true
}
const doSave = async () => {
  editSaving.value = true
  try {
    await memoryApi.update(editForm.value.id, {
      content: editForm.value.content,
      importance: editForm.value.importance,
      tier: filters.value.tier,
    })
    ElMessage.success('已更新')
    editVisible.value = false
    loadList()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || ''))
  } finally {
    editSaving.value = false
  }
}

const doDelete = async (row) => {
  try {
    await ElMessageBox.confirm(`删除该记忆？\n${row.content.slice(0, 40)}`, '提示', { type: 'warning' })
    await memoryApi.delete(row.id, { tier: filters.value.tier })
    ElMessage.success('已删除')
    loadList()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.message || ''))
  }
}

const clearUser = async () => {
  const uid = filters.value.user_id
  const userObj = userList.value.find(u => String(u.id) === uid)
  const displayName = userObj ? userObj.username : uid
  try {
    await ElMessageBox.confirm(`清空用户「${displayName}」的全部记忆？此操作不可恢复。`, '提示', { type: 'error' })
    const res = await memoryApi.clearUser(uid)
    const d = res.data || res
    ElMessage.success(`已清理 ${d.deleted ?? 0} 条`)
    loadList()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('清理失败: ' + (e.message || ''))
  }
}

// 召回试用
const recall = ref({ query: '', user_id: '', limit: 10 })
const recallResults = ref([])
const recallLoading = ref(false)
const doRecall = async () => {
  if (!recall.value.query.trim()) { ElMessage.warning('请输入查询词'); return }
  recallLoading.value = true
  try {
    const params = { query: recall.value.query, limit: recall.value.limit }
    if (recall.value.user_id) params.user_id = recall.value.user_id
    const res = await memoryApi.recall(params)
    const d = res.data || res
    recallResults.value = d.results || []
  } catch (e) {
    ElMessage.error('召回失败: ' + (e.message || ''))
  } finally {
    recallLoading.value = false
  }
}

const fmt = (iso) => {
  if (!iso) return ''
  try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }) } catch { return iso }
}

const resolveUsername = (uid) => {
  if (!uid) return ''
  const userObj = userList.value.find(u => String(u.id) === String(uid))
  return userObj ? userObj.username : uid
}

onMounted(() => {
  loadUsers()
  loadWorkspaces()
  loadOverview()
  loadList()
})
</script>
