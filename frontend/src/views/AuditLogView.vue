<template>
  <div>
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span>审计日志明细</span>
          <el-button @click="loadLogs">刷新</el-button>
        </div>
      </template>
      <el-form :inline="true" @submit.prevent="onSearch">
        <el-form-item label="用户名">
          <el-autocomplete v-model="filter.username" :fetch-suggestions="querySearchUser" placeholder="用户名" clearable style="width: 150px;" />
        </el-form-item>
        <el-form-item label="资源类型">
          <el-select v-model="filter.resource_type" clearable placeholder="资源类型" style="width: 120px;">
            <el-option v-for="t in resourceTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="操作类型">
          <el-select v-model="filter.action" clearable placeholder="操作类型" style="width: 110px;">
            <el-option v-for="a in actionTypes" :key="a" :label="a" :value="a" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker v-model="filter.dateRange" type="daterange" range-separator="至"
            start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD" style="width: 240px;" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="onSearch">查询</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="logs" v-loading="loading" border size="small" style="margin-top: 12px;">
        <el-table-column prop="username" label="用户名" width="100" />
        <el-table-column prop="resource_type" label="资源类型" width="100" />
        <el-table-column prop="resource_id" label="资源ID" width="100" show-overflow-tooltip />
        <el-table-column prop="action" label="操作" width="80" />
        <el-table-column prop="http_method" label="方法" width="60" />
        <el-table-column prop="status_code" label="状态码" width="70" />
        <el-table-column v-if="filter.resource_type === 'security'" label="匹配词" width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.after_data || row.resource_id || '-' }}</template>
        </el-table-column>
        <el-table-column prop="create_time" label="时间" width="160" />
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }"><el-button size="small" @click="showDetail(row)">详情</el-button></template>
        </el-table-column>
      </el-table>
      <el-pagination
        style="margin-top: 12px; justify-content: flex-end; display: flex;"
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="loadLogs"
        @size-change="onSearch"
      />
    </el-card>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" title="审计详情" width="720px">
      <el-descriptions :column="1" border v-if="detail">
        <el-descriptions-item label="审计ID">{{ detail.audit_id || detail.pr_key_id }}</el-descriptions-item>
        <el-descriptions-item label="用户">{{ detail.username }} (id={{ detail.user_id }})</el-descriptions-item>
        <el-descriptions-item label="请求">{{ detail.http_method }} {{ detail.path }}</el-descriptions-item>
        <el-descriptions-item label="资源">{{ detail.resource_type }} / {{ detail.resource_id }}</el-descriptions-item>
        <el-descriptions-item label="操作">{{ detail.action }}</el-descriptions-item>
        <el-descriptions-item label="状态码">{{ detail.status_code }}</el-descriptions-item>
        <el-descriptions-item label="工作空间">{{ detail.workspace_id }}</el-descriptions-item>
        <el-descriptions-item label="before_data（操作前）">
          <pre style="max-height: 200px; overflow: auto; margin: 0;">{{ formatJson(detail.before_data) }}</pre>
        </el-descriptions-item>
        <el-descriptions-item label="after_data（操作后）">
          <pre style="max-height: 200px; overflow: auto; margin: 0;">{{ formatJson(detail.after_data) }}</pre>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { auditApi } from '../api/index.js'
import { ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()

const logs = ref([])
const loading = ref(false)
const filter = ref({ username: '', resource_type: '', action: '', dateRange: [] })
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const detailVisible = ref(false)
const detail = ref(null)
const resourceTypes = ['agent', 'skill', 'mcp', 'mode', 'api', 'tool', 'external_tool', 'trigger', 'workspace', 'user', 'role', 'config', 'subscription', 'mailbox', 'knowledgebase', 'team', 'security']
const actionTypes = ['create', 'update', 'delete', 'enable', 'disable', 'toggle', 'test', 'reload', 'blocked_input', 'blocked_output']

const onSearch = () => {
  page.value = 1
  loadLogs()
}

const loadLogs = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filter.value.username) params.username = filter.value.username
    if (filter.value.resource_type) params.resource_type = filter.value.resource_type
    if (filter.value.action) params.action = filter.value.action
    if (filter.value.dateRange?.[0]) params.start_date = filter.value.dateRange[0]
    if (filter.value.dateRange?.[1]) params.end_date = filter.value.dateRange[1]
    const res = await auditApi.list(params)
    logs.value = res?.data?.logs || res?.logs || []
    total.value = res?.data?.total ?? res?.total ?? 0
  } catch (e) {
    ElMessage.error('查询失败：' + (e.message || ''))
  } finally {
    loading.value = false
  }
}

const querySearchUser = async (queryString, cb) => {
  try {
    const res = await auditApi.usernames(queryString || '')
    const names = res?.data?.usernames || res?.usernames || []
    cb(names.map(n => ({ value: n })))
  } catch {
    cb([])
  }
}

const showDetail = async (row) => {
  const id = row.audit_id || row.pr_key_id
  if (!id) {
    detail.value = row
    detailVisible.value = true
    return
  }
  try {
    const res = await auditApi.detail(id)
    detail.value = res?.data || row
  } catch {
    detail.value = row
  }
  detailVisible.value = true
}

const formatJson = (v) => {
  if (v == null) return ''
  if (typeof v === 'string') {
    try { return JSON.stringify(JSON.parse(v), null, 2) } catch { return v }
  }
  try { return JSON.stringify(v, null, 2) } catch { return String(v) }
}

onMounted(() => {
  // 读 route.query 预填筛选（来自报表饼图点选跳转）
  const q = route.query
  if (q.resource_type) filter.value.resource_type = q.resource_type
  if (q.username) filter.value.username = q.username
  if (q.action) filter.value.action = q.action
  if (q.start_date && q.end_date) {
    filter.value.dateRange = [q.start_date, q.end_date]
  }
  // 清掉 query 避免刷新重复预筛
  if (Object.keys(q).length) {
    router.replace({ path: '/stats/audit' })
  }
  loadLogs()
})
</script>
