<template>
  <div class="page-container">
    <div class="table-toolbar">
      <span style="font-size: 16px; font-weight: 600;">MCP 服务管理</span>
      <div style="display: flex; gap: 8px; align-items: center;">
        <el-input v-model="searchName" placeholder="搜索名称" style="width: 180px" clearable @keyup.enter="loadData" />
        <el-button @click="loadData">刷新</el-button>
        <el-button type="primary" @click="openCreate">新建 MCP</el-button>
      </div>
    </div>

    <el-table :data="list" v-loading="loading" border stripe>
      <el-table-column prop="mcp_name" label="名称" width="180" />
      <el-table-column prop="description" label="描述" show-overflow-tooltip />
      <el-table-column prop="category" label="分类" width="100" />
      <el-table-column label="连接类型" width="100">
        <template #default="{ row }">{{ row.connection_type }}</template>
      </el-table-column>
      <el-table-column label="mcp_id" width="220">
        <template #default="{ row }">{{ row.mcp_id }}</template>
      </el-table-column>
      <el-table-column label="状态" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="可见性" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="visTag(row).type" size="small">{{ visTag(row).label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="工作空间" width="100">
        <template #default="{ row }">{{ workspaceName(row.workspace_id) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="380" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="showDetail(row)">详情</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" @click="testConnect(row)">测试连接</el-button>
          <el-button size="small" @click="syncInterfaces(row)">同步接口</el-button>
          <el-button size="small" :type="row.enabled ? 'warning' : 'success'" @click="toggleStatus(row)">{{ row.enabled ? '禁用' : '启用' }}</el-button>
          <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div style="margin-top: 12px; display: flex; justify-content: flex-end;">
      <el-pagination
        v-model:current-page="pageNo"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        @current-change="loadData"
        @size-change="loadData"
      />
    </div>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="formVisible" :title="editing ? '编辑 MCP' : '新建 MCP'" width="720px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="名称" required>
          <el-input v-model="form.mcpName" :disabled="editing" placeholder="如 text-analysis-tools" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="form.category" placeholder="如 utility" />
        </el-form-item>
        <el-form-item label="连接类型">
          <el-select v-model="form.connectionType" style="width: 200px">
            <el-option label="stdio（本地进程）" value="stdio" />
            <el-option label="sse（HTTP/SSE）" value="sse" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.connectionType === 'stdio'" label="执行命令">
          <el-input v-model="form.execCmd" placeholder="如 python 或 python.exe 的完整路径" />
        </el-form-item>
        <el-form-item v-if="form.connectionType === 'stdio'" label="参数(JSON)">
          <el-input v-model="paramsJson" type="textarea" :rows="4" placeholder='{"args": ["/path/to/mcp_server.py"]}' />
        </el-form-item>
        <el-form-item v-if="form.connectionType === 'sse'" label="连接 URL">
          <el-input v-model="form.connectionUrl" placeholder="如 http://localhost:8000/sse" />
        </el-form-item>
        <el-form-item v-if="form.connectionType === 'sse'" label="参数(JSON)">
          <el-input v-model="paramsJson" type="textarea" :rows="4" placeholder='{"headers": {}, "url_params": {}}' />
        </el-form-item>
        <el-form-item label="认证信息">
          <el-input v-model="form.authInfo" placeholder="Bearer token 等（可选）" />
        </el-form-item>
        <el-form-item label="超时(ms)">
          <el-input-number v-model="form.timeout" :min="1000" :step="1000" />
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
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 详情对话框 -->
    <el-dialog v-model="detailVisible" title="MCP 详情" width="820px">
      <el-descriptions v-if="detail" :column="1" border>
        <el-descriptions-item label="名称">{{ detail.mcp.mcp_name }}</el-descriptions-item>
        <el-descriptions-item label="mcp_id">{{ detail.mcp.mcp_id }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ detail.mcp.description || '-' }}</el-descriptions-item>
        <el-descriptions-item label="分类">{{ detail.mcp.category || '-' }}</el-descriptions-item>
        <el-descriptions-item label="连接类型">{{ detail.mcp.connection_type }}</el-descriptions-item>
        <el-descriptions-item label="执行命令">{{ detail.mcp.exec_cmd || '-' }}</el-descriptions-item>
        <el-descriptions-item label="连接 URL">{{ detail.mcp.connection_url || '-' }}</el-descriptions-item>
        <el-descriptions-item label="超时">{{ detail.mcp.timeout }} ms</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="detail.mcp.enabled ? 'success' : 'info'" size="small">{{ detail.mcp.enabled ? '启用' : '禁用' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="参数">
          <pre style="white-space: pre-wrap; max-height: 160px; overflow-y: auto;">{{ JSON.stringify(detail.mcp.params, null, 2) }}</pre>
        </el-descriptions-item>
      </el-descriptions>
      <h4 style="margin: 16px 0 8px;">接口列表（{{ (detail?.interfaces || []).length }}）</h4>
      <el-table :data="detail?.interfaces || []" border size="small">
        <el-table-column prop="intfc_name" label="接口名" width="180" />
        <el-table-column prop="description" label="描述" show-overflow-tooltip />
        <el-table-column label="输入参数" width="100">
          <template #default="{ row }">{{ Object.keys(row.input_param_ex?.properties || {}).length }} 个</template>
        </el-table-column>
        <el-table-column label="状态" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 测试连接结果 -->
    <el-dialog v-model="connectResultVisible" title="连接测试结果" width="720px">
      <p v-if="connectResult.length === 0" style="color: #999;">未获取到工具</p>
      <el-table :data="connectResult" border size="small">
        <el-table-column prop="name" label="工具名" width="180" />
        <el-table-column prop="description" label="描述" show-overflow-tooltip />
        <el-table-column label="参数" width="100">
          <template #default="{ row }">{{ Object.keys(row.inputSchema?.properties || {}).length }} 个</template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { mcpApi } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const list = ref([])
const loading = ref(false)
const pageNo = ref(1)
const pageSize = ref(10)
const total = ref(0)
const searchName = ref('')

const formVisible = ref(false)
const editing = ref(false)
const saving = ref(false)
const form = ref(emptyForm())
const paramsJson = ref('{}')

const detailVisible = ref(false)
const detail = ref(null)

const connectResultVisible = ref(false)
const connectResult = ref([])

function emptyForm() {
  return {
    prKeyId: '',
    mcpName: '',
    description: '',
    category: '',
    connectionType: 'stdio',
    connectionUrl: '',
    execCmd: '',
    authInfo: '',
    timeout: 30000,
    enabled: true,
    visibility: 'private',
  }
}

// 三层可见性 → 标签（兼容旧 is_public 字段）
const workspaceMap = ref({})

const loadWorkspaces = async () => {
  try {
    const token = localStorage.getItem('auth_token') || ''
    const res = await fetch('/api/auth/workspaces', { headers: { Authorization: token } })
    const data = await res.json()
    for (const ws of (data?.list || [])) {
      workspaceMap.value[ws.workspace_id] = ws.name
    }
  } catch { /* ignore */ }
}

const workspaceName = (id) => workspaceMap.value[id] || (id ? `#${id}` : '-')

const visTag = (row) => {
  const v = row.visibility || (row.is_public === 1 ? 'public' : 'workspace')
  if (v === 'public') return { type: 'success', label: '全局' }
  if (v === 'private') return { type: 'info', label: '个人' }
  return { type: 'warning', label: '空间' }
}

const loadData = async () => {
  loading.value = true
  try {
    const res = await mcpApi.page({ pageNo: pageNo.value, pageSize: pageSize.value, mcpName: searchName.value || undefined })
    const data = res?.data || {}
    list.value = data.list || []
    total.value = data.total || 0
  } catch (e) {
    ElMessage.warning('加载失败，请确保后端服务已启动')
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editing.value = false
  form.value = emptyForm()
  paramsJson.value = '{}'
  formVisible.value = true
}

const openEdit = (row) => {
  editing.value = true
  form.value = {
    prKeyId: String(row.pr_key_id),
    mcpName: row.mcp_name,
    description: row.description || '',
    category: row.category || '',
    connectionType: row.connection_type || 'stdio',
    connectionUrl: row.connection_url || '',
    execCmd: row.exec_cmd || '',
    authInfo: row.auth_info || '',
    timeout: row.timeout || 30000,
    enabled: row.enabled,
    visibility: row.visibility || (row.is_public === 1 ? 'public' : 'workspace'),
  }
  paramsJson.value = JSON.stringify(row.params || {}, null, 2)
  formVisible.value = true
}

const save = async () => {
  if (!form.value.mcpName) {
    ElMessage.warning('请填写名称')
    return
  }
  let params
  try {
    params = paramsJson.value.trim() ? JSON.parse(paramsJson.value) : {}
  } catch (e) {
    ElMessage.error('参数 JSON 格式错误: ' + e.message)
    return
  }
  saving.value = true
  try {
    const payload = { ...form.value, params }
    if (editing.value) {
      const res = await mcpApi.update(payload)
      if (res?.code !== '0000000000000000') throw new Error(res?.message || '更新失败')
      ElMessage.success('更新成功')
    } else {
      const res = await mcpApi.register(payload)
      if (res?.code !== '0000000000000000') throw new Error(res?.message || '创建失败')
      ElMessage.success('创建成功')
    }
    formVisible.value = false
    await loadData()
  } catch (e) {
    ElMessage.error(e.message || '操作失败')
  } finally {
    saving.value = false
  }
}

const showDetail = async (row) => {
  try {
    const res = await mcpApi.detail({ prKeyId: String(row.pr_key_id) })
    if (res?.code !== '0000000000000000') throw new Error(res?.message || '加载失败')
    detail.value = res.data
    detailVisible.value = true
  } catch (e) {
    ElMessage.error(e.message || '加载详情失败')
  }
}

const testConnect = async (row) => {
  try {
    const res = await mcpApi.testConnect({
      connectionType: row.connection_type,
      connectionUrl: row.connection_url,
      execCmd: row.exec_cmd,
      authInfo: row.auth_info,
      timeout: row.timeout,
      params: row.params,
    })
    if (res?.code !== '0000000000000000') throw new Error(res?.message || '连接失败')
    connectResult.value = res.data?.tools || []
    connectResultVisible.value = true
    ElMessage.success(`获取到 ${connectResult.value.length} 个工具`)
  } catch (e) {
    ElMessage.error(e.message || '连接测试失败')
  }
}

const syncInterfaces = async (row) => {
  try {
    await ElMessageBox.confirm(`确认从 MCP "${row.mcp_name}" 同步接口？`, '提示', { type: 'warning' })
    const res = await mcpApi.intfcSync({ prKeyId: String(row.pr_key_id) })
    if (res?.code !== '0000000000000000') throw new Error(res?.message || '同步失败')
    ElMessage.success(res.message || '同步完成')
    await loadData()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error(e.message || '同步失败')
    }
  }
}

const toggleStatus = async (row) => {
  const newStatus = row.enabled ? '0' : '1'
  try {
    const res = await mcpApi.updateStatus({ prKeyId: String(row.pr_key_id), status: newStatus })
    if (res?.code !== '0000000000000000') throw new Error(res?.message || '状态更新失败')
    ElMessage.success(newStatus === '1' ? '已启用' : '已禁用')
    await loadData()
  } catch (e) {
    ElMessage.error(e.message || '状态更新失败')
  }
}

const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除 MCP "${row.mcp_name}"？`, '提示', { type: 'warning' })
    const res = await mcpApi.delete({ prKeyId: String(row.pr_key_id) })
    if (res?.code !== '0000000000000000') throw new Error(res?.message || '删除失败')
    ElMessage.success('删除成功')
    await loadData()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error(e.message || '删除失败')
    }
  }
}

onMounted(() => { loadWorkspaces(); loadData() })
</script>
