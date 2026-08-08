import axios from 'axios'
import { ElMessage } from 'element-plus'

// ── Token 工具函数（统一 token 存取入口） ──
const AUTH_KEY = 'auth_token'
export function getToken() { return localStorage.getItem(AUTH_KEY) || '' }
export function setToken(token) { localStorage.setItem(AUTH_KEY, token) }
export function clearToken() { localStorage.removeItem(AUTH_KEY) }

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截：注入默认 token（无登录模式）
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = token
  }
  return config
})

// ─── 统一错误处理函数（可独立测试） ───
// 设计目标：后端所有错误响应统一返回 {code, message, data} 格式
// （来自 wrap_response + 全局 exception handler）
// 本函数根据 status code 分流，弹不同级别的 ElMessage
export function handleApiError(error) {
  const status = error.response?.status
  const data = error.response?.data
  // 统一错误格式：{code, message, data}（来自后端 wrap_response）
  const message = data?.message || error.message || '请求失败'

  if (status === 429) {
    // rate limit（slowapi 触发）
    ElMessage.warning('请求过于频繁，请稍后重试')
  } else if (status === 401) {
    // 未授权：清 token + 跳转登录
    ElMessage.error('未授权，请重新登录')
    clearToken()
    localStorage.removeItem('user_info')
    if (typeof window !== 'undefined' && window.location) {
      window.location.href = '/login'
    }
  } else if (status >= 500) {
    // 服务器错误
    ElMessage.error(`服务器错误: ${message}`)
  } else if (status >= 400) {
    // 4xx 客户端错误
    ElMessage.error(message)
  } else if (!error.response) {
    // 网络错误（无 response，如断网/超时）
    ElMessage.error(`网络错误: ${error.message || '连接失败'}`)
  }

  return Promise.reject(error)
}

// 响应拦截：成功返回 response.data，失败调 handleApiError
http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('API Error:', error.response?.status, error.message)
    return handleApiError(error)
  }
)

// SSE 流式 fetch 公共函数（streamChat / multiDispatch 共用）
// 用 ReadableStream 读取 SSE，按 \n\n 分割事件，解析 data: JSON
const sseFetch = (url, params, onEvent) => {
  const token = getToken()
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: token } : {}) },
    body: JSON.stringify(params)
  }).then(async (response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      try {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let idx
        while ((idx = buffer.indexOf('\n\n')) >= 0) {
          const line = buffer.slice(0, idx)
          buffer = buffer.slice(idx + 2)
          if (line.startsWith('data: ')) {
            try { onEvent(JSON.parse(line.slice(6))) } catch (e) { console.error('SSE parse', e) }
          }
        }
      } catch (e) {
        onEvent({ error: '连接断开' })
        break
      }
    }
  })
}

// ── Agent 管理 ──
export const agentApi = {
  getList: (params) => params ? http.get('/admin/agents/list', { params }) : http.get('/admin/agents/list'),
  getDetail: (id) => http.get(`/admin/agents/${id}`),
  getApps: () => http.get('/admin/agents/apps/list'),
  getSelections: () => http.get('/admin/agents/selections'),
  create: (params) => http.post('/admin/agents/create', params),
  update: (id, params) => http.put(`/admin/agents/${id}`, params),
  delete: (id) => http.delete(`/admin/agents/${id}`),
  toggle: (id, enabled) => http.patch(`/admin/agents/${id}/toggle`, { enabled }),
  submitReview: (id, body) => http.post(`/admin/agents/${id}/submit-review`, body || {}),
  testChat: (agentId, message) => http.post('/chat', { messages: [{ role: 'user', content: message }], agent: agentId }),
  dispatch: (id, params) => http.post(`/admin/agents/${id}/dispatch`, params || {}),
  getDispatchTasks: () => http.get('/admin/agents/dispatch-tasks'),
}

// ── SubAgent 管理 ──
// SubAgent API 已废弃，统一使用 agentApi（/api/admin/agents/*）；后端 /subagents 路由保留向后兼容

// ── 工具管理 ──
export const toolApi = {
  getList: () => http.get('/admin/tools', { params: { skip: 0, limit: 100 } }),
  // 统计概览：按 workspace 统计 Agent 绑定的去重外部工具数（T-A 方案）
  // workspaceId 为 null/undefined（全部用户）时不传 workspace_id，后端聚合全部空间
  getStats: (workspaceId) => http.get('/admin/tools/stats', { params: workspaceId ? { workspace_id: workspaceId } : {} }),
  getDetail: (name) => http.get(`/admin/tools/${name}`),
  update: (name, params) => http.put(`/admin/tools/${name}`, params),
  export: (name) => http.post(`/admin/tools/${name}/export`),
  exportAll: () => http.post('/admin/tools/export-all'),
  restoreDefaults: (name) => http.post(`/admin/tools/${name}/restore-defaults`),
  restoreAllDefaults: () => http.post('/admin/tools/restore-defaults'),
}

// ── 外部工具 ──
export const externalToolApi = {
  getList: () => http.get('/admin/external-tools'),
  getDetail: (name) => http.get(`/admin/external-tools/${name}`),
  create: (params) => http.post('/admin/external-tools', params),
  update: (name, params) => http.put(`/admin/external-tools/${name}`, params),
  delete: (name) => http.delete(`/admin/external-tools/${name}`),
  import: (params) => http.post('/admin/external-tools/import', params),
  export: () => http.post('/admin/external-tools/export'),
  getParams: (name) => http.get(`/admin/external-tools/${name}/parameters`),
  createParam: (name, params) => http.post(`/admin/external-tools/${name}/parameters`, params),
  updateParam: (name, paramName, params) => http.put(`/admin/external-tools/${name}/parameters/${paramName}`, params),
  deleteParam: (name, paramName) => http.delete(`/admin/external-tools/${name}/parameters/${paramName}`),
}

// ── Skill 管理 ──
export const skillApi = {
  // params 可选：无参时行为不变（Dashboard/SkillList）；统计概览传 { workspace_id } 按用户筛选
  getList: (params) => params ? http.get('/admin/skills/list', { params }) : http.get('/admin/skills/list'),
  getDetail: (id) => http.get(`/admin/skills/${id}`),
  create: (params) => http.post('/admin/skills/create', params),
  update: (id, params) => http.put(`/admin/skills/${id}`, params),
  delete: (id) => http.delete(`/admin/skills/${id}`),
  bind: (params) => http.post('/admin/skills/bind', params),
  unbind: (params) => http.delete('/admin/skills/unbind', { data: params }),
  getByAgent: (agentId) => http.get(`/admin/skills/agent/${agentId}`),
  reload: () => http.post('/admin/skills/reload'),
  getCategories: () => http.get('/admin/skills/categories'),
  getLocalSkills: () => http.get('/admin/skills/local/list'),
  importLocal: (name) => http.post(`/admin/skills/local/import/${name}`),
  page: (params) => http.post('/admin/smart-agent/skillManage/page', params),
  createSkill: (params) => http.post('/admin/smart-agent/skillManage/createSkill', params),
  updateSkill: (params) => http.post('/admin/smart-agent/skillManage/updateSkill', params),
  deleteSkill: (params) => http.post('/admin/smart-agent/skillManage/deleteSkill', params),
  getSkillDetail: (params) => http.post('/admin/smart-agent/skillManage/getSkillDetail', params),
  updateSkillStatus: (params) => http.post('/admin/smart-agent/skillManage/updateSkillStatus', params),
}

// ── 模式管理 ──
export const modeApi = {
  getList: () => http.get('/admin/modes', { params: { skip: 0, limit: 100 } }),
  getDetail: (id) => http.get(`/admin/modes/${id}`),
  create: (params) => http.post('/admin/modes', params),
  update: (id, params) => http.put(`/admin/modes/${id}`, params),
  delete: (id) => http.delete(`/admin/modes/${id}`),
  getSystem: () => http.get('/admin/modes/system'),
  import: (files) => http.post('/admin/modes/import', files),
  export: (name) => http.post(`/admin/modes/${name}/export`),
  exportAll: () => http.post('/admin/modes/export-all'),
  preview: (params) => http.post('/admin/modes/preview', params),
  getModes: () => http.get('/modes'),
}

// ── Prompt 模板 ──
export const promptApi = {
  list: () => http.get('/admin/prompts'),
  detail: (name) => http.get(`/admin/prompts/${name}`),
  create: (params) => http.post('/admin/prompts', params),
  update: (id, params) => http.put(`/admin/prompts/${id}`, params),
  render: (params) => http.post('/admin/prompts/render', params),
}

// ── Agent 版本管理 ──
// 注：发布只能经审批流（提交审批→审批通过），不再提供直接 publish API
export const versionApi = {
  list: (agentId) => http.get(`/admin/agents/${agentId}/versions`),
  create: (agentId, params) => http.post(`/admin/agents/${agentId}/versions`, params),
  rollback: (agentId, versionNo) => http.post(`/admin/agents/${agentId}/versions/${versionNo}/rollback`),
  diff: (agentId, v1, v2) => http.get(`/admin/agents/${agentId}/versions/diff`, { params: { v1, v2 } }),
}

// ── 端到端评测 ──
export const evalApi = {
  listDatasets: () => http.get('/admin/eval/datasets'),
  getDataset: (id) => http.get(`/admin/eval/datasets/${id}`),
  createDataset: (params) => http.post('/admin/eval/datasets', params),
  judge: (params) => http.post('/admin/eval/judge', params),
  runDataset: (params) => http.post('/admin/eval/run-dataset', params),
  submitFeedback: (params) => http.post('/admin/eval/feedback', params),
  listResults: (params) => http.get('/admin/eval/results', { params }),
}

// ── 知识库版本管理 ──
export const kbVersionApi = {
  list: (kbId) => http.get(`/admin/knowledgebase/${kbId}/versions`),
  create: (kbId, params) => http.post(`/admin/knowledgebase/${kbId}/versions`, params),
  publish: (kbId, v) => http.post(`/admin/knowledgebase/${kbId}/versions/${v}/publish`),
  rollback: (kbId, v) => http.post(`/admin/knowledgebase/${kbId}/versions/${v}/rollback`),
  diff: (kbId, v1, v2) => http.get(`/admin/knowledgebase/${kbId}/versions/diff`, { params: { v1, v2 } }),
  rebuildIndex: (kbId, params) => http.post(`/admin/knowledgebase/${kbId}/rebuild-index`, params),
}

// ── Agent 团队协作 ──
export const teamApi = {
  list: () => http.get('/admin/teams'),
  detail: (teamId) => http.get(`/admin/teams/${teamId}`),
  create: (params) => http.post('/admin/teams', params),
  addMember: (teamId, params) => http.post(`/admin/teams/${teamId}/members`, params),
  getMembers: (teamId) => http.get(`/admin/teams/${teamId}/members`),
  sendMessage: (params) => http.post('/admin/mailbox/send', params),
  pollMessages: (agentName) => http.get('/admin/mailbox/poll', { params: { agent_name: agentName } }),
  ackMessage: (messageId) => http.post(`/admin/mailbox/ack/${messageId}`),
}

// ── 出站事件订阅 ──
export const subscriptionApi = {
  list: () => http.get('/admin/subscriptions'),
  create: (params) => http.post('/admin/subscriptions', params),
  delete: (subId) => http.delete(`/admin/subscriptions/${subId}`),
  notify: (params) => http.post('/admin/subscriptions/notify', params),
}

// ── MCP 管理 ──
export const mcpApi = {
  // params: body(PageQuery)；config: 可选 axios config，统计概览传 { params: { workspace_id } } 做 query 筛选
  page: (params, config) => http.post('/admin/mcp/page', params, config),
  detail: (params) => http.post('/admin/mcp/detail', params),
  register: (params) => http.post('/admin/mcp/register', params),
  update: (params) => http.post('/admin/mcp/update', params),
  updateStatus: (params) => http.post('/admin/mcp/updateStatus', params),
  delete: (params) => http.post('/admin/mcp/delete', params),
  testConnect: (params) => http.post('/admin/mcp/testConnect', params),
  intfcPage: (params) => http.post('/admin/mcp/intfc/page', params),
  intfcSync: (params) => http.post('/admin/mcp/intfc/sync', params),
}

// ── 知识库 ──
export const knowledgeApi = {
  getDatabases: (params) => http.post('/admin/smart-agent/api/knowledgebase/getDatabases', params),
  searchTables: (params) => http.post('/admin/smart-agent/api/knowledgebase/searchTables', params),
  list: (params) => http.post('/admin/smart-agent/api/knowledgebase/list', params),
  save: (params) => http.post('/admin/smart-agent/api/knowledgebase/save', params),
  detail: (params) => http.post('/admin/smart-agent/api/knowledgebase/detail', params),
  delete: (params) => http.post('/admin/smart-agent/api/knowledgebase/delete', params),
  getTableDetails: (params) => http.post('/admin/smart-agent/api/knowledgebase/getTableDetails', params),
  getSqlModels: (params) => http.post('/admin/smart-agent/api/knowledgebase/getSqlModels', params),
  saveSqlModel: (params) => http.post('/admin/smart-agent/api/knowledgebase/sqlmodel/save', params),
  sqlModelDetail: (params) => http.post('/admin/smart-agent/api/knowledgebase/sqlmodel/detail', params),
  searchSqlResult: (params) => http.post('/admin/smart-agent/api/knowledgebase/searchSqlResult', params),
  upload: (params) => http.post('/admin/smart-agent/api/knowledgebase/upload', params),
  documents: (params) => http.post('/admin/smart-agent/api/knowledgebase/documents', params),
  deleteDocuments: (params) => http.post('/admin/smart-agent/api/knowledgebase/documents/delete', params),
}

// ── 系统配置 ──
export const systemApi = {
  getConfig: () => http.get('/admin/config/agent'),
  updateConfig: (params) => http.put('/admin/config/agent', params),
  getStatistics: () => http.get('/admin/config/statistics'),
}

// ── 模型资源管理 ──
export const modelResourceApi = {
  page: (params) => http.post('/admin/smart-agent/system/resMgmt/page', params),
  create: (params) => http.post('/admin/smart-agent/system/resMgmt/create', params),
  update: (params) => http.post('/admin/smart-agent/system/resMgmt/update', params),
  delete: (params) => http.post('/admin/smart-agent/system/resMgmt/delete', params),
  select: (params) => http.post('/admin/smart-agent/system/resMgmt/select', params),
  testConnection: (params) => http.post('/admin/smart-agent/system/resMgmt/testConnection', params),
}

// ── 菜单管理 ──
export const menuApi = {
  selectMenuList: (params) => http.post('/admin/smart-agent/system/menu/selectMenuList', params),
  addMenu: (params) => http.post('/admin/smart-agent/system/menu/addMenu', params),
  editMenu: (params) => http.post('/admin/smart-agent/system/menu/editMenu', params),
  deleteMenu: (params) => http.post('/admin/smart-agent/system/menu/deleteMenu', params),
  selectMenuTree: (params) => http.post('/admin/smart-agent/system/menu/selectMenuTree', params),
  detail: (params) => http.post('/admin/smart-agent/system/menu/detail', params),
}

// ── RLS 规则 ──
export const rlsRuleApi = {
  getDetail: (id) => http.get(`/admin/rls-rule/${id}`),
  update: (id, params) => http.put(`/admin/rls-rule/${id}`, params),
  delete: (id) => http.delete(`/admin/rls-rule/${id}`),
  getTableColumns: () => http.get('/admin/rls-rule/table-columns'),
  checkRuleId: () => http.get('/admin/rls-rule/check-rule-id'),
}

// ── 聊天 ──
export const chatApi = {
  send: (params) => http.post('/chat', params),
  streamChat: (params, onEvent) => sseFetch('/api/chat/stream', params, onEvent),
  getModes: () => http.get('/modes'),
  getSubagents: () => http.get('/subagents'),
  createSession: (params) => http.post('/sessions', params),
  getSessions: () => http.get('/sessions'),
  getSession: (id) => http.get(`/sessions/${id}`),
  updateSession: (id, params) => http.put(`/sessions/${id}`, params),
  deleteSession: (id) => http.delete(`/sessions/${id}`),
  getMessages: (id) => http.get(`/sessions/${id}/messages`),
  multiDispatch: (params, onEvent) => sseFetch('/api/admin/agents/dispatch-multi', params, onEvent),
}

export const planApi = {
  review: async (dispatchId, action, modifiedPlan) => {
    const res = await fetch(`/api/plan/${dispatchId}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, modified_plan: modifiedPlan })
    })
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  }
}

export const ragApi = {
  ingest: async (formData) => {
    const res = await fetch('/api/rag/ingest', {
      method: 'POST',
      body: formData,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
  ingestStatus: async (taskId) => {
    const res = await fetch(`/api/rag/ingest/status/${taskId}`)
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
  retrieve: async (params) => {
    const res = await fetch('/api/rag/retrieve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
  getConfig: async () => {
    const res = await fetch('/api/rag/config')
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
  kbList: async () => {
    const res = await fetch('/api/rag/kb')
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
  kbCreate: async (params) => {
    const res = await fetch('/api/rag/kb', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
  kbUpdate: async (kbId, params) => {
    const res = await fetch(`/api/rag/kb/${kbId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
  kbDelete: async (kbId) => {
    const res = await fetch(`/api/rag/kb/${kbId}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
  parse: async (formData) => {
    const res = await fetch('/api/rag/parse', { method: 'POST', body: formData })
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
  parseStatus: async (taskId) => {
    const res = await fetch(`/api/rag/parse/status/${taskId}`)
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
}

// ── 模型配置 ──
export const modelApi = {
  list: async (modelType = null) => {
    const url = modelType ? `/api/models?model_type=${modelType}` : '/api/models'
    const res = await fetch(url)
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
  create: async (params) => {
    const res = await fetch('/api/models', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params) })
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
  update: async (id, params) => {
    const res = await fetch(`/api/models/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params) })
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
  delete: async (id) => {
    const res = await fetch(`/api/models/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`${res.status}`)
    return res.json()
  },
}

// ── 认证 + 多租户 RBAC ──
export const authApi = {
  login: async (username, password) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '登录失败') }
    return res.json()
  },
  register: async (username, phone, password) => {
    const res = await fetch('/api/auth/register', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, phone, password })
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '注册失败') }
    return res.json()
  },
  changePassword: async (oldPassword, newPassword) => {
    const token = getToken()
    const res = await fetch('/api/auth/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword })
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '修改失败') }
    return res.json()
  },
  me: async () => {
    const token = getToken()
    const res = await fetch('/api/auth/me', { headers: { Authorization: token } })
    if (!res.ok) throw new Error('未登录')
    return res.json()
  },
  workspaces: async () => {
    const token = getToken()
    const res = await fetch('/api/auth/workspaces', { headers: { Authorization: token } })
    if (!res.ok) throw new Error('获取空间失败')
    return res.json()
  },
  switchWorkspace: async (workspaceId) => {
    const token = getToken()
    const res = await fetch(`/api/auth/switch-workspace?workspace_id=${workspaceId}`, {
      method: 'POST', headers: { Authorization: token }
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '切换失败') }
    return res.json()
  },
}

// ── Admin RBAC 管理（仅管理员）──
export const adminRbacApi = {
  users: async () => {
    const token = getToken()
    const res = await fetch('/api/admin/users', { headers: { Authorization: token } })
    if (!res.ok) throw new Error('获取用户列表失败')
    return res.json()
  },
  roles: async () => {
    const token = getToken()
    const res = await fetch('/api/admin/roles', { headers: { Authorization: token } })
    if (!res.ok) throw new Error('获取角色列表失败')
    return res.json()
  },
  createRole: async (roleName, roleCode, description, workspaceId) => {
    const token = getToken()
    const body = { role_name: roleName, role_code: roleCode, description }
    if (workspaceId) body.workspace_id = workspaceId
    const res = await fetch('/api/admin/roles', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify(body)
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '创建失败') }
    return res.json()
  },
  updateRole: async (roleId, data) => {
    const token = getToken()
    const res = await fetch(`/api/admin/roles/${roleId}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify(data)
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '更新失败') }
    return res.json()
  },
  deleteRole: async (roleId) => {
    const token = getToken()
    const res = await fetch(`/api/admin/roles/${roleId}`, { method: 'DELETE', headers: { Authorization: token } })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '删除失败') }
    return res.json()
  },
  permissions: async () => {
    const token = getToken()
    const res = await fetch('/api/admin/permissions', { headers: { Authorization: token } })
    if (!res.ok) throw new Error('获取权限列表失败')
    return res.json()
  },
  assignRole: async (userId, roleCode, workspaceId = null) => {
    const token = getToken()
    const res = await fetch('/api/admin/users/assign-role', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify({ user_id: userId, role_code: roleCode, workspace_id: workspaceId })
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '分配失败') }
    return res.json()
  },
  removeRole: async (userId, roleCode) => {
    const token = getToken()
    const res = await fetch('/api/admin/users/remove-role', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify({ user_id: userId, role_code: roleCode })
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '移除失败') }
    return res.json()
  },
  userPermissions: async (userId) => {
    const token = getToken()
    const res = await fetch(`/api/admin/users/${userId}/permissions`, { headers: { Authorization: token } })
    if (!res.ok) throw new Error('获取权限失败')
    return res.json()
  },
  rolePermissions: async (roleId) => {
    const token = getToken()
    const res = await fetch(`/api/admin/roles/${roleId}/permissions`, { headers: { Authorization: token } })
    if (!res.ok) throw new Error('获取角色权限失败')
    return res.json()
  },
  assignPermission: async (roleId, permissionId) => {
    const token = getToken()
    const res = await fetch('/api/admin/roles/assign-permission', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify({ role_id: roleId, permission_id: permissionId })
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '分配失败') }
    return res.json()
  },
  removePermission: async (roleId, permissionId) => {
    const token = getToken()
    const res = await fetch('/api/admin/roles/remove-permission', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify({ role_id: roleId, permission_id: permissionId })
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '移除失败') }
    return res.json()
  },
  updateStatus: async (userId, status) => {
    const token = getToken()
    const res = await fetch('/api/admin/users/update-status', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify({ user_id: userId, status })
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '更新失败') }
    return res.json()
  },
  createUser: async (params) => {
    const token = getToken()
    const res = await fetch('/api/admin/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify(params)
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '创建失败') }
    return res.json()
  },
  updateUser: async (userId, params) => {
    const token = getToken()
    const res = await fetch(`/api/admin/users/${userId}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify(params)
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '更新失败') }
    return res.json()
  },
  deleteUser: async (userId) => {
    const token = getToken()
    const res = await fetch(`/api/admin/users/${userId}`, {
      method: 'DELETE', headers: { Authorization: token }
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '删除失败') }
    return res.json()
  },
  // 工作空间管理
  workspaces: async () => {
    const token = getToken()
    const res = await fetch('/api/admin/workspaces', { headers: { Authorization: token } })
    if (!res.ok) throw new Error('获取工作空间失败')
    return res.json()
  },
  createWorkspace: async (name, description, ownerId) => {
    const token = getToken()
    const res = await fetch('/api/admin/workspaces', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify({ name, description, owner_id: ownerId })
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '创建失败') }
    return res.json()
  },
  updateWorkspace: async (workspaceId, data) => {
    const token = getToken()
    const res = await fetch(`/api/admin/workspaces/${workspaceId}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify(data)
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '更新失败') }
    return res.json()
  },
  deleteWorkspace: async (workspaceId) => {
    const token = getToken()
    const res = await fetch(`/api/admin/workspaces/${workspaceId}`, { method: 'DELETE', headers: { Authorization: token } })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '删除失败') }
    return res.json()
  },
  bindUser: async (workspaceId, userId, isOwner) => {
    const token = getToken()
    const res = await fetch(`/api/admin/workspaces/${workspaceId}/bind-user`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify({ user_id: userId, is_owner: isOwner })
    })
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || '绑定失败') }
    return res.json()
  },
  workspaceUsers: async (workspaceId) => {
    const token = getToken()
    const res = await fetch(`/api/admin/workspaces/${workspaceId}/users`, { headers: { Authorization: token } })
    if (!res.ok) throw new Error('获取空间用户失败')
    return res.json()
  },
}

// ── 触发器管理 ──
// 与后端 api/admin/trigger.py 路由契约一致
export const triggerApi = {
  list: (workspaceId, enabledOnly = false) =>
    http.get('/admin/triggers', { params: { workspace_id: workspaceId, enabled_only: enabledOnly } }),
  getDetail: (id) => http.get(`/admin/triggers/${id}`),
  create: (params) => http.post('/admin/triggers', params),
  update: (id, params) => http.put(`/admin/triggers/${id}`, params),
  delete: (id) => http.delete(`/admin/triggers/${id}`),
  enable: (id) => http.post(`/admin/triggers/${id}/enable`),
  disable: (id) => http.post(`/admin/triggers/${id}/disable`),
  test: (id) => http.post(`/admin/triggers/${id}/test`),
  getLogs: (id, limit = 50) => http.get(`/admin/triggers/${id}/logs`, { params: { limit } }),
}

// ── 审计日志（admin 专属）──
export const auditApi = {
  list: (params) => http.get('/admin/audit/logs', { params }),
  detail: (id) => http.get(`/admin/audit/logs/${id}`),
  usernames: (q) => http.get('/admin/audit/usernames', { params: { q } }),
  workspaces: (q) => http.get('/admin/audit/workspaces', { params: { q } }),
  summary: (params) => http.get('/admin/audit/summary', { params }),
}

// ── 用量统计 + 配额 ──
export const usageApi = {
  workspaceUsage: (workspaceId, params) => http.get(`/admin/usage/workspace/${workspaceId}`, { params }),
  agentUsage: (agentId, params) => http.get(`/admin/usage/agent/${agentId}`, { params }),
  dispatchUsage: (dispatchId) => http.get(`/admin/usage/dispatch/${dispatchId}`),
  pricing: () => http.get('/admin/usage/pricing'),
  quota: (workspaceId) => http.get(`/admin/quota/${workspaceId}`),
  saveQuota: (params) => http.post('/admin/quota', params),
}

// ── 记忆管理 ──
// 与后端 api/admin/memory.py 路由契约一致（/api/admin/memory/*）
export const memoryApi = {
  stats: () => http.get('/admin/memory/stats'),
  list: (params) => http.get('/admin/memory/list', { params }),
  workspaces: () => http.get('/admin/workspaces'),
  detail: (id, params) => http.get(`/admin/memory/${id}`, { params }),
  update: (id, params) => http.put(`/admin/memory/${id}`, params),
  delete: (id, params) => http.delete(`/admin/memory/${id}`, { params }),
  clearUser: (userId) => http.delete(`/admin/memory/user/${userId}`),
  recall: (params) => http.post('/admin/memory/recall', params),
  consolidate: () => http.post('/admin/memory/consolidate'),
  cronJobs: () => http.get('/admin/memory/cron-jobs'),
}

export const dashboardApi = {
  list: () => http.get('/admin/dashboard/shortcuts'),
  add: (body) => http.post('/admin/dashboard/shortcuts', body),
  remove: (id) => http.delete(`/admin/dashboard/shortcuts/${id}`),
}

export const pluginApi = {
  marketplace: (body) => http.post('/admin/plugin/marketplace', body || {}),
  detail: (pluginId) => http.post('/admin/plugin/detail', { pluginId }),
  publish: (body) => http.post('/admin/plugin/publish', body),
  install: (pluginId, config) => http.post('/admin/plugin/install', { pluginId, config }),
  uninstall: (installId) => http.post('/admin/plugin/uninstall', { installId }),
  installed: () => http.post('/admin/plugin/installed', {}),
  toggle: (installId, enabled) => http.post('/admin/plugin/toggle', { installId, enabled }),
  // P5 新增
  stats: () => http.get('/admin/plugin/stats'),
  installedDetail: () => http.get('/admin/plugin/installed/detail'),
  reloadAll: () => http.post('/admin/plugin/reload-all'),
}

// ── 审批中心 ──
export const approvalApi = {
  pendingReviews: async () => {
    const token = getToken()
    const res = await fetch('/api/admin/agents/pending-reviews', { headers: { Authorization: token } })
    if (!res.ok) throw new Error('获取待审批失败')
    return res.json()
  },
  mySubmissions: async (status = null) => {
    const token = getToken()
    let url = '/api/admin/agents/my-submissions'
    if (status) url += `?status=${status}`
    const res = await fetch(url, { headers: { Authorization: token } })
    if (!res.ok) throw new Error('获取提交记录失败')
    return res.json()
  },
  approve: async (agentId, action, reason = '') => {
    const token = getToken()
    const res = await fetch(`/api/admin/agents/${agentId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify({ action, reason })
    })
    if (!res.ok) throw new Error('审批操作失败')
    return res.json()
  },
  submitReview: (id, body) => http.post(`/admin/agents/${id}/submit-review`, body || {}),
}

export const toolApprovalApi = {
  pending: async () => {
    const token = getToken()
    const res = await fetch('/api/admin/tool-approval/pending', {
      headers: { Authorization: token }
    })
    if (!res.ok) throw new Error('获取待审批列表失败')
    return res.json()
  },
  review: async (dispatchId, action, reason = '') => {
    const token = getToken()
    const res = await fetch(`/api/admin/tool-approval/${dispatchId}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify({ action, reason })
    })
    if (!res.ok) throw new Error('审批操作失败')
    return res.json()
  },
}

// ── WebSocket 审批通知 ──
export const approvalWs = {
  _ws: null,
  _reconnectTimer: null,
  _listeners: new Map(),
  _reconnectDelay: 5000,
  _MAX_RECONNECT_DELAY: 60000,
  connect() {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) return
    const token = (getToken()).replace('Bearer ', '')
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/ws/approvals?token=${encodeURIComponent(token)}`
    try {
      this._ws = new WebSocket(wsUrl)
      // 连接成功后重置退避延迟（服务恢复后立即回退到 5s）
      this._ws.onopen = () => { this._reconnectDelay = 5000 }
      this._ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'pong') return
          // 通知所有监听器
          for (const [key, fn] of this._listeners) {
            try { fn(data) } catch {}
          }
        } catch {}
      }
      this._ws.onclose = () => {
        this._ws = null
        // 指数退避重连（5s → 10s → 20s → 40s → 60s 上限），防服务端宕机打爆
        if (this._reconnectTimer) clearTimeout(this._reconnectTimer)
        this._reconnectTimer = setTimeout(() => this.connect(), this._reconnectDelay)
        this._reconnectDelay = Math.min(this._reconnectDelay * 2, this._MAX_RECONNECT_DELAY)
      }
      this._ws.onerror = () => { this._ws?.close() }
    } catch {
      // WebSocket 不可用，降级到轮询
      this._ws = null
    }
  },
  disconnect() {
    if (this._reconnectTimer) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null }
    if (this._ws) { this._ws.onclose = null; this._ws.close(); this._ws = null }
    this._reconnectDelay = 5000
  },
  on(key, fn) { this._listeners.set(key, fn) },
  off(key) { this._listeners.delete(key) },
  isConnected() { return this._ws && this._ws.readyState === WebSocket.OPEN },
}

export default http
