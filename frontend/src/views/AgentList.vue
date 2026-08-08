<template>
  <div class="page-container">
    <div class="table-toolbar">
      <span style="font-size: 16px; font-weight: 600;">Agent 管理</span>
      <div style="display: flex; gap: 8px; align-items: center;">
        <el-input v-model="search" placeholder="搜索 Agent 名称..." style="width: 220px" clearable />
        <el-button @click="loadData">刷新</el-button>
        <el-button type="success" @click="openMultiDispatch" :disabled="!selectedRows.length">并行调度 ({{ selectedRows.length }})</el-button>
        <el-button @click="loadDispatchHistory">调度历史</el-button>
        <el-button type="primary" @click="openCreate">新建 Agent</el-button>
      </div>
    </div>

    <!-- Agent 卡片网格 -->
    <div class="agent-cards" v-loading="loading">
      <div
        v-for="row in filteredList"
        :key="row.pr_key_id"
        class="agent-card"
        :class="{ 'agent-card-selected': selectedRows.some(r => r.pr_key_id === row.pr_key_id) }"
        @click="onCardClick(row)"
      >
        <!-- 选择框（左上角） -->
        <el-checkbox
          class="card-checkbox"
          :model-value="selectedRows.some(r => r.pr_key_id === row.pr_key_id)"
          @change="val => toggleSelect(row, val)"
          @click.stop
        />

        <!-- 详情预览（右上角 ⓘ 图标） -->
        <div class="card-info" @click.stop>
          <el-popover trigger="hover" placement="top" :width="300">
            <template #reference>
              <span class="card-info-icon" title="查看详情">ⓘ</span>
            </template>
            <div style="font-size: 13px; line-height: 1.6;">
              <p style="font-weight: 600; margin: 0 0 6px;">{{ row.agent_name }}</p>
              <p style="color: #64748B; margin: 0 0 6px;">{{ row.agent_description || '暂无描述' }}</p>
              <p style="margin: 2px 0;"><b>模型:</b> {{ row.model_id || '默认' }}</p>
              <p style="margin: 2px 0;"><b>Skills:</b> {{ row.tools?.join('、') || '无' }}</p>
              <p style="margin: 2px 0;"><b>MCP:</b> {{ row.mcp_tools?.join('、') || '无' }}</p>
              <p style="margin: 2px 0;"><b>提示词:</b></p>
              <pre style="max-height: 120px; overflow: auto; white-space: pre-wrap; font-size: 12px; margin: 4px 0 0 0;">{{ row.system_prompt || '-' }}</pre>
            </div>
          </el-popover>
        </div>

        <!-- hover 操作菜单（右上角偏移） -->
        <div class="card-actions" @click.stop>
          <el-dropdown trigger="click" @command="(cmd) => handleCommand(cmd, row)">
            <span class="card-more">⋮</span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="dispatch">调度</el-dropdown-item>
                <el-dropdown-item command="edit" divided>编辑</el-dropdown-item>
                <el-dropdown-item command="graph">关系图</el-dropdown-item>
                <el-dropdown-item command="version">版本管理</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <!-- 卡片主体（AI智能体 icon + 名称） -->
        <div class="card-body">
          <div class="card-agent-icon-wrap"><IconfontIcon name="AI智能体" :size="36" /></div>
          <span class="card-name">{{ row.agent_name }}</span>
        </div>

        <p class="card-desc">{{ row.agent_description || '暂无描述' }}</p>

        <!-- 标签行 -->
        <div class="card-tags">
          <el-tag size="small">{{ row.tools?.length || 0 }} Skills</el-tag>
          <el-tag size="small" type="warning">{{ row.mcp_tools?.length || 0 }} MCP</el-tag>
          <el-tag size="small" :type="visTag(row).type">{{ visTag(row).label }}</el-tag>
        </div>

        <!-- 状态行：发布状态 + 启动开关/提交审批 -->
        <div class="card-status" @click.stop>
          <el-tag size="small" :type="row.release_status === '1' ? 'success' : row.release_status === '2' ? 'warning' : 'info'">
            {{ row.release_status === '1' ? '已发布' : row.release_status === '2' ? '待审批' : '草稿' }}
          </el-tag>
          <!-- 已发布：显示启动开关 -->
          <el-switch
            v-if="row.release_status === '1'"
            :model-value="row.status === '1'"
            @change="val => toggleStatus(row, val)"
            size="small"
          />
          <!-- 待审批：审批中（不可重复提交；编辑即作废） -->
          <el-tag v-else-if="row.release_status === '2'" size="small" type="warning" effect="plain">审批中</el-tag>
          <!-- 草稿：显示提交审批按钮 -->
          <el-button
            v-else
            size="small"
            type="warning"
            @click="submitReview(row)"
          >提交审批</el-button>
        </div>
      </div>
    </div>

    <el-empty v-if="!loading && !filteredList.length" description="暂无 Agent，点击「新建 Agent」开始" :image-size="80" style="margin-top: 40px;" />

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="formVisible" :title="editing ? '编辑 Agent' : '新建 Agent'" width="740px">
      <el-form ref="agentFormRef" :model="form" :rules="formRules" label-width="120px">
        <el-form-item label="名称" prop="agentName">
          <el-input v-model="form.agentName" :disabled="editing" placeholder="如 text-analysis-agent" />
        </el-form-item>
        <el-form-item label="描述" prop="agentDescription">
          <el-input v-model="form.agentDescription" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="模型 ID" prop="modelId">
          <el-input v-model="form.modelId" placeholder="如 qwen3-coder-next:cloud" />
        </el-form-item>
        <el-form-item label="系统提示词" prop="systemPrompt">
          <el-input v-model="form.systemPrompt" type="textarea" :rows="5" placeholder="你是一个..." />
        </el-form-item>
        <el-form-item label="温度">
          <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" />
        </el-form-item>
        <el-form-item label="最大 Token">
          <el-input-number v-model="form.maxTokens" :min="100" :step="100" />
        </el-form-item>
        <el-form-item label="绑定 Skills">
          <el-select v-model="form.skills" multiple filterable placeholder="选择 Skills" style="width: 100%">
            <el-option v-for="s in selections.skills" :key="s.pr_key_id" :label="s.skill_name" :value="s.skill_name" />
          </el-select>
        </el-form-item>
        <el-form-item label="绑定 MCP">
          <el-select v-model="form.mcps" multiple filterable placeholder="选择 MCP 服务" style="width: 100%">
            <el-option v-for="m in selections.mcps" :key="m.pr_key_id" :label="m.mcp_name" :value="m.mcp_name" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <!-- 高级执行配置 -->
        <el-divider content-position="left">
          <el-button text size="small" @click="showAdvConfig = !showAdvConfig">
            高级执行配置 {{ showAdvConfig ? '▲' : '▼' }}
          </el-button>
        </el-divider>
        <template v-if="showAdvConfig">
          <el-form-item label="Agent 间委派">
            <el-switch v-model="form.agentConfig.delegation.enabled" active-text="允许委托其他 Agent" />
          </el-form-item>
          <el-form-item v-if="form.agentConfig.delegation.enabled" label="最大委派深度">
            <el-input-number v-model="form.agentConfig.delegation.maxDepth" :min="1" :max="5" />
          </el-form-item>
          <el-form-item label="辩论最大轮数">
            <el-input-number v-model="form.agentConfig.debate.maxRounds" :min="1" :max="5" />
          </el-form-item>
        </template>
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
    <el-dialog v-model="detailVisible" title="Agent 详情" width="760px">
      <el-descriptions v-if="detail" :column="1" border>
        <el-descriptions-item label="ID">{{ detail.pr_key_id }}</el-descriptions-item>
        <el-descriptions-item label="名称">{{ detail.agent_name }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ detail.agent_description || '-' }}</el-descriptions-item>
        <el-descriptions-item label="模型">{{ detail.model_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="系统提示词">
          <el-input type="textarea" :model-value="detail.system_prompt" :rows="5" readonly />
        </el-descriptions-item>
        <el-descriptions-item label="温度">{{ detail.temperature }}</el-descriptions-item>
        <el-descriptions-item label="最大 Token">{{ detail.max_tokens }}</el-descriptions-item>
        <el-descriptions-item label="Skills">
          <el-tag v-for="t in (detail.tools || [])" :key="t" size="small" style="margin: 2px">{{ t }}</el-tag>
          <span v-if="!(detail.tools || []).length">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="MCP 服务">
          <el-tag v-for="m in (detail.mcp_tools || [])" :key="m" type="warning" size="small" style="margin: 2px">{{ m }}</el-tag>
          <span v-if="!(detail.mcp_tools || []).length">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="外部工具">
          <el-tag v-for="e in (detail.external_tools || [])" :key="e" type="danger" size="small" style="margin: 2px">{{ e }}</el-tag>
          <span v-if="!(detail.external_tools || []).length">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="可见性">
          <el-tag size="small" :type="visTag(detail).type">{{ visTag(detail).label }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="detail.status === '1' ? 'success' : 'info'" size="small">{{ detail.status === '1' ? '启用' : '停用' }}</el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <!-- 调度详情对话框 -->
    <el-dialog v-model="dispatchVisible" :title="`调度详情 - ${dispatchData?.before?.agent_name || ''}`" width="820px" top="5vh">
      <div v-loading="dispatchLoading" style="min-height: 200px;">
        <template v-if="dispatchData">
          <el-divider content-position="left">执行前 - Agent 信息</el-divider>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="名称">{{ dispatchData.before.agent_name }}</el-descriptions-item>
            <el-descriptions-item label="模型">{{ dispatchData.before.model_id || '-' }}</el-descriptions-item>
            <el-descriptions-item label="温度">{{ dispatchData.before.temperature }}</el-descriptions-item>
            <el-descriptions-item label="最大Token">{{ dispatchData.before.max_tokens }}</el-descriptions-item>
            <el-descriptions-item label="Skills" :span="2">{{ (dispatchData.before.skills || []).join(', ') || '-' }}</el-descriptions-item>
            <el-descriptions-item label="MCP" :span="2">{{ (dispatchData.before.mcp_tools || []).join(', ') || '-' }}</el-descriptions-item>
            <el-descriptions-item label="系统提示词" :span="2">
              <el-input type="textarea" :model-value="dispatchData.before.system_prompt" :rows="3" readonly />
            </el-descriptions-item>
          </el-descriptions>
          <el-divider content-position="left">执行前 - 加载的工具</el-divider>
          <el-table :data="dispatchData.before.tools" border size="small">
            <el-table-column prop="name" label="工具名" width="180" />
            <el-table-column prop="category" label="类别" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="catTagType(row.category)">{{ row.category }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="描述" show-overflow-tooltip />
          </el-table>
          <el-divider content-position="left">执行测试（可选）</el-divider>
          <div style="display: flex; gap: 8px; margin-bottom: 10px;">
            <el-input v-model="testMessage" placeholder="输入测试消息（留空则不执行 LLM）" />
            <el-button type="primary" :loading="execLoading" @click="execDispatch">执行</el-button>
          </div>
          <template v-if="dispatchData.execution">
            <el-divider content-position="left">执行中 - 工具调用记录</el-divider>
            <el-table v-if="dispatchData.execution.steps && dispatchData.execution.steps.length" :data="dispatchData.execution.steps" border size="small">
              <el-table-column prop="type" label="类型" width="90">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.type === 'tool_call' ? 'primary' : 'success'">{{ row.type === 'tool_call' ? '调用' : '返回' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="工具名" width="170" />
              <el-table-column label="参数/结果" show-overflow-tooltip>
                <template #default="{ row }">{{ row.detail }}</template>
              </el-table-column>
            </el-table>
            <div v-else style="color:#999;padding:8px 0;">无工具调用（LLM 直接回复）</div>
            <el-divider content-position="left">执行结果</el-divider>
            <el-alert v-if="dispatchData.execution.error" type="error" :title="dispatchData.execution.error" :closable="false" />
            <el-input v-else type="textarea" :model-value="dispatchData.execution.response" :rows="5" readonly />
          </template>
          <el-divider content-position="left">最终摘要</el-divider>
          <el-alert type="success" :title="dispatchData.final.summary" :closable="false" />
        </template>
      </div>
    </el-dialog>

    <!-- 节点关系图对话框 -->
    <el-dialog v-model="graphVisible" :title="`节点关系图 - ${graphAgentName}`" width="780px" top="5vh">
      <div style="margin-bottom: 12px; display: flex; gap: 8px;">
        <el-button size="small" @click="exportGraph('png')" :disabled="graphLoading">导出 PNG</el-button>
        <el-button size="small" @click="exportGraph('jpeg')" :disabled="graphLoading">导出 JPEG</el-button>
      </div>
      <div ref="graphContainer" v-loading="graphLoading" style="min-height: 400px; border: 1px solid #eee; padding: 16px; text-align: center;"></div>
    </el-dialog>

    <!-- 多 Agent 并行调度对话框 -->
    <el-dialog v-model="multiVisible" :title="multiMode === 'dag' ? 'DAG 依赖调度' : '多 Agent 并行调度'" width="820px" top="5vh">
      <div style="margin-bottom: 12px;">
        <span style="margin-right: 8px;">选中 Agent:</span>
        <el-tag v-for="a in selectedRows" :key="a.pr_key_id" style="margin: 2px">{{ a.agent_name }}</el-tag>
      </div>
      <el-radio-group v-model="multiMode" style="margin-bottom: 12px;">
        <el-radio label="parallel">并行</el-radio>
        <el-radio label="sequential">顺序</el-radio>
        <el-radio label="dag">DAG 依赖</el-radio>
        <el-radio label="langgraph">LangGraph</el-radio>
      </el-radio-group>
      <div v-if="multiMode === 'dag' && selectedRows.length" style="margin-bottom: 12px; padding: 8px; background: #F1F5F9; border-radius: 4px;">
        <div v-for="(row, i) in selectedRows" :key="i" style="margin-bottom: 6px;">
          <span style="margin-right: 8px;">{{ i }}. {{ row.agent_name }}</span>
          <span style="margin-right: 4px;">依赖:</span>
          <el-select v-model="dagDeps[i]" multiple placeholder="选依赖 task" style="width: 280px;" size="small">
            <el-option v-for="j in selectedRows.length" :key="j-1" :label="'task ' + (j-1)" :value="j-1" :disabled="j-1 === i" />
          </el-select>
        </div>
      </div>
      <div style="display: flex; gap: 8px; margin-bottom: 12px;">
        <el-input v-model="multiMessage" placeholder="输入消息..." @keydown.enter.ctrl="sendMultiDispatch" />
        <el-button type="primary" :loading="multiSending" :disabled="!selectedRows.length" @click="sendMultiDispatch">发送</el-button>
      </div>
      <el-divider />
      <div style="max-height: 450px; overflow-y: auto;">
        <el-card v-for="(ch, tid) in multiChannels" :key="tid" style="margin-bottom: 10px;">
          <template #header>
            <span style="font-weight: 600;">{{ ch.agent || tid }}</span>
            <el-tag size="small" :type="ch.done ? 'success' : 'warning'" style="margin-left: 8px">{{ ch.done ? '完成' : '执行中' }}</el-tag>
          </template>
          <div style="white-space: pre-wrap;">{{ ch.content || (ch.done ? '(无回复)' : '等待中...') }}</div>
        </el-card>
        <div v-if="!Object.keys(multiChannels).length" style="text-align: center; color: #ccc; padding: 30px;">发送消息后各 Agent 回复将在此分通道显示</div>
      </div>
    </el-dialog>

    <!-- 版本管理 -->
    <el-dialog v-model="versionVisible" :title="`版本管理 - ${versionAgent?.agent_name || ''}`" width="880px" top="5vh">
      <div style="margin-bottom: 16px; display: flex; align-items: center; gap: 8px;">
        <el-input v-model="newVersion.version_no" placeholder="版本号如 1.0.1" style="width: 150px;" />
        <el-input v-model="newVersion.version_description" placeholder="版本说明" style="width: 280px;" />
        <el-button type="primary" @click="createVersion" :loading="versionSaving">创建快照</el-button>
        <el-button @click="openDiffDialog">配置 Diff</el-button>
      </div>
      <el-table :data="versions" border size="small" v-loading="versionLoading">
        <el-table-column prop="version_no" label="版本" width="100" />
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="versionStatusType(row.status)">{{ versionStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version_description" label="说明" show-overflow-tooltip />
        <el-table-column prop="create_time" label="创建时间" width="160" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" @click="rollbackVersion(row)" v-if="row.status !== 'draft'" title="恢复工作副本并回草稿，需重新提交审批">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>
      <!-- diff 子对话框 -->
      <el-dialog v-model="diffVisible" title="版本配置 Diff" width="720px" append-to-body>
        <div style="margin-bottom: 12px; display: flex; gap: 8px; align-items: center;">
          <span>版本1</span>
          <el-select v-model="diffForm.v1" placeholder="选版本" style="width: 130px;">
            <el-option v-for="v in versions" :key="v.version_no" :label="v.version_no" :value="v.version_no" />
          </el-select>
          <span>版本2</span>
          <el-select v-model="diffForm.v2" placeholder="选版本" style="width: 130px;">
            <el-option v-for="v in versions" :key="v.version_no" :label="v.version_no" :value="v.version_no" />
          </el-select>
          <el-button size="small" @click="loadDiff" :loading="diffLoading">对比</el-button>
        </div>
        <el-table :data="diffResult" border size="small">
          <el-table-column label="字段" width="150"><template #default="{ row }">{{ row[0] }}</template></el-table-column>
          <el-table-column label="版本1"><template #default="{ row }">{{ row[1]?.v1 }}</template></el-table-column>
          <el-table-column label="版本2"><template #default="{ row }">{{ row[1]?.v2 }}</template></el-table-column>
          <el-table-column label="变化" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row[1]?.changed ? 'danger' : 'info'">{{ row[1]?.changed ? '已变' : '相同' }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-dialog>
    </el-dialog>

    <!-- ④调度历史 dashboard -->
    <el-dialog v-model="historyVisible" title="调度历史" width="820px" top="5vh">
      <el-table :data="dispatchHistory" border size="small" v-loading="historyLoading">
        <el-table-column prop="mode" label="模式" width="80" />
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'completed' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="消息" show-overflow-tooltip />
        <el-table-column prop="error" label="错误" show-overflow-tooltip width="150" />
        <el-table-column prop="create_time" label="时间" width="160" />
      </el-table>
    </el-dialog>
  </div>
  <PlanReviewDialog v-model="reviewVisible" :data="reviewData" />
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { agentApi, chatApi, versionApi } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import PlanReviewDialog from '../components/PlanReviewDialog.vue'
import IconfontIcon from '../components/IconfontIcon.vue'
import mermaid from 'mermaid'

const router = useRouter()
const route = useRoute()

const list = ref([])
const reviewVisible = ref(false)
const reviewData = ref(null)
const loading = ref(false)
const search = ref('')
const selections = ref({ tools: [], skills: [], mcps: [] })

const formVisible = ref(false)
const editing = ref(false)
const saving = ref(false)
const showAdvConfig = ref(false)
const form = ref(emptyForm())
const agentFormRef = ref(null)

const formRules = {
  agentName: [
    { required: true, message: '请输入 Agent 名称', trigger: 'blur' },
    { min: 2, max: 100, message: '名称长度 2-100 字符', trigger: 'blur' },
  ],
  systemPrompt: [
    { required: true, message: '请输入系统提示词', trigger: 'blur' },
  ],
}

const isAdmin = computed(() => {
  try {
    const userInfo = JSON.parse(localStorage.getItem('user_info') || '{}')
    return userInfo.role === 'admin'
  } catch { return false }
})

const detailVisible = ref(false)
const detail = ref(null)

// Agent 版本管理
const versionVisible = ref(false)
const versionAgent = ref(null)
const versions = ref([])
const versionLoading = ref(false)
const versionSaving = ref(false)
const newVersion = ref({ version_no: '', version_description: '' })
const diffVisible = ref(false)
const diffForm = ref({ v1: '', v2: '' })
const diffResult = ref([])
const diffLoading = ref(false)

// 调度详情
const dispatchVisible = ref(false)
const dispatchData = ref(null)
const dispatchLoading = ref(false)
const testMessage = ref('')
const execLoading = ref(false)
const currentAgentId = ref('')

// 节点关系图
const graphVisible = ref(false)
const graphAgentName = ref('')
const graphLoading = ref(false)
const graphContainer = ref(null)
let mermaidInitialized = false

// 多 agent 并行调度
const selectedRows = ref([])
const multiVisible = ref(false)
const teamDispatchId = ref('')  // 团队调度 teamId（从 query 预选）
const multiMessage = ref('')
const multiSending = ref(false)
const multiChannels = ref({})
const multiMode = ref('parallel')
const dagDeps = ref({})
const historyVisible = ref(false)
const dispatchHistory = ref([])
const historyLoading = ref(false)

function emptyForm() {
  return {
    prKeyId: '',
    agentName: '',
    agentDescription: '',
    modelId: '',
    systemPrompt: '',
    temperature: 0.7,
    maxTokens: 2000,
    skills: [],
    mcps: [],
    enabled: true,
    visibility: 'private',
    agentConfig: {
      delegation: { enabled: false, maxDepth: 2 },
      debate: { maxRounds: 2 },
    },
  }
}

const filteredList = computed(() => {
  if (!search.value) return list.value
  const s = search.value.toLowerCase()
  return list.value.filter(a => a.agent_name?.toLowerCase().includes(s))
})

// 三层可见性 → 标签（兼容旧 is_public 字段）
const visTag = (row) => {
  const v = row.visibility || (row.is_public === 1 ? 'public' : 'workspace')
  if (v === 'public') return { type: 'success', label: '全局' }
  if (v === 'private') return { type: 'info', label: '个人' }
  return { type: 'warning', label: '空间' }
}

const loadData = async () => {
  loading.value = true
  try {
    const data = await agentApi.getList()
    list.value = data?.agents ?? []
  } catch (e) {
    ElMessage.warning('加载失败，请确保后端服务已启动')
  } finally {
    loading.value = false
  }
}

const loadSelections = async () => {
  try {
    const data = await agentApi.getSelections()
    selections.value = data || { tools: [], skills: [], mcps: [] }
  } catch (e) {
    console.error('load selections failed', e)
  }
}

const openCreate = () => {
  editing.value = false
  form.value = emptyForm()
  formVisible.value = true
}

const openEdit = (row) => {
  editing.value = true
  form.value = {
    prKeyId: String(row.pr_key_id),
    agentName: row.agent_name,
    agentDescription: row.agent_description || '',
    modelId: row.model_id || '',
    systemPrompt: row.system_prompt || '',
    temperature: row.temperature ?? 0.7,
    maxTokens: row.max_tokens ?? 2000,
    skills: row.tools || [],
    mcps: row.mcp_tools || [],
    enabled: row.status === '1',
    visibility: row.visibility || (row.is_public === 1 ? 'public' : 'workspace'),
  }
  formVisible.value = true
}

const save = async () => {
  if (!agentFormRef.value) return
  try {
    await agentFormRef.value.validate()
  } catch {
    return  // 校验失败，el-form 会自动显示错误
  }
  saving.value = true
  try {
    if (editing.value) {
      await agentApi.update(form.value.prKeyId, form.value)
      ElMessage.success('更新成功')
    } else {
      await agentApi.create(form.value)
      ElMessage.success('创建成功')
    }
    formVisible.value = false
    await loadData()
  } catch (e) {
    const msg = e.response?.data?.detail || e.message || '操作失败'
    ElMessage.error(msg)
  } finally {
    saving.value = false
  }
}

// 状态/可见性 列内直接切换（不进编辑表单）
const toggleStatus = async (row, val) => {
  try {
    await agentApi.toggle(row.pr_key_id, val)
    row.status = val ? '1' : '0'
    ElMessage.success(val ? '已启用' : '已停用')
  } catch (e) {
    ElMessage.error('切换失败：' + (e.message || ''))
  }
}

/** 卡片点击：已发布+已启用→对话，其他→编辑 */
const onCardClick = (row) => {
  if (row.release_status === '1' && row.status === '1') {
    chatWithAgent(row)
  } else {
    openEdit(row)
  }
}

const chatWithAgent = (row) => {
  router.push({ path: '/chat', query: { agent: String(row.pr_key_id) } })
}

const submitReview = async (row) => {
  try {
    const { value: desc } = await ElMessageBox.prompt(
      '将自动生成下一版本号。可填写版本说明（可选）：',
      `提交审批 - ${row.agent_name}`,
      {
        confirmButtonText: '提交审批',
        cancelButtonText: '取消',
        inputType: 'textarea',
        inputPlaceholder: '版本说明（可选，如：修复 xxx / 新增 xxx',
        inputValidator: () => true,
      }
    )
    const res = await agentApi.submitReview(row.pr_key_id, { version_description: desc || '' })
    ElMessage.success(`已提交审批（版本 ${res.data?.version_no || ''}）`)
    await loadData()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error('提交失败: ' + (e.response?.data?.detail || e.message || ''))
  }
}

const handleCommand = (cmd, row) => {
  if (cmd === 'graph') showGraph(row)
  else if (cmd === 'version') openVersion(row)
  else if (cmd === 'edit') openEdit(row)
  else if (cmd === 'delete') remove(row)
  else if (cmd === 'dispatch') dispatchAgent(row)
}

// ── Agent 版本管理 ──
const openVersion = async (row) => {
  versionAgent.value = row
  versionVisible.value = true
  newVersion.value = { version_no: '', version_description: '' }
  await loadVersions(row)
}

const loadVersions = async (row) => {
  const agent = row || versionAgent.value
  if (!agent) return
  versionLoading.value = true
  try {
    const res = await versionApi.list(agent.pr_key_id)
    versions.value = res.versions || []
  } catch (e) {
    ElMessage.error('加载版本失败')
    versions.value = []
  } finally {
    versionLoading.value = false
  }
}

const createVersion = async () => {
  if (!newVersion.value.version_no) { ElMessage.warning('请输入版本号'); return }
  versionSaving.value = true
  try {
    await versionApi.create(versionAgent.value.pr_key_id, newVersion.value)
    ElMessage.success('快照已创建（draft 状态）')
    newVersion.value = { version_no: '', version_description: '' }
    await loadVersions()
  } catch (e) {
    ElMessage.error('创建失败')
  } finally {
    versionSaving.value = false
  }
}

const rollbackVersion = async (row) => {
  try {
    await ElMessageBox.confirm(`回滚到版本 ${row.version_no}？（agent 配置恢复为该版本快照）`, '确认回滚', { type: 'warning' })
    await versionApi.rollback(versionAgent.value.pr_key_id, row.version_no)
    ElMessage.success('已回滚，agent 配置已恢复')
    await loadData()
  } catch (e) { /* 取消 */ }
}

const openDiffDialog = () => {
  diffForm.value = { v1: '', v2: '' }
  diffResult.value = []
  diffVisible.value = true
}

const loadDiff = async () => {
  if (!diffForm.value.v1 || !diffForm.value.v2) { ElMessage.warning('请选两个版本'); return }
  if (diffForm.value.v1 === diffForm.value.v2) { ElMessage.warning('请选不同版本'); return }
  diffLoading.value = true
  try {
    const res = await versionApi.diff(versionAgent.value.pr_key_id, diffForm.value.v1, diffForm.value.v2)
    diffResult.value = Object.entries(res || {})
  } catch (e) {
    ElMessage.error('对比失败')
    diffResult.value = []
  } finally {
    diffLoading.value = false
  }
}

const showDetail = async (row) => {
  try {
    const data = await agentApi.getDetail(row.pr_key_id)
    detail.value = data?.agent || row
  } catch {
    detail.value = row
  }
  detailVisible.value = true
}

const catTagType = (cat) => {
  const m = { mcp: 'warning', skill: 'success', api: 'primary', built_in: 'info', knowledge: 'danger' }
  return m[cat] || 'info'
}

// 版本状态 → 中文标签/颜色（pending_review/rejected/invalidated 为审批流新增态）
const versionStatusLabel = (s) => {
  const m = { published: '已发布', archived: '已归档', pending_review: '待审批', rejected: '已驳回', invalidated: '已作废', draft: '草稿' }
  return m[s] || s
}
const versionStatusType = (s) => {
  const m = { published: 'success', archived: 'info', pending_review: 'warning', rejected: 'danger', invalidated: 'info', draft: 'info' }
  return m[s] || 'info'
}

const dispatchAgent = async (row) => {
  currentAgentId.value = String(row.pr_key_id)
  testMessage.value = ''
  dispatchData.value = null
  dispatchVisible.value = true
  dispatchLoading.value = true
  try {
    const data = await agentApi.dispatch(currentAgentId.value)
    dispatchData.value = data
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '调度失败')
    dispatchVisible.value = false
  } finally {
    dispatchLoading.value = false
  }
}

const execDispatch = async () => {
  if (!testMessage.value.trim() || execLoading.value) return
  execLoading.value = true
  try {
    const data = await agentApi.dispatch(currentAgentId.value, { testMessage: testMessage.value })
    dispatchData.value = data
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '执行失败')
  } finally {
    execLoading.value = false
  }
}

const buildMermaidGraph = (row) => {
  const skills = row.tools || []
  const mcps = row.mcp_tools || []
  const apis = row.external_tools || []
  const lines = ['flowchart LR', '  START([Start]) --> AGENT']
  lines.push(`  AGENT["${row.agent_name}"]`)
  const leaves = []
  skills.forEach((s, i) => {
    const id = `SK${i}`
    lines.push(`  AGENT --> ${id}[["Skill: ${s}"]]`)
    leaves.push(id)
  })
  mcps.forEach((m, i) => {
    const id = `MC${i}`
    lines.push(`  AGENT --> ${id}[["MCP: ${m}"]]`)
    leaves.push(id)
  })
  apis.forEach((a, i) => {
    const id = `API${i}`
    lines.push(`  AGENT --> ${id}[["API: ${a}"]]`)
    leaves.push(id)
  })
  if (leaves.length === 0) {
    lines.push('  AGENT --> END([End])')
  } else {
    leaves.forEach(id => lines.push(`  ${id} --> END([End])`))
  }
  return lines.join('\n')
}

const showGraph = async (row) => {
  graphAgentName.value = row.agent_name
  graphVisible.value = true
  graphLoading.value = true
  await nextTick()
  try {
    if (!mermaidInitialized) {
      mermaid.initialize({ startOnReady: false, theme: 'default', securityLevel: 'loose', flowchart: { htmlLabels: false } })
      mermaidInitialized = true
    }
    const graphDef = buildMermaidGraph(row)
    if (graphContainer.value) {
      graphContainer.value.innerHTML = ''
      const { svg } = await mermaid.render('graphSvg_' + Date.now(), graphDef)
      graphContainer.value.innerHTML = svg
    }
  } catch (e) {
    ElMessage.error('关系图渲染失败: ' + (e.message || e))
  } finally {
    graphLoading.value = false
  }
}

const exportGraph = async (format) => {
  if (!graphContainer.value) return
  const svgEl = graphContainer.value.querySelector('svg')
  if (!svgEl) {
    ElMessage.warning('无图可导出')
    return
  }
  try {
    const svgData = new XMLSerializer().serializeToString(svgEl)
    const dataUrl = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svgData)
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      const scale = 2
      const vb = svgEl.viewBox && svgEl.viewBox.baseVal
      const w = (vb && vb.width) || svgEl.clientWidth || 800
      const h = (vb && vb.height) || svgEl.clientHeight || 600
      canvas.width = w * scale
      canvas.height = h * scale
      const ctx = canvas.getContext('2d')
      ctx.fillStyle = '#fff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      const mime = format === 'jpeg' ? 'image/jpeg' : 'image/png'
      const link = document.createElement('a')
      link.download = `agent-graph-${graphAgentName.value || 'agent'}.${format}`
      link.href = canvas.toDataURL(mime, 0.95)
      link.click()
      ElMessage.success(`已导出 ${format.toUpperCase()}`)
    }
    img.onerror = () => {
      ElMessage.error('导出失败：SVG 转换图片失败')
    }
    img.src = dataUrl
  } catch (e) {
    ElMessage.error('导出失败: ' + (e.message || e))
  }
}

const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除 Agent "${row.agent_name}"？`, '提示', { type: 'warning' })
    await agentApi.delete(String(row.pr_key_id))
    ElMessage.success('删除成功')
    await loadData()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error(e.response?.data?.detail || '删除失败')
    }
  }
}

const loadDispatchHistory = async () => {
  historyLoading.value = true
  try {
    const data = await agentApi.getDispatchTasks()
    dispatchHistory.value = data?.records || []
    historyVisible.value = true
  } catch (e) {
    ElMessage.error('加载调度历史失败')
  } finally {
    historyLoading.value = false
  }
}

const onSelectionChange = (rows) => {
  selectedRows.value = rows
}

/** 卡片式选择切换（替代表格 selection-change） */
const toggleSelect = (row, val) => {
  if (val) {
    if (!selectedRows.value.some(r => r.pr_key_id === row.pr_key_id)) {
      selectedRows.value.push(row)
    }
  } else {
    selectedRows.value = selectedRows.value.filter(r => r.pr_key_id !== row.pr_key_id)
  }
}

const openMultiDispatch = () => {
  multiMessage.value = ''
  multiChannels.value = {}
  multiMode.value = 'parallel'
  dagDeps.value = {}
  multiVisible.value = true
}

const sendMultiDispatch = async () => {
  // 团队调度模式：用 teamId，不要求 selectedRows
  const isTeamDispatch = !!teamDispatchId.value
  if (!multiMessage.value.trim() || multiSending.value) return
  if (!isTeamDispatch && !selectedRows.value.length) return
  multiSending.value = true
  multiChannels.value = {}
  const params = { message: multiMessage.value, mode: multiMode.value }
  if (isTeamDispatch) {
    params.teamId = teamDispatchId.value
  } else {
    params.agentIds = selectedRows.value.map(r => String(r.pr_key_id))
    if (multiMode.value === 'dag') {
      params.tasks = selectedRows.value.map((r, i) => ({
        agent_id: String(r.pr_key_id),
        dependencies: dagDeps.value[i] || [],
      }))
    }
  }
  try {
    await chatApi.multiDispatch(params, (data) => {
      // 顶层 error 事件无 task_id，需在 tid 检查前处理（否则被 if (!tid) return 丢弃）
      if (data.type === 'error') {
        ElMessage.error(data.data || '调度失败')
        return
      }
      // 人工审核 plan_review（dispatch_id 级，无 task_id，需在 tid 检查前处理）
      if (data.type === 'plan_review') {
        reviewVisible.value = true
        reviewData.value = data
        return
      }
      const tid = data.task_id
      if (!tid) return
      if (data.type === 'task_started') {
        multiChannels.value[tid] = { agent: data.agent || tid, content: '', done: false }
      }
      const ch = multiChannels.value[tid]
      if (!ch) return
      if (data.content) ch.content += data.content
      if (data.agent) ch.agent = data.agent
      if (data.done) ch.done = true
      if (data.type === 'task_completed' || data.done === true) ch.done = true
      if (data.type === 'task_failed') { ch.done = true; ch.content += ' [失败]' }
      multiChannels.value = { ...multiChannels.value }
    })
  } catch (e) {
    ElMessage.error('并行调度失败')
  } finally {
    multiSending.value = false
  }
}

onMounted(() => {
  loadData()
  loadSelections()
  // 团队调度跳转：TeamList 的"团队调度"按钮跳转 /agents?teamDispatch=xxx
  if (route.query.teamDispatch) {
    teamDispatchId.value = String(route.query.teamDispatch)
    openMultiDispatch()
  }
})
</script>

<style scoped>
/* ── Agent 卡片网格 ── */
.agent-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  margin-top: 16px;
}
/* 大屏可以显示更多列 */
@media (min-width: 1600px) {
  .agent-cards { grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); }
}
/* 小屏适配 */
@media (max-width: 768px) {
  .agent-cards { grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); }
}
.agent-card {
  background: #fff;
  border: 1px solid #E2E8F0;
  border-radius: 12px;
  padding: 14px;
  cursor: pointer;
  position: relative;
  transition: all 0.2s ease;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.agent-card:hover {
  border-color: #A5B4FC;
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.12);
  transform: translateY(-2px);
}
.agent-card-selected {
  border-color: #6366F1;
  background: rgba(99, 102, 241, 0.03);
}

/* 选择框（左上角） */
.card-checkbox {
  position: absolute; top: 10px; left: 10px;
  z-index: 2;
}

/* 详情预览（右上角 ⓘ 图标，始终可见） */
.card-info {
  position: absolute; top: 8px; right: 36px;
  z-index: 2;
}
.card-info-icon {
  font-size: 16px; color: #94A3B8; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; border-radius: 6px;
  transition: all 0.15s ease;
}
.card-info-icon:hover { background: #F1F5F9; color: #475569; }

/* hover 操作菜单（右上角） */
.card-actions {
  position: absolute; top: 8px; right: 8px;
  z-index: 2;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.agent-card:hover .card-actions { opacity: 1; }
.card-more {
  font-size: 18px; color: #94A3B8; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; border-radius: 6px;
  transition: all 0.15s ease;
}
.card-more:hover { background: #F1F5F9; color: #475569; }

/* 卡片主体：图标 + 名称 */
.card-body {
  display: flex; align-items: center; gap: 10px;
  margin: 6px 0 8px 26px;
}
.card-icon { color: #6366F1; flex-shrink: 0; }
/* AI智能体图标容器（参考插件市场：40×40 圆角 + 浅蓝背景，内 icon 22px） */
.card-agent-icon-wrap {
  width: 40px; height: 40px; border-radius: 12px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #EEF2FF, #E0E7FF);
}
.card-name {
  font-size: 14px; font-weight: 600; color: #1E293B;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  max-width: 160px;
}

/* 描述 */
.card-desc {
  font-size: 12px; color: #64748B; line-height: 1.4;
  margin: 0 0 10px 0;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden; min-height: 34px;
}

/* 标签行 */
.card-tags {
  display: flex; flex-wrap: wrap; gap: 4px;
  margin-bottom: 8px;
}

/* 状态行 */
.card-status {
  display: flex; align-items: center; justify-content: space-between;
  border-top: 1px solid #F1F5F9;
  padding-top: 8px;
}
</style>
