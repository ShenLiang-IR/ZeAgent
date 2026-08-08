<template>
  <div class="workspace-dashboard">
    <!-- 上半区：应用中心（左）+ 日历（右） -->
    <div class="top-row">
      <div class="app-section">
        <div class="section-header">
          <h3 class="section-title">应用中心</h3>
          <span class="section-desc">收藏常用页面，一键直达</span>
        </div>
        <div class="app-cards" v-loading="loading">
          <div
            v-for="card in shortcuts"
            :key="card.id"
            class="app-card"
            @click="openApp(card)"
          >
            <span class="card-close" @click.stop="removeCard(card)" title="移除">×</span>
            <IconfontIcon :name="card.menu_icon || 'Agent列表'" :size="30" class="card-icon" />
            <span class="card-label">{{ card.menu_label }}</span>
          </div>
          <div class="app-card app-card-add" @click="openAddDialog">
            <span class="add-icon">+</span>
            <span class="card-label">添加应用</span>
          </div>
        </div>
        <el-empty v-if="!loading && !shortcuts.length" description="暂无收藏应用，点击「添加应用」开始" :image-size="80" style="margin-top: 40px;" />
      </div>
      <CalendarWidget :todo-dates="todoDates" class="calendar-right" />
    </div>

    <!-- 审批中心（与日历底端对齐） -->
    <ApprovalTabs class="approval-section" />

    <!-- 添加应用弹窗 -->
    <el-dialog v-model="showAddDialog" title="添加应用" width="480px" @close="selectedMenu = null">
      <p style="margin: 0 0 12px; font-size: 13px; color: #64748B;">从菜单中选择要收藏的页面：</p>
      <el-select
        v-model="selectedMenu"
        filterable
        placeholder="搜索菜单名称..."
        style="width: 100%"
        :filter-method="filterMenus"
      >
        <el-option
          v-for="item in filteredMenus"
          :key="item.index"
          :label="`${item.group} / ${item.label}`"
          :value="item.index"
        />
      </el-select>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!selectedMenu" :loading="adding" @click="addCard">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { dashboardApi, approvalApi } from '../api/index.js'
import IconfontIcon from '../components/IconfontIcon.vue'
import CalendarWidget from '../components/CalendarWidget.vue'
import ApprovalTabs from '../components/ApprovalTabs.vue'

const router = useRouter()
const loading = ref(false)
const shortcuts = ref([])
const showAddDialog = ref(false)
const selectedMenu = ref(null)
const adding = ref(false)
const searchQuery = ref('')

// ── 日历待办日期 ──
const todoDates = ref([])

const loadTodoDates = async () => {
  try {
    const isAdmin = (() => {
      try { const u = JSON.parse(localStorage.getItem('user_info') || 'null'); return u && u.role === 'admin' } catch { return false }
    })()
    let items = []
    if (isAdmin) {
      const res = await approvalApi.pendingReviews()
      items = res?.list || []
    } else {
      const res = await approvalApi.mySubmissions('2')
      items = res?.list || []
    }
    // 提取 updated_at / created_at 中的日期字符串
    todoDates.value = items
      .map(a => {
        const dt = a.updated_at || a.created_at
        if (!dt) return null
        // 尝试解析为 YYYY-MM-DD
        const m = String(dt).match(/^(\d{4}-\d{2}-\d{2})/)
        return m ? m[1] : null
      })
      .filter(Boolean)
  } catch { todoDates.value = [] }
}

// ── 用户角色 ──
const isAdmin = computed(() => {
  try { const u = JSON.parse(localStorage.getItem('user_info') || 'null'); return u && u.role === 'admin' } catch { return false }
})

// 全部可选菜单（与 MainLayout 的 allGroups 保持一致）
const allMenuItems = computed(() => {
  const groups = [
    { label: 'Agent 管理', children: [
      { index: '/agents', label: 'Agent 列表', icon: 'Agent列表' },
      { index: '/teams', label: '团队管理', icon: '团队管理' },
      { index: '/modes', label: '模式管理', icon: '模式管理' },
    ]},
    { label: '工具链', children: [
      { index: '/tools', label: '工具管理', icon: '工具管理' },
      { index: '/external-tools', label: '外部工具', icon: '外部工具' },
      { index: '/mcps', label: 'MCP 管理', icon: 'MCP管理' },
      { index: '/skills', label: 'Skill 管理', icon: 'Skill管理' },
    ]},
    { label: '会话管理', children: [
      { index: '/chat', label: '对话测试', icon: '对话测试' },
      { index: '/memory', label: '记忆管理', icon: '记忆管理' },
      { index: '/observability', label: '会话跟踪', icon: '会话跟踪' },
    ]},
    { label: '统计中心', children: [
      { index: '/stats/overview', label: '统计概览', icon: '统计概览' },
      ...(isAdmin.value ? [
        { index: '/stats/audit', label: '审计日志', icon: '审计日志' },
        { index: '/stats/usage', label: '用量统计', icon: '用量统计' },
      ] : []),
    ]},
    ...(isAdmin.value ? [
      { label: '平台管理', children: [
        { index: '/config', label: '系统配置', icon: '系统配置' },
        { index: '/users', label: '用户管理', icon: '用户管理' },
        { index: '/workspaces', label: '工作空间', icon: '工作空间管理' },
        { index: '/rag', label: '知识库', icon: '知识库管理' },
      ]},
      { label: '策略中心', children: [
        { index: '/prompts', label: '提示词', icon: '提示词管理' },
        { index: '/eval', label: '评测管理', icon: '评测管理' },
        { index: '/triggers', label: '触发器', icon: '触发器管理' },
        { index: '/subscriptions', label: '事件订阅', icon: '事件订阅' },
      ]},
    ] : []),
  ]
  const items = []
  for (const g of groups) {
    for (const c of g.children) {
      items.push({ ...c, group: g.label })
    }
  }
  return items
})

const filteredMenus = computed(() => {
  const savedPaths = new Set(shortcuts.value.map(s => s.menu_path))
  let items = allMenuItems.value.filter(i => !savedPaths.has(i.index))
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    items = items.filter(i => i.label.toLowerCase().includes(q) || i.group.toLowerCase().includes(q))
  }
  return items
})

const filterMenus = (query) => { searchQuery.value = query }

const loadShortcuts = async () => {
  loading.value = true
  try {
    const res = await dashboardApi.list()
    shortcuts.value = res?.data?.list || res?.list || []
  } catch (e) {
    ElMessage.error('加载工作台失败')
    shortcuts.value = []
  } finally {
    loading.value = false
  }
}

const openApp = (card) => { router.push(card.menu_path) }

const removeCard = async (card) => {
  try {
    await ElMessageBox.confirm(`确定移除「${card.menu_label}」？`, '移除应用', { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' })
  } catch { return }
  try {
    await dashboardApi.remove(card.id)
    shortcuts.value = shortcuts.value.filter(s => s.id !== card.id)
    ElMessage.success('已移除')
  } catch (e) {
    ElMessage.error('移除失败')
  }
}

const openAddDialog = () => {
  selectedMenu.value = null
  searchQuery.value = ''
  showAddDialog.value = true
}

const addCard = async () => {
  if (!selectedMenu.value) return
  const item = allMenuItems.value.find(i => i.index === selectedMenu.value)
  if (!item) return
  adding.value = true
  try {
    await dashboardApi.add({ menu_path: item.index, menu_label: item.label, menu_icon: item.icon })
    ElMessage.success(`已添加「${item.label}」`)
    showAddDialog.value = false
    await loadShortcuts()
  } catch (e) {
    ElMessage.error('添加失败')
  } finally {
    adding.value = false
  }
}

onMounted(() => {
  loadShortcuts()
  loadTodoDates()
})
</script>

<style scoped>
.workspace-dashboard {
  padding: 28px 32px;
  max-width: 1100px;
}

/* ── 上半区：应用中心 + 日历同行 ── */
.top-row {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 24px;
}
.app-section { flex: 1; min-width: 0; }
.calendar-right { flex-shrink: 0; }

/* ── 审批中心 ── */
.approval-section { margin-top: 28px; }

/* ── 应用中心 ── */
.app-section { /* wrapper */ }
.section-header {
  display: flex; align-items: baseline; gap: 12px;
  margin-bottom: 20px;
}
.section-title {
  font-size: 18px; font-weight: 700; color: #1E293B; margin: 0;
}
.section-desc {
  font-size: 13px; color: #94A3B8;
}
.app-cards {
  display: flex; flex-wrap: wrap; gap: 16px;
}
.app-card {
  width: 130px; height: 110px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 10px;
  background: #fff;
  border: 1px solid #E2E8F0;
  border-radius: 14px;
  cursor: pointer;
  position: relative;
  transition: all 0.2s ease;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.app-card:hover {
  border-color: #A5B4FC;
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.12);
  transform: translateY(-2px);
}
.card-icon { color: #6366F1; }
.card-label {
  font-size: 12.5px; font-weight: 500; color: #475569;
  text-align: center; line-height: 1.2;
  max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.card-close {
  position: absolute; top: 6px; right: 8px;
  width: 18px; height: 18px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 50%;
  font-size: 14px; color: #CBD5E1;
  opacity: 0; transition: all 0.15s ease;
}
.app-card:hover .card-close { opacity: 1; }
.card-close:hover { background: rgba(239, 68, 68, 0.12); color: #EF4444; }

.app-card-add {
  border-style: dashed;
  border-color: #CBD5E1;
  background: #F8FAFC;
}
.app-card-add:hover {
  border-color: #6366F1;
  background: rgba(99, 102, 241, 0.04);
}
.add-icon {
  font-size: 28px; font-weight: 300; color: #94A3B8; line-height: 1;
}
.app-card-add:hover .add-icon { color: #6366F1; }
</style>
