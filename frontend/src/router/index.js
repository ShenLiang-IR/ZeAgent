import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from '../layouts/MainLayout.vue'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/LoginView.vue'), meta: { title: '登录', public: true } },
  {
    path: '/',
    component: MainLayout,
    children: [
      { path: '', redirect: '/workspace' },
      { path: 'dashboard', redirect: '/workspace' },
      { path: 'workspace', name: 'WorkspaceDashboard', component: () => import('../views/WorkspaceDashboard.vue'), meta: { title: '我的工作台' } },
      { path: 'plugins', name: 'PluginMarketplace', component: () => import('../views/PluginMarketplace.vue'), meta: { title: '插件市场' } },
      { path: 'stats/overview', name: 'StatsOverview', component: () => import('../views/StatisticsOverview.vue'), meta: { title: '统计概览' } },
      { path: 'stats/audit', name: 'StatsAudit', component: () => import('../views/AuditLogView.vue'), meta: { title: '审计日志', adminOnly: true } },
      { path: 'stats/usage', name: 'StatsUsage', component: () => import('../views/UsageView.vue'), meta: { title: '用量统计', adminOnly: true } },
      { path: 'agents', name: 'AgentList', component: () => import('../views/AgentList.vue'), meta: { title: 'Agent 管理' } },
      { path: 'subagents', redirect: '/agents' },
      { path: 'tools', name: 'ToolList', component: () => import('../views/ToolList.vue'), meta: { title: '工具管理' } },
      { path: 'external-tools', name: 'ExternalToolList', component: () => import('../views/ExternalToolList.vue'), meta: { title: '外部工具' } },
      { path: 'mcps', name: 'McpList', component: () => import('../views/McpList.vue'), meta: { title: 'MCP 管理' } },
      { path: 'observability', name: 'LangfuseView', component: () => import('../views/LangfuseView.vue'), meta: { title: '会话跟踪', adminOnly: true } },
      { path: 'skills', name: 'SkillList', component: () => import('../views/SkillList.vue'), meta: { title: 'Skill 管理' } },
      { path: 'modes', name: 'ModeList', component: () => import('../views/ModeList.vue'), meta: { title: '模式管理' } },
      { path: 'prompts', name: 'PromptList', component: () => import('../views/PromptList.vue'), meta: { title: '提示词管理', adminOnly: true } },
      { path: 'eval', name: 'EvalList', component: () => import('../views/EvalList.vue'), meta: { title: '评测管理' } },
      { path: 'teams', name: 'TeamList', component: () => import('../views/TeamList.vue'), meta: { title: '团队管理' } },
      { path: 'subscriptions', name: 'SubscriptionList', component: () => import('../views/SubscriptionList.vue'), meta: { title: '事件订阅' } },
      { path: 'security', name: 'SensitiveWords', component: () => import('../views/SensitiveWordList.vue'), meta: { title: '安全审查', adminOnly: true } },
      { path: 'approvals', name: 'AgentApproval', component: () => import('../views/AgentApproval.vue'), meta: { title: 'Agent 审批', adminOnly: true } },
      { path: 'config', name: 'SystemConfig', component: () => import('../views/SystemConfig.vue'), meta: { title: '系统配置', adminOnly: true } },
      { path: 'chat', name: 'ChatView', component: () => import('../views/ChatView.vue'), meta: { title: '对话测试' } },
      { path: 'rag', name: 'RagView', component: () => import('../views/RagView.vue'), meta: { title: '知识库管理', adminOnly: true } },
      { path: 'memory', name: 'MemoryManage', component: () => import('../views/MemoryView.vue'), meta: { title: '记忆管理', adminOnly: true } },
      { path: 'users', name: 'UserManage', component: () => import('../views/UserManageView.vue'), meta: { title: '用户管理', adminOnly: true } },
      { path: 'workspaces', name: 'Workspace', component: () => import('../views/WorkspaceView.vue'), meta: { title: '工作空间管理', adminOnly: true } },
      { path: 'triggers', name: 'TriggerList', component: () => import('../views/TriggerList.vue'), meta: { title: '触发器管理', adminOnly: true } },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 登录守卫：未登录跳转 /login（public 路由除外）+ adminOnly 权限检查
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('auth_token')
  if (!to.meta.public && !token && to.path !== '/login') {
    next('/login')
  } else if (to.path === '/login' && token) {
    next('/workspace')
  } else if (to.meta.adminOnly) {
    // adminOnly 页面：非 admin 用户禁止访问
    try {
      const user = JSON.parse(localStorage.getItem('user_info') || 'null')
      if (!user || user.role !== 'admin') {
        next('/workspace')
        return
      }
    } catch { next('/login'); return }
    next()
  } else {
    next()
  }
})

export default router
