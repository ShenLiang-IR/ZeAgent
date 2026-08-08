<template>
  <div class="plugin-marketplace">
    <!-- 页面头部 -->
    <div class="pm-page-header">
      <div class="pm-title-row">
        <h2>
          <IconfontIcon name="插件市场" :size="24" class="pm-title-icon" />
          插件市场
        </h2>
        <span class="pm-subtitle">MCP 服务 · Skills 技能 · Tools 工具，发现、安装、赋能</span>
      </div>
      <div class="pm-main-actions">
        <el-button-group class="pm-util-group">
          <el-button size="small" :icon="Refresh" @click="loadStats">刷新统计</el-button>
          <el-button size="small" type="warning" plain :icon="Refresh" @click="reloadAll" :loading="reloading">热重载全部</el-button>
        </el-button-group>
        <el-input
          v-model="keyword" placeholder="搜索插件…" clearable style="width: 200px" size="default"
          @input="debouncedLoad" @clear="loadMarket"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="category" placeholder="全部分类" clearable style="width: 130px" @change="loadMarket">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <el-button type="primary" @click="openPublish">
          <el-icon><Plus /></el-icon> 发布插件
        </el-button>
      </div>
    </div>

    <!-- 分类快捷筛选 -->
    <div class="pm-category-bar">
      <el-button
        :type="category === '' ? 'primary' : 'default'"
        size="small" round
        @click="category = ''; loadMarket()"
      >全部</el-button>
      <el-button
        v-for="c in categories"
        :key="c"
        :type="category === c ? 'primary' : 'default'"
        size="small" round
        @click="category = c; loadMarket()"
      >
        <span class="pm-cat-dot" :class="'cat-' + c"></span>
        {{ c }}
      </el-button>
    </div>

    <!-- 统计面板 -->
    <div v-if="stats" class="pm-stats-row">
      <div class="pm-stat-card stat-total">
        <div class="pm-stat-card-icon"><el-icon :size="22"><Collection /></el-icon></div>
        <div class="pm-stat-card-body">
          <span class="pm-stat-card-num">{{ stats.total_installed || 0 }}</span>
          <span class="pm-stat-card-label">已安装插件</span>
        </div>
        <span class="pm-stat-card-badge">{{ stats.by_status?.enabled || 0 }} 启用</span>
      </div>
      <div class="pm-stat-card stat-healthy">
        <div class="pm-stat-card-icon"><el-icon :size="22"><CircleCheckFilled /></el-icon></div>
        <div class="pm-stat-card-body">
          <span class="pm-stat-card-num text-green">{{ stats.healthy || 0 }}</span>
          <span class="pm-stat-card-label">运行健康</span>
        </div>
      </div>
      <div class="pm-stat-card stat-unhealthy">
        <div class="pm-stat-card-icon"><el-icon :size="22"><WarningFilled /></el-icon></div>
        <div class="pm-stat-card-body">
          <span class="pm-stat-card-num text-red">{{ stats.unhealthy || 0 }}</span>
          <span class="pm-stat-card-label">状态异常</span>
        </div>
      </div>
      <div class="pm-stat-card stat-runtime">
        <div class="pm-stat-card-icon"><el-icon :size="22"><Monitor /></el-icon></div>
        <div class="pm-stat-card-body">
          <div class="pm-stat-card-row">
            <span class="pm-stat-card-num">{{ stats.runtime?.mcp_pool_size || 0 }}</span>
            <span class="pm-stat-card-label-inline">MCP 进程</span>
          </div>
          <div class="pm-stat-card-row">
            <span class="pm-stat-card-num">{{ (stats.runtime?.python_venvs || 0) + (stats.runtime?.node_envs || 0) + (stats.runtime?.go_binaries || 0) }}</span>
            <span class="pm-stat-card-label-inline">运行时环境</span>
          </div>
        </div>
      </div>
      <div class="pm-stat-card stat-types">
        <div class="pm-type-list">
          <div v-for="(cnt, type) in (stats.by_type || {})" :key="type" class="pm-type-row">
            <span class="pm-type-dot" :class="'dot-' + type"></span>
            <span class="pm-type-name">{{ typeLabel(type) }}</span>
            <span class="pm-type-cnt">{{ cnt }}</span>
          </div>
          <div v-if="!Object.keys(stats.by_type || {}).length" class="pm-type-empty">暂无安装</div>
        </div>
      </div>
    </div>

    <!-- 标签页 -->
    <el-tabs v-model="activeTab" @tab-change="onTabChange" class="pm-tabs">
      <el-tab-pane label="插件市场" name="market">
        <template #label>
          <span class="tab-label-wrap"><el-icon><Shop /></el-icon> 插件市场</span>
        </template>
      </el-tab-pane>
      <el-tab-pane label="已安装" name="installed">
        <template #label>
          <span class="tab-label-wrap"><el-icon><List /></el-icon> 已安装</span>
        </template>
      </el-tab-pane>
    </el-tabs>

    <!-- 市场卡片 -->
    <div v-if="activeTab === 'market'" class="pm-cards-grid" v-loading="loading">
      <div v-for="p in plugins" :key="p.plugin_id" class="pm-card">
        <div class="pm-card-icon-row">
          <div class="pm-card-icon" :class="typeIconBg(p.plugin_type)">
            <el-icon :size="20"><component :is="typeIcon(p.plugin_type)" /></el-icon>
          </div>
          <div class="pm-card-type-badge" :class="'badge-' + p.plugin_type">
            {{ typeLabel(p.plugin_type) }}
          </div>
        </div>
        <div class="pm-card-body">
          <h4 class="pm-card-name">{{ p.display_name || p.name }}</h4>
          <p class="pm-card-desc">{{ p.description || '暂无描述' }}</p>
        </div>
        <div class="pm-card-footer">
          <div class="pm-card-meta">
            <span class="pm-meta-item">{{ p.author || '官方' }}</span>
            <span class="pm-meta-sep">·</span>
            <span class="pm-meta-item">v{{ p.version }}</span>
            <span class="pm-meta-sep">·</span>
            <span class="pm-meta-item"><el-icon :size="12"><Download /></el-icon> {{ p.download_count || 0 }}</span>
          </div>
          <el-button
            size="small" round
            :type="installedSet.has(p.plugin_id) ? '' : 'primary'"
            :disabled="installedSet.has(p.plugin_id)"
            @click="install(p)"
          >
            <el-icon v-if="installedSet.has(p.plugin_id)"><Check /></el-icon>
            {{ installedSet.has(p.plugin_id) ? '已安装' : '安装' }}
          </el-button>
        </div>
      </div>
      <el-empty v-if="!loading && !plugins.length" description="暂无插件" :image-size="100">
        <el-button type="primary" @click="openPublish">发布第一个插件</el-button>
      </el-empty>
    </div>

    <!-- 已安装卡片 -->
    <div v-if="activeTab === 'installed'" class="pm-cards-grid" v-loading="loadingInstalled">
      <div v-for="item in installed" :key="item.install_id" class="pm-card pm-card-installed">
        <div class="pm-card-icon-row">
          <div class="pm-card-icon" :class="typeIconBg(item.plugin?.plugin_type)">
            <el-icon :size="20"><component :is="typeIcon(item.plugin?.plugin_type)" /></el-icon>
          </div>
          <div class="pm-card-type-badge" :class="'badge-' + (item.plugin?.plugin_type || 'mcp_server')">
            {{ typeLabel(item.plugin?.plugin_type) }}
          </div>
          <el-switch
            :model-value="item.enabled === '1'"
            @change="(v) => toggle(item, v)"
            class="pm-card-switch"
          />
        </div>
        <div class="pm-card-body">
          <h4 class="pm-card-name">{{ item.plugin?.display_name || item.plugin_id }}</h4>
          <p class="pm-card-desc">{{ item.plugin?.description || '暂无描述' }}</p>
        </div>
        <div class="pm-card-footer">
          <div class="pm-status-tags">
            <el-tag size="small" :type="item.enabled === '1' ? 'success' : 'info'" effect="dark">
              {{ item.enabled === '1' ? '已启用' : '已停用' }}
            </el-tag>
            <el-tag v-if="item.runtime_status" size="small"
              :type="item.runtime_status.healthy ? 'success' : 'danger'"
              effect="plain"
            >
              <el-icon :size="12" style="margin-right:2px">
                <CircleCheckFilled v-if="item.runtime_status.healthy" />
                <WarningFilled v-else />
              </el-icon>
              {{ runtimeStatusLabel(item.runtime_status) }}
            </el-tag>
          </div>
          <el-button size="small" type="danger" @click="uninstall(item)">卸载</el-button>
        </div>
      </div>
      <el-empty v-if="!loadingInstalled && !installed.length" description="尚未安装任何插件" :image-size="100">
        <el-button type="primary" @click="activeTab = 'market'">去市场发现</el-button>
      </el-empty>
    </div>

    <!-- 发布插件弹窗 -->
    <el-dialog v-model="showPublish" title="发布插件" width="620px" :close-on-click-modal="false">
      <el-form :model="pubForm" label-width="90px" size="default">
        <el-form-item label="插件类型" required>
          <div class="pub-type-selector">
            <div
              v-for="opt in typeOptions" :key="opt.value"
              class="pub-type-option" :class="{ active: pubForm.pluginType === opt.value }"
              @click="pubForm.pluginType = opt.value"
            >
              <el-icon :size="18"><component :is="opt.icon" /></el-icon>
              <span>{{ opt.label }}</span>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="技术名" required><el-input v-model="pubForm.name" placeholder="唯一标识，如 weather-mcp" /></el-form-item>
        <el-form-item label="显示名" required><el-input v-model="pubForm.displayName" placeholder="插件显示名称" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="pubForm.description" type="textarea" :rows="2" placeholder="简要描述插件功能" /></el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="分类"><el-input v-model="pubForm.category" placeholder="如 数据处理" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="版本"><el-input v-model="pubForm.version" placeholder="1.0.0" /></el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="作者"><el-input v-model="pubForm.author" placeholder="作者名称" /></el-form-item>

        <!-- MCP 配置 -->
        <template v-if="pubForm.pluginType === 'mcp_server'">
          <el-divider content-position="left"><el-icon><Connection /></el-icon> MCP 连接配置</el-divider>
          <el-form-item label="连接类型">
            <el-radio-group v-model="pubForm.connectionType">
              <el-radio-button value="stdio">stdio · 本地命令</el-radio-button>
              <el-radio-button value="sse">HTTP · SSE</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="pubForm.connectionType === 'stdio'" label="启动命令">
            <el-input v-model="pubForm.execCmd" placeholder="npx -y @modelcontextprotocol/server-weather" />
          </el-form-item>
          <el-form-item v-else label="连接 URL">
            <el-input v-model="pubForm.connectionUrl" placeholder="http://localhost:8080/sse" />
          </el-form-item>
        </template>

        <!-- Skill 配置 -->
        <template v-if="pubForm.pluginType.startsWith('skill_')">
          <el-divider content-position="left"><el-icon><Document /></el-icon> Skill 配置</el-divider>
          <el-form-item label="模块路径" required>
            <el-input v-model="pubForm.modulePath" placeholder="Python: skills.xxx  |  Node: index.js" />
          </el-form-item>
          <el-form-item label="函数名" required>
            <el-input v-model="pubForm.functionName" placeholder="execute 或 echo" />
          </el-form-item>
          <el-form-item label="依赖列表">
            <el-input v-model="pubForm.dependencies" type="textarea" :rows="2"
              :placeholder="pubForm.pluginType === 'skill_python' ? 'requests==2.31.0,numpy  (pip 格式)' : 'axios@1.6,lodash  (npm 格式)'" />
          </el-form-item>
        </template>

        <!-- Tool 配置 -->
        <template v-if="pubForm.pluginType === 'tool'">
          <el-divider content-position="left"><el-icon><Setting /></el-icon> Tool 配置</el-divider>
          <el-form-item label="返回描述">
            <el-input v-model="pubForm.returnDescription" type="textarea" :rows="2" placeholder="工具返回值描述" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="showPublish = false">取消</el-button>
        <el-button type="primary" :loading="publishing" @click="publish">
          <el-icon><Upload /></el-icon> 发布
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, markRaw } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Search, Refresh, Plus, Collection, CircleCheckFilled, WarningFilled, Monitor,
  Shop, List, Download, Check, Upload, Connection, Document, Setting
} from '@element-plus/icons-vue'
import IconfontIcon from '../components/IconfontIcon.vue'
import { pluginApi } from '../api/index.js'

const activeTab = ref('market')
const keyword = ref('')
const category = ref('')
const categories = ref([])
const plugins = ref([])
const installed = ref([])
const loading = ref(false)
const loadingInstalled = ref(false)
const stats = ref(null)
const reloading = ref(false)

const installedSet = computed(() => new Set(installed.value.map(i => i.plugin_id)))

// ── 类型展示映射 ──
const typeLabels = { mcp_server: 'MCP 服务', skill_python: 'Python 技能', skill_nodejs: 'Node.js 技能', skill_go: 'Go 技能', tool: '工具配置' }
const typeLabel = (t) => typeLabels[t] || (t || '').replace('_', ' ')
const typeIconBg = (t) => {
  const m = { mcp_server: 'icon-bg-mcp', skill_python: 'icon-bg-py', skill_nodejs: 'icon-bg-node', skill_go: 'icon-bg-go', tool: 'icon-bg-tool' }
  return m[t] || 'icon-bg-default'
}
const typeIcon = (t) => {
  const m = { mcp_server: markRaw(Connection), skill_python: markRaw(Document), skill_nodejs: markRaw(Document), skill_go: markRaw(Document), tool: markRaw(Setting) }
  return m[t] || markRaw(Setting)
}
const typeOptions = [
  { value: 'mcp_server', label: 'MCP 服务', icon: markRaw(Connection) },
  { value: 'skill_python', label: 'Python 技能', icon: markRaw(Document) },
  { value: 'skill_nodejs', label: 'Node.js 技能', icon: markRaw(Document) },
  { value: 'skill_go', label: 'Go 技能', icon: markRaw(Document) },
  { value: 'tool', label: '工具配置', icon: markRaw(Setting) },
]
const runtimeStatusLabel = (rs) => {
  if (!rs) return ''
  if (rs.healthy) return '正常运行'
  const t = rs.type
  if (t === 'mcp_server') return '无活跃进程'
  if (t === 'skill_python') return 'venv 未创建'
  if (t === 'skill_nodejs') return 'node env 未创建'
  if (t === 'skill_go') return 'binary 未编译'
  if (t === 'tool') return '配置缺失'
  return '异常'
}

// ── 搜索防抖 ──
let debounceTimer = null
const debouncedLoad = () => { clearTimeout(debounceTimer); debounceTimer = setTimeout(loadMarket, 300) }

// ── 数据加载 ──
const loadMarket = async () => {
  loading.value = true
  try {
    const res = await pluginApi.marketplace({ keyword: keyword.value, category: category.value, pageNo: 1, pageSize: 100 })
    plugins.value = res?.data?.list || []
    categories.value = res?.data?.categories || []
  } catch { ElMessage.error('加载插件市场失败') }
  finally { loading.value = false }
}
const loadInstalled = async () => {
  loadingInstalled.value = true
  try {
    const res = await pluginApi.installedDetail()
    installed.value = res?.data?.list || []
  } catch { ElMessage.error('加载已安装列表失败') }
  finally { loadingInstalled.value = false }
}
const loadStats = async () => {
  try { const r = await pluginApi.stats(); stats.value = r?.data || null } catch { /* 静默 */ }
}
const reloadAll = async () => {
  reloading.value = true
  try { await pluginApi.reloadAll(); ElMessage.success('热重载完成'); await loadStats(); if (activeTab.value === 'installed') await loadInstalled() }
  catch { ElMessage.error('热重载失败') }
  finally { reloading.value = false }
}
const onTabChange = (tab) => { if (tab === 'installed') loadInstalled(); else loadMarket() }

// ── 操作 ──
const install = async (p) => {
  try { await pluginApi.install(p.plugin_id); ElMessage.success(`已安装「${p.display_name || p.name}」`); await loadInstalled(); await loadMarket(); await loadStats() }
  catch (e) { ElMessage.error('安装失败：' + (e.message || '')) }
}
const uninstall = async (item) => {
  try { await ElMessageBox.confirm(`确定卸载「${item.plugin?.display_name || item.plugin_id}」？`, '卸载插件', { type: 'warning' }) } catch { return }
  try { await pluginApi.uninstall(item.install_id); ElMessage.success('已卸载'); await loadInstalled(); await loadMarket(); await loadStats() }
  catch { ElMessage.error('卸载失败') }
}
const toggle = async (item, val) => {
  try { await pluginApi.toggle(item.install_id, val); item.enabled = val ? '1' : '0'; ElMessage.success(val ? '已启用' : '已停用') }
  catch { ElMessage.error('操作失败') }
}

// ── 发布弹窗 ──
const showPublish = ref(false); const publishing = ref(false)
const pubForm = reactive({ pluginType: 'mcp_server', name: '', displayName: '', description: '', category: '', author: '', version: '1.0.0', connectionType: 'stdio', execCmd: '', connectionUrl: '', modulePath: '', functionName: '', dependencies: '', returnDescription: '' })
const openPublish = () => { Object.assign(pubForm, { pluginType: 'mcp_server', name: '', displayName: '', description: '', category: '', author: '', version: '1.0.0', connectionType: 'stdio', execCmd: '', connectionUrl: '', modulePath: '', functionName: '', dependencies: '', returnDescription: '' }); showPublish.value = true }
const publish = async () => {
  if (!pubForm.name || !pubForm.displayName) { ElMessage.warning('请填写技术名与显示名'); return }
  publishing.value = true
  try {
    const body = { name: pubForm.name, displayName: pubForm.displayName, description: pubForm.description, category: pubForm.category, author: pubForm.author, version: pubForm.version, pluginType: pubForm.pluginType }
    if (pubForm.pluginType === 'mcp_server') { body.mcpConfig = { connection_type: pubForm.connectionType, exec_cmd: pubForm.execCmd, connection_url: pubForm.connectionUrl, timeout: 30000 } }
    else if (pubForm.pluginType.startsWith('skill_')) {
      const deps = pubForm.dependencies.trim(); let depParsed = null
      if (deps) {
        if (pubForm.pluginType === 'skill_python') depParsed = deps.split(/[,\n]/).map(s => s.trim()).filter(Boolean)
        else { depParsed = {}; deps.split(/[,\n]/).map(s => s.trim()).filter(Boolean).forEach(s => { const [pkg, ver] = s.split('@'); depParsed[pkg.trim()] = (ver || '').trim() }) }
      }
      body.manifest = { module_path: pubForm.modulePath, function_name: pubForm.functionName, dependencies: depParsed || {} }
    } else if (pubForm.pluginType === 'tool') { body.manifest = { return_description: pubForm.returnDescription } }
    await pluginApi.publish(body)
    ElMessage.success('发布成功'); showPublish.value = false; await loadMarket(); await loadStats()
  } catch (e) { ElMessage.error('发布失败：' + (e.message || '')) }
  finally { publishing.value = false }
}

onMounted(() => { loadMarket(); loadInstalled(); loadStats() })
</script>

<style scoped>
.plugin-marketplace { padding: 24px 32px; }

/* ── 页面头部 ── */
.pm-page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; flex-wrap: wrap; gap: 16px; }
.pm-title-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.pm-title-row h2 { margin: 0; font-size: 20px; font-weight: 700; color: #1E293B; display: flex; align-items: center; gap: 8px; }
.pm-title-icon { color: #6366F1; }
.pm-subtitle { font-size: 13px; color: #94A3B8; }
.pm-main-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-left: auto; }
.pm-util-group { margin-right: 4px; }

/* ── 分类筛选栏 ── */
.pm-category-bar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; padding: 8px 0; }
.pm-cat-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.cat-网络请求 { background: #6366F1; }
.cat-开发工具 { background: #3B82F6; }
.cat-编码转换 { background: #F59E0B; }
.cat-文本处理 { background: #22C55E; }
.cat-数据处理 { background: #06B6D4; }
.cat-实用工具 { background: #8B5CF6; }
.cat-内容处理 { background: #EC4899; }
.cat-办公 { background: #F97316; }
.cat-测试 { background: #94A3B8; }

/* ── 统计面板 ── */
.pm-stats-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; margin-bottom: 20px; }
@media (max-width: 1200px) { .pm-stats-row { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 768px) { .pm-stats-row { grid-template-columns: repeat(2, 1fr); } }
.pm-stat-card {
  background: #fff; border: 1px solid #E2E8F0; border-radius: 14px; padding: 16px 18px;
  display: flex; align-items: flex-start; gap: 14px; transition: all .2s; position: relative;
}
.pm-stat-card:hover { border-color: #C7D2FE; box-shadow: 0 2px 12px rgba(99,102,241,.08); }
.pm-stat-card-icon { width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.stat-total .pm-stat-card-icon { background: #EEF2FF; color: #6366F1; }
.stat-healthy .pm-stat-card-icon { background: #ECFDF5; color: #22C55E; }
.stat-unhealthy .pm-stat-card-icon { background: #FEF2F2; color: #EF4444; }
.stat-runtime .pm-stat-card-icon { background: #FFF7ED; color: #F97316; }
.stat-types { flex-direction: column; }
.pm-stat-card-body { flex: 1; min-width: 0; }
.pm-stat-card-num { font-size: 24px; font-weight: 700; color: #1E293B; display: block; }
.pm-stat-card-label { font-size: 12px; color: #94A3B8; margin-top: 2px; display: block; }
.pm-stat-card-label-inline { font-size: 12px; color: #94A3B8; margin-left: 6px; }
.pm-stat-card-row { display: flex; align-items: baseline; }
.pm-stat-card-row + .pm-stat-card-row { margin-top: 4px; }
.pm-stat-card-badge { font-size: 11px; color: #6366F1; background: #EEF2FF; padding: 2px 8px; border-radius: 6px; position: absolute; top: 12px; right: 14px; }
.text-green { color: #22C55E !important; }
.text-red { color: #EF4444 !important; }

/* 类型分布 */
.pm-type-list { display: flex; flex-direction: column; gap: 4px; width: 100%; }
.pm-type-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.pm-type-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot-mcp_server { background: #6366F1; }
.dot-skill_python { background: #3B82F6; }
.dot-skill_nodejs { background: #22C55E; }
.dot-skill_go { background: #06B6D4; }
.dot-tool { background: #F59E0B; }
.pm-type-name { color: #64748B; flex: 1; }
.pm-type-cnt { color: #1E293B; font-weight: 600; }
.pm-type-empty { font-size: 12px; color: #CBD5E1; text-align: center; padding: 8px 0; }

/* ── Tabs ── */
.pm-tabs { margin-bottom: 16px; }
.pm-tabs :deep(.el-tabs__item) { font-size: 14px; height: 40px; line-height: 40px; }
.tab-label-wrap { display: flex; align-items: center; gap: 6px; }

/* ── 卡片网格（自适应列数）─── */
.pm-cards-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
/* 宽屏 ≥1440px：一行 4 列 */
@media (min-width: 1440px) {
  .pm-cards-grid { grid-template-columns: repeat(4, 1fr); }
}
/* 超宽屏 ≥1920px：一行 5 列 */
@media (min-width: 1920px) {
  .pm-cards-grid { grid-template-columns: repeat(5, 1fr); }
}
/* 窄屏 ≤768px：紧凑 */
@media (max-width: 768px) {
  .pm-cards-grid { grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
}
.pm-card {
  background: #fff; border: 1px solid #E2E8F0; border-radius: 16px; padding: 20px;
  display: flex; flex-direction: column; gap: 14px; transition: all .2s;
}
.pm-card:hover { border-color: #A5B4FC; box-shadow: 0 6px 24px rgba(99,102,241,.12); transform: translateY(-1px); }

/* 卡片头部：图标 + 类型标签 */
.pm-card-icon-row { display: flex; align-items: center; gap: 10px; }
.pm-card-icon {
  width: 44px; height: 44px; border-radius: 14px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; color: #fff;
}
.icon-bg-mcp { background: linear-gradient(135deg, #6366F1, #8B5CF6); }
.icon-bg-py { background: linear-gradient(135deg, #3B82F6, #60A5FA); }
.icon-bg-node { background: linear-gradient(135deg, #22C55E, #4ADE80); }
.icon-bg-go { background: linear-gradient(135deg, #06B6D4, #22D3EE); }
.icon-bg-tool { background: linear-gradient(135deg, #F59E0B, #FBBF24); }
.icon-bg-default { background: linear-gradient(135deg, #94A3B8, #CBD5E1); }

.pm-card-type-badge {
  font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 6px;
  letter-spacing: .3px;
}
.badge-mcp_server { background: #EEF2FF; color: #6366F1; }
.badge-skill_python { background: #DBEAFE; color: #3B82F6; }
.badge-skill_nodejs { background: #DCFCE7; color: #16A34A; }
.badge-skill_go { background: #CFFAFE; color: #0891B2; }
.badge-tool { background: #FEF3C7; color: #D97706; }

.pm-card-switch { margin-left: auto; }

/* 卡片内容 */
.pm-card-body { flex: 1; }
.pm-card-name { margin: 0 0 6px; font-size: 15px; font-weight: 600; color: #1E293B; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pm-card-desc { margin: 0; font-size: 13px; color: #64748B; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 39px; }

/* 卡片底部 */
.pm-card-footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.pm-card-meta { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.pm-meta-item { font-size: 12px; color: #94A3B8; display: flex; align-items: center; gap: 2px; }
.pm-meta-sep { font-size: 12px; color: #CBD5E1; }

.pm-status-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.pm-card-installed .pm-card-footer { justify-content: space-between; }

/* ── 发布弹窗 ── */
.pub-type-selector { display: flex; gap: 8px; flex-wrap: wrap; }
.pub-type-option {
  display: flex; align-items: center; gap: 6px; padding: 8px 14px; border: 1.5px solid #E2E8F0;
  border-radius: 10px; cursor: pointer; font-size: 13px; color: #64748B; transition: all .15s;
}
.pub-type-option:hover { border-color: #A5B4FC; color: #6366F1; }
.pub-type-option.active { border-color: #6366F1; color: #6366F1; background: #EEF2FF; font-weight: 600; }
</style>
