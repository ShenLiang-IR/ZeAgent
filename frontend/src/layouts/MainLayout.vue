<template>
  <div class="app-shell">
    <!-- 左侧图标导航条 -->
    <aside class="icon-rail" :class="{ collapsed: sidebarCollapsed }" @mouseenter="onRailHover" @mouseleave="onRailLeave">
      <!-- 工作空间头像（hover 显示完整名称） -->
      <el-tooltip :content="workspaceTitle" placement="right" :show-after="200">
        <div class="rail-item rail-workspace-item" :class="{ active: $route.path === '/stats/overview' }" @click="$router.push('/stats/overview')" @mouseenter="hoverGroup = null">
          <span class="workspace-badge">{{ workspaceBadge }}</span>
        </div>
      </el-tooltip>
      <div class="rail-items" v-show="!sidebarCollapsed || railHovering">
        <div
          v-for="group in visibleGroups"
          :key="group.index"
          class="rail-item"
          :class="{ active: isGroupActive(group) }"
          @mouseenter="hoverGroup = group"
          @mouseleave="hoverGroup = null"
          @click="navigateToFirst(group)"
        >
          <IconfontIcon :name="group.icon" :size="28" class="rail-icon" />
          <span class="rail-label">{{ group.label }}</span>
          <transition name="flyout">
            <div v-if="hoverGroup?.index === group.index" class="rail-flyout" @mouseenter="hoverGroup = group" @mouseleave="hoverGroup = null">
              <div
                v-for="item in group.children"
                :key="item.index"
                class="flyout-item"
                :class="{ active: $route.path === item.index }"
                @click.stop="openTab(item); hoverGroup = null"
              >
                <IconfontIcon :name="item.icon" :size="16" class="flyout-icon" />
                <span>{{ item.label }}</span>
              </div>
            </div>
          </transition>
        </div>
      </div>
      <!-- 折叠按钮 -->
      <div class="rail-collapse-btn" @click="sidebarCollapsed = !sidebarCollapsed" :title="sidebarCollapsed ? '固定菜单' : '折叠菜单'">
        <span class="collapse-arrow">{{ sidebarCollapsed ? '▶' : '◀' }}</span>
      </div>
    </aside>

    <!-- 右侧主区域 -->
    <div class="main-area">
      <!-- 顶部工具栏 -->
      <header class="top-bar">
        <!-- 中：可关闭的横向 Tab 导航 -->
        <div class="tab-bar" @contextmenu.prevent="onTabContextMenu">
          <div class="tab-scroll">
            <div
              v-for="tab in tabs"
              :key="tab.path"
              class="nav-tab"
              :class="{ active: activeTabPath === tab.path }"
              @click="switchTab(tab.path)"
              @contextmenu.stop="onTabRightClick($event, tab)"
            >
              <span class="tab-label">{{ tab.title }}</span>
              <span v-if="tab.closable" class="tab-close" @click.stop="closeTab(tab.path)">×</span>
            </div>
          </div>
        </div>
        <!-- Tab 右键菜单 -->
        <div v-if="tabCtxVisible" class="tab-ctx-menu" :style="{ left: tabCtxX + 'px', top: tabCtxY + 'px' }" @click.stop @mouseleave="tabCtxVisible = false">
          <div class="ctx-item" @click="closeAllTabs">关闭所有标签</div>
          <div class="ctx-item" @click="closeOtherTabs">关闭其他标签</div>
        </div>

        <!-- 右：操作区（搜索框 + 用户菜单） -->
        <div class="bar-right">
          <!-- 菜单搜索（位于 admin 左侧，保持间距） -->
          <div class="bar-search">
            <el-popover
              :visible="searchVisible"
              placement="bottom-end"
              :width="260"
              trigger="manual"
            >
              <template #reference>
                <div class="search-trigger" @click="searchVisible = !searchVisible">
                  <el-icon :size="15" class="search-icon"><Search /></el-icon>
                  <input
                    ref="searchInputRef"
                    v-model="searchQuery"
                    class="search-input"
                    placeholder="搜索菜单..."
                    @focus="searchVisible = true"
                    @input="searchVisible = true"
                    @keydown.esc="searchVisible = false; searchQuery = ''"
                  />
                </div>
              </template>
              <div class="search-results">
                <div
                  v-for="item in searchResults"
                  :key="item.index"
                  class="search-result-item"
                  @click="openTab(item); searchVisible = false; searchQuery = ''"
                >
                  <IconfontIcon :name="item.icon" :size="14" class="search-result-icon" />
                  <span class="search-result-label">{{ item.label }}</span>
                  <span class="search-result-group">{{ item.group }}</span>
                </div>
                <div v-if="searchQuery && !searchResults.length" class="search-empty">无匹配菜单</div>
              </div>
            </el-popover>
          </div>

          <!-- 审批通知（admin 可见） -->
          <el-badge v-if="isAdmin" :value="pendingCount" :hidden="!pendingCount" class="notify-badge" :max="99">
            <el-button text size="small" @click="router.push('/workspace')" title="待审批 Agent">
              <el-icon :size="20"><Bell /></el-icon>
            </el-button>
          </el-badge>

          <el-dropdown v-if="currentUser" trigger="click" @command="handleUserCommand">
            <span class="user-trigger">
              <span class="user-avatar">{{ (currentUser.username || 'U')[0].toUpperCase() }}</span>
              <span class="user-name">{{ currentUser.username }}</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="changePassword">修改密码</el-dropdown-item>
                <el-dropdown-item command="switchWorkspace">切换工作空间</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <!-- 内容区 -->
      <main class="content-body">
        <router-view />
      </main>
    </div>

    <el-dialog v-model="changePwdVisible" title="修改密码" width="440px">
      <el-form :model="changePwdForm" label-width="90px">
        <el-form-item label="旧密码"><el-input v-model="changePwdForm.oldPassword" type="password" show-password /></el-form-item>
        <el-form-item label="新密码"><el-input v-model="changePwdForm.newPassword" type="password" show-password /></el-form-item>
        <el-form-item label="确认密码"><el-input v-model="changePwdForm.confirmPassword" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer><el-button @click="changePwdVisible = false">取消</el-button><el-button type="primary" :loading="changePwdSaving" @click="doChangePassword">确认</el-button></template>
    </el-dialog>

    <el-dialog v-model="wsVisible" title="切换工作空间" width="460px" @open="loadWorkspaces">
      <div v-loading="wsLoading">
        <el-radio-group v-model="wsSelected" style="display: flex; flex-direction: column; gap: 10px;">
          <el-radio v-for="w in workspaces" :key="w.workspace_id" :value="w.workspace_id">{{ w.name }}<el-tag v-if="w.workspace_id === currentWorkspaceId" size="small" type="success" style="margin-left: 6px;">当前</el-tag></el-radio>
        </el-radio-group>
        <el-empty v-if="!wsLoading && !workspaces.length" description="无可切换的工作空间" />
      </div>
      <template #footer><el-button @click="wsVisible = false">取消</el-button><el-button type="primary" :loading="wsSwitching" :disabled="!wsSelected" @click="doSwitchWorkspace">切换</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, Bell } from '@element-plus/icons-vue'
import { authApi } from '../api/index.js'
import IconfontIcon from '../components/IconfontIcon.vue'

const router = useRouter()
const route = useRoute()
const hoverGroup = ref(null)

// ── 左侧菜单折叠 ──
const sidebarCollapsed = ref(false)
const railHovering = ref(false)
const onRailHover = () => { railHovering.value = true }
const onRailLeave = () => { railHovering.value = false }

const currentUser = computed(() => { try { return JSON.parse(localStorage.getItem('user_info') || 'null') } catch { return null } })
const isAdmin = computed(() => { const u = currentUser.value; return u && (u.role === 'admin') })
const pendingCount = ref(0)

const loadPendingCount = async () => {
  if (!isAdmin.value) return
  try {
    const token = localStorage.getItem('auth_token') || ''
    const res = await fetch('/api/admin/agents/pending-reviews', { headers: { Authorization: token } })
    const data = await res.json()
    pendingCount.value = data?.total || data?.list?.length || 0
  } catch { /* ignore */ }
}

onMounted(() => { loadPendingCount(); setInterval(loadPendingCount, 60000) })
const workspaceTitle = computed(() => {
  const u = currentUser.value
  if (!u) return 'Agent 管理平台'
  const wsName = u.workspace_name || u.username || 'Agent'
  return `${wsName}的工作空间`
})
const workspaceBadge = computed(() => {
  const u = currentUser.value
  if (!u) return 'A'
  const wsName = u.workspace_name || u.username || 'Agent'
  const chars = [...wsName]
  const firstChar = chars[0] || 'A'
  if (/[\u4e00-\u9fff]/.test(firstChar)) {
    return firstChar
  }
  return chars.slice(0, 2).join('').toUpperCase() || 'A'
})

const allGroups = computed(() => [
  { index: '/agents-group', label: 'Agent 管理', icon: 'Agent管理', children: [
    { index: '/agents', label: 'Agent 列表', icon: 'Agent列表' },
    { index: '/teams', label: '团队管理', icon: '团队管理' },
    { index: '/modes', label: '模式管理', icon: '模式管理' },
  ]},
  { index: '/toolchain', label: '工具链', icon: '工具链集合', children: [
    { index: '/plugins', label: '插件市场', icon: '插件市场' },
    { index: '/tools', label: '工具管理', icon: '工具管理' },
    { index: '/external-tools', label: '外部工具', icon: '外部工具' },
    { index: '/mcps', label: 'MCP 管理', icon: 'MCP管理' },
    { index: '/skills', label: 'Skill 管理', icon: 'Skill管理' },
  ]},
   { index: '/session-group', label: '会话管理', icon: '会话管理', children: [
     { index: '/chat', label: '对话测试', icon: '对话测试' },
     ...(isAdmin.value ? [
       { index: '/memory', label: '记忆管理', icon: '记忆管理' },
       { index: '/observability', label: '会话跟踪', icon: '会话跟踪' },
     ] : []),
   ]},
   ...(isAdmin.value ? [
     { index: '/strategy', label: '策略中心', icon: '策略中心', children: [
       { index: '/prompts', label: '提示词', icon: '提示词管理' },
       { index: '/eval', label: '评测管理', icon: '评测管理' },
       { index: '/triggers', label: '触发器', icon: '触发器管理' },
       { index: '/subscriptions', label: '事件订阅', icon: '事件订阅' },
       { index: '/security', label: '安全审查', icon: '安全审查' },
     ]},
     { index: '/platform', label: '平台管理', icon: '平台管理', children: [
       { index: '/config', label: '系统配置', icon: '系统配置' },
       { index: '/users', label: '用户管理', icon: '用户管理' },
       { index: '/workspaces', label: '工作空间', icon: '工作空间管理' },
       { index: '/rag', label: '知识库', icon: '知识库管理' },
     ]},
   ] : []),
   { index: '/stats-group', label: '统计中心', icon: '统计中心', children: [
     { index: '/stats/overview', label: '统计概览', icon: '统计概览' },
     ...(isAdmin.value ? [{ index: '/stats/audit', label: '审计日志', icon: '审计日志' }, { index: '/stats/usage', label: '用量统计', icon: '用量统计' }] : []),
   ]},
])
const visibleGroups = computed(() => allGroups.value)

// 扁平化所有子菜单项（用于查找）
const allMenuItems = computed(() => {
  const items = []
  for (const g of allGroups.value) {
    for (const c of g.children) {
      items.push({ ...c, group: g.label })
    }
  }
  return items
})

const isGroupActive = (group) => group.children.some(c => route.path === c.index || route.path.startsWith(c.index))
const navigateToFirst = (group) => { if (group.children.length) router.push(group.children[0].index) }

// ── 可关闭 Tab 导航 ──
const tabs = ref([{ path: '/workspace', title: '我的工作台', closable: false }])
const activeTabPath = computed(() => route.path)

const openTab = (item) => {
  const exists = tabs.value.find(t => t.path === item.index)
  if (!exists) {
    tabs.value.push({ path: item.index, title: item.label, closable: true })
  }
  router.push(item.index)
}

const switchTab = (path) => { router.push(path) }

const closeTab = (path) => {
  const idx = tabs.value.findIndex(t => t.path === path)
  if (idx === -1) return
  tabs.value.splice(idx, 1)
  if (tabs.value.length === 0) {
    // 关最后一个 → 回工作台
    tabs.value.push({ path: '/workspace', title: '我的工作台', closable: false })
    router.push('/workspace')
    return
  }
  // 如果关的是当前激活的 → 切到相邻
  if (route.path === path) {
    const next = tabs.value[Math.min(idx, tabs.value.length - 1)]
    router.push(next.path)
  }
}

// ── Tab 右键菜单 ──
const tabCtxVisible = ref(false)
const tabCtxX = ref(0)
const tabCtxY = ref(0)
const tabCtxPath = ref('')

const onTabRightClick = (event, tab) => {
  tabCtxPath.value = tab.path
  tabCtxX.value = event.clientX
  tabCtxY.value = event.clientY
  tabCtxVisible.value = true
}

const onTabContextMenu = () => {
  // 点击空白区也显示（关闭所有标签）
  tabCtxVisible.value = false
  setTimeout(() => {
    tabCtxPath.value = ''
    tabCtxVisible.value = true
  }, 10)
}

const closeAllTabs = () => {
  tabs.value = tabs.value.filter(t => !t.closable)
  tabCtxVisible.value = false
  if (!tabs.value.find(t => t.path === route.path)) {
    router.push('/workspace')
  }
}

const closeOtherTabs = () => {
  const current = tabCtxPath.value || route.path
  tabs.value = tabs.value.filter(t => !t.closable || t.path === current)
  tabCtxVisible.value = false
}

// 点击页面其他地方关闭右键菜单
if (typeof window !== 'undefined') {
  window.addEventListener('click', () => { tabCtxVisible.value = false })
}

// ── 菜单搜索 ──
const searchVisible = ref(false)
const searchQuery = ref('')
const searchInputRef = ref(null)
const searchResults = computed(() => {
  if (!searchQuery.value) return allMenuItems.value.slice(0, 8)
  const q = searchQuery.value.toLowerCase()
  return allMenuItems.value.filter(i => i.label.toLowerCase().includes(q) || i.group.toLowerCase().includes(q)).slice(0, 8)
})

// 监听路由变化 → 自动加 tab（从 flyout 点击或直接路由跳转）
watch(() => route.path, (newPath) => {
  if (!newPath || newPath === '/login' || newPath === '/workspace') return
  const item = allMenuItems.value.find(i => i.index === newPath)
  if (item) {
    const exists = tabs.value.find(t => t.path === newPath)
    if (!exists) {
      tabs.value.push({ path: newPath, title: item.label, closable: true })
    }
  }
}, { immediate: true })

// ── 用户操作 ──
const handleUserCommand = (command) => { if (command === 'changePassword') openChangePassword(); else if (command === 'switchWorkspace') openSwitchWorkspace(); else if (command === 'logout') logout() }
const logout = () => { localStorage.removeItem('auth_token'); localStorage.removeItem('user_info'); router.push('/login') }
const currentWorkspaceId = computed(() => currentUser.value?.workspace_id ?? null)

const changePwdVisible = ref(false); const changePwdSaving = ref(false); const changePwdForm = ref({ oldPassword: '', newPassword: '', confirmPassword: '' })
const openChangePassword = () => { changePwdForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }; changePwdVisible.value = true }
const doChangePassword = async () => {
  const { oldPassword, newPassword, confirmPassword } = changePwdForm.value
  if (!oldPassword || !newPassword) { ElMessage.warning('请填写旧密码与新密码'); return }
  if (newPassword !== confirmPassword) { ElMessage.warning('两次输入的新密码不一致'); return }
  changePwdSaving.value = true
  try { await authApi.changePassword(oldPassword, newPassword); ElMessage.success('密码修改成功'); changePwdVisible.value = false } catch (e) { ElMessage.error('修改失败：' + (e.message || '')) } finally { changePwdSaving.value = false }
}

const wsVisible = ref(false); const wsLoading = ref(false); const wsSwitching = ref(false); const workspaces = ref([]); const wsSelected = ref(null)
const openSwitchWorkspace = () => { wsSelected.value = currentWorkspaceId.value; wsVisible.value = true }
const loadWorkspaces = async () => { wsLoading.value = true; try { const res = await authApi.workspaces(); workspaces.value = res?.list || [] } catch (e) { ElMessage.error('加载失败'); workspaces.value = [] } finally { wsLoading.value = false } }
const doSwitchWorkspace = async () => {
  if (!wsSelected.value) return; wsSwitching.value = true
  try { const res = await authApi.switchWorkspace(wsSelected.value); if (res?.token) localStorage.setItem('auth_token', 'Bearer ' + res.token); if (res?.workspace_id != null) { try { const info = JSON.parse(localStorage.getItem('user_info') || '{}'); info.workspace_id = res.workspace_id; if (res?.workspace_name) info.workspace_name = res.workspace_name; localStorage.setItem('user_info', JSON.stringify(info)) } catch {} } ElMessage.success('已切换'); wsVisible.value = false; setTimeout(() => window.location.reload(), 300) } catch (e) { ElMessage.error('切换失败') } finally { wsSwitching.value = false }
}
</script>

<style scoped>
.app-shell { height: 100vh; display: flex; }

/* ── 左侧图标导航条（64px）── */
.icon-rail {
  width: 64px;
  flex-shrink: 0;
  background: #0F172A;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 12px;
  z-index: 200;
  box-shadow: 4px 0 24px rgba(0, 0, 0, 0.12);
}
/* 工作空间头像（替代原 logo，用 rail-item 结构） */
.rail-workspace-item {
  margin-bottom: 8px;
}
.workspace-badge {
  width: 32px; height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366F1, #22D3EE);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
  transition: transform 0.2s ease;
}
.rail-workspace-item:hover .workspace-badge { transform: scale(1.08); }

.rail-items { flex: 1; display: flex; flex-direction: column; gap: 14px; width: 100%; align-items: center; padding: 0 4px; }
.rail-item {
  width: 52px; min-height: 54px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 3px; padding: 5px 0;
  border-radius: 12px;
  cursor: pointer;
  position: relative;
  transition: all 0.2s ease;
  color: #64748B;
}
.rail-item:hover { background: rgba(99, 102, 241, 0.18); color: #C7D2FE; box-shadow: 0 0 12px rgba(99, 102, 241, 0.15); }
.rail-item.active { background: rgba(99, 102, 241, 0.22); color: #A5B4FC; box-shadow: 0 0 16px rgba(99, 102, 241, 0.2); }
.rail-item.active::before {
  content: '';
  position: absolute; left: -4px; top: 50%; transform: translateY(-50%);
  width: 3px; height: 24px; border-radius: 2px;
  background: linear-gradient(180deg, #6366F1, #22D3EE);
}
.rail-icon { transition: transform 0.2s ease; }
.rail-item:hover .rail-icon { transform: scale(1.15); }
.rail-label { font-size: 10px; font-weight: 500; opacity: 0.8; line-height: 1.1; margin-top: 2px; white-space: nowrap; }

/* ── hover 弹出二级面板 ── */
.rail-flyout {
  position: absolute;
  left: 56px; top: 0;
  min-width: 160px;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.6);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
  padding: 6px;
  z-index: 300;
}
.flyout-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px; border-radius: 7px;
  font-size: 12.5px; color: #475569; cursor: pointer;
  transition: all 0.15s ease;
}
.flyout-item:hover { background: rgba(99, 102, 241, 0.06); color: #1E293B; }
.flyout-item.active { background: rgba(99, 102, 241, 0.1); color: #6366F1; font-weight: 600; }
.flyout-icon { flex-shrink: 0; }

.flyout-enter-active { transition: all 0.15s ease; }
.flyout-enter-from { opacity: 0; transform: translateX(-8px); }
.flyout-leave-active { transition: all 0.1s ease; }
.flyout-leave-to { opacity: 0; transform: translateX(-8px); }

/* ── 右侧主区域 ── */
.main-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
.top-bar {
  height: 48px;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 16px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(16px) saturate(180%);
  -webkit-backdrop-filter: blur(16px) saturate(180%);
  border-bottom: 1px solid rgba(226, 232, 240, 0.5);
  flex-shrink: 0;
  z-index: 100;
  gap: 12px;
}

/* 搜索框（位于右侧操作区，admin 左边） */
.bar-search { flex-shrink: 0; }
.search-trigger {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 10px;
  border-radius: 8px;
  border: 1px solid #E2E8F0;
  background: #F8FAFC;
  cursor: text;
  transition: all 0.15s ease;
  width: 180px;
}
.search-trigger:focus-within {
  border-color: #A5B4FC;
  background: #fff;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.1);
}
.search-icon { color: #94A3B8; flex-shrink: 0; }
.search-input {
  border: none; outline: none; background: transparent;
  font-size: 12.5px; color: #334155;
  width: 100%; min-width: 0;
}
.search-input::placeholder { color: #94A3B8; }
.search-results { max-height: 280px; overflow-y: auto; }
.search-result-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; border-radius: 7px;
  cursor: pointer; transition: background 0.12s ease;
}
.search-result-item:hover { background: rgba(99, 102, 241, 0.06); }
.search-result-icon { color: #6366F1; flex-shrink: 0; }
.search-result-label { font-size: 13px; color: #334155; font-weight: 500; }
.search-result-group { font-size: 11px; color: #94A3B8; margin-left: auto; }
.search-empty { padding: 12px; text-align: center; font-size: 12.5px; color: #94A3B8; }
/* 中：Tab 导航 */
.tab-bar {
  flex: 1;
  overflow: hidden;
  min-width: 0;
}
.tab-scroll {
  display: flex; align-items: center; gap: 4px;
  overflow-x: auto; overflow-y: hidden;
  height: 100%;
  scrollbar-width: none;
}
.tab-scroll::-webkit-scrollbar { display: none; }

.nav-tab {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 12px;
  border-radius: 8px;
  font-size: 13px; font-weight: 500;
  color: #64748B;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
  flex-shrink: 0;
}
.nav-tab:hover { background: #F1F5F9; color: #1E293B; }
.nav-tab.active {
  background: rgba(99, 102, 241, 0.1);
  color: #6366F1;
  font-weight: 600;
}
.tab-label { user-select: none; }
.tab-close {
  display: flex; align-items: center; justify-content: center;
  width: 16px; height: 16px;
  border-radius: 50%;
  font-size: 14px;
  color: #94A3B8;
  line-height: 1;
  transition: all 0.15s ease;
}
.tab-close:hover {
  background: rgba(239, 68, 68, 0.15);
  color: #EF4444;
}

/* 右：操作区（搜索框 + 用户菜单，gap 保证搜索框与 admin 头像保持间距） */
.bar-right { display: flex; align-items: center; gap: 18px; flex-shrink: 0; }
.bar-action { color: #64748B !important; font-size: 13px; }
.bar-action:hover { color: #6366F1 !important; }
.user-trigger {
  display: flex; align-items: center; gap: 6px; cursor: pointer;
  padding: 4px 8px; border-radius: 8px; transition: background 0.2s ease;
}
.user-trigger:hover { background: rgba(99, 102, 241, 0.06); }
.user-avatar {
  width: 28px; height: 28px; border-radius: 50%;
  background: linear-gradient(135deg, #6366F1, #818CF8);
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 600;
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.2);
}
.user-name { font-size: 13px; color: #475569; }

.content-body { flex: 1; overflow-y: auto; background: var(--bg-page); }

/* ── 左侧折叠按钮 ── */
.rail-collapse-btn {
  width: 100%; height: 36px;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
  color: #475569;
  font-size: 12px;
  transition: all 0.2s ease;
  margin-top: auto;
  margin-bottom: 8px;
}
.rail-collapse-btn:hover { color: #A5B4FC; background: rgba(99, 102, 241, 0.12); }
.collapse-arrow { transition: transform 0.2s ease; }
.icon-rail.collapsed { width: 16px; padding: 0; }
.icon-rail.collapsed .rail-item,
.icon-rail.collapsed .rail-items { display: none; }
.icon-rail.collapsed .rail-collapse-btn { margin-top: 12px; }
/* hover 展开：鼠标移到折叠态左侧时临时显示内容 */
.icon-rail.collapsed:hover { width: 64px; }
.icon-rail.collapsed:hover .rail-workspace-item,
.icon-rail.collapsed:hover .rail-items { display: flex; }

/* ── Tab 右键菜单 ── */
.tab-ctx-menu {
  position: fixed;
  z-index: 1000;
  min-width: 120px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  border: 1px solid #E2E8F0;
  padding: 4px;
  font-size: 13px;
}
.ctx-item {
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  color: #475569;
  transition: background 0.12s;
  white-space: nowrap;
}
.ctx-item:hover { background: rgba(99, 102, 241, 0.08); color: #6366F1; }
</style>
