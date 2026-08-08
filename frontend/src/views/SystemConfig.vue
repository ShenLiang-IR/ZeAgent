<template>
  <div class="page-container">
    <el-card v-loading="loading">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span>系统配置</span>
          <el-button type="primary" @click="save" :loading="saving">保存配置</el-button>
        </div>
      </template>
      <el-tabs v-model="activeTab">
        <el-tab-pane label="LLM 配置" name="llm">
          <div style="margin-bottom: 12px; display: flex; align-items: center; gap: 12px;">
            <el-button type="primary" size="small" @click="openModelForm()">新增模型</el-button>
            <el-select v-model="modelTypeFilter" placeholder="全部类型" clearable size="small" style="width: 120px;" @change="loadModelList">
              <el-option label="LLM" value="LLM" /><el-option label="Embedding" value="Embedding" /><el-option label="Rerank" value="Rerank" />
            </el-select>
          </div>
          <el-table :data="modelList" border size="small">
            <el-table-column prop="display_name" label="显示名称" width="140" />
            <el-table-column prop="model_name" label="模型名称" width="140" />
            <el-table-column prop="provider" label="Provider" width="100" />
            <el-table-column prop="model_type" label="类型" width="90" />
            <el-table-column prop="api_endpoint_url" label="API URL" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="70" />
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openModelForm(row)">编辑</el-button>
                <el-button size="small" type="danger" @click="doDeleteModel(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <!-- 新增/编辑模型弹窗 -->
          <el-dialog v-model="modelFormVisible" :title="modelFormTitle" width="600px" append-to-body>
            <el-form :model="modelForm" label-width="120px">
              <el-form-item label="模型名称"><el-input v-model="modelForm.model_name" placeholder="如 qwen-turbo" /></el-form-item>
              <el-form-item label="Provider"><el-select v-model="modelForm.provider" style="width: 200px;"><el-option label="OpenAI" value="openai" /><el-option label="Ollama" value="ollama" /><el-option label="HuggingFace" value="huggingface" /><el-option label="本地(local)" value="local" /></el-select></el-form-item>
              <el-form-item label="模型类型"><el-select v-model="modelForm.model_type" style="width: 200px;"><el-option label="LLM" value="LLM" /><el-option label="Embedding" value="Embedding" /><el-option label="Rerank" value="Rerank" /></el-select></el-form-item>
              <el-form-item label="显示名称"><el-input v-model="modelForm.display_name" placeholder="如 通义千问Turbo" /></el-form-item>
              <el-form-item label="API Key"><el-input v-model="modelForm.api_key" placeholder="Ollama/local 可不填" /></el-form-item>
              <el-form-item label="API Endpoint"><el-input v-model="modelForm.api_endpoint_url" placeholder="如 https://api.openai.com/v1" /></el-form-item>
            </el-form>
            <template #footer><el-button @click="modelFormVisible = false">取消</el-button><el-button type="primary" :loading="modelSaving" @click="doSaveModel">保存</el-button></template>
          </el-dialog>
        </el-tab-pane>
        <el-tab-pane label="Agent 配置" name="agent">
          <el-form label-width="160px" v-if="config?.agent">
            <el-form-item label="后端引擎">
              <el-select v-model="config.agent.backend" placeholder="选择后端引擎" style="width: 240px">
                <el-option label="langgraph (ReAct)" value="langgraph" />
                <el-option label="deepagents (深度思考)" value="deepagents" />
              </el-select>
              <span style="color: #999; font-size: 12px; margin-left: 8px;">单 agent 执行风格；多 agent 自主规划用下方"自动规划"开关</span>
            </el-form-item>
            <el-form-item label="自动规划">
              <el-switch v-model="config.agent.auto_plan" />
              <span style="color: #999; font-size: 12px; margin-left: 8px;">开启后走 LLM 自主规划：LLM 据请求+可用 agent 能力卡自动选 agent + 生成执行计划编排（auto_plan=true，与后端引擎正交）</span>
            </el-form-item>
            <el-form-item label="递归限制"><el-input-number v-model="config.agent.recursion_limit" :step="5" /></el-form-item>
            <el-form-item label="执行类型"><el-input v-model="config.agent.execution.type" /></el-form-item>
            <el-form-item label="最大并行任务"><el-input-number v-model="config.agent.execution.parallel_tasks.max_concurrency" :step="1" /></el-form-item>
            <el-form-item label="任务超时(秒)"><el-input-number v-model="config.agent.execution.timeout.task_timeout" :step="10" /></el-form-item>
            <el-form-item label="最大重试"><el-input-number v-model="config.agent.execution.retry.max_attempts" :step="1" /></el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="Checkpoint" name="checkpoint">
          <el-form label-width="160px" v-if="config?.checkpoint">
            <el-form-item label="后端"><el-input v-model="config.checkpoint.backend" /></el-form-item>
            <el-form-item label="MySQL 持久化"><el-switch v-model="config.checkpoint.mysql_enabled" /></el-form-item>
            <template v-if="config.checkpoint.mysql">
              <el-form-item label="MySQL 主机"><el-input v-model="config.checkpoint.mysql.host" /></el-form-item>
              <el-form-item label="MySQL 端口"><el-input-number v-model="config.checkpoint.mysql.port" /></el-form-item>
              <el-form-item label="MySQL 用户"><el-input v-model="config.checkpoint.mysql.user" /></el-form-item>
              <el-form-item label="MySQL 密码"><el-input v-model="config.checkpoint.mysql.password" /></el-form-item>
              <el-form-item label="MySQL 数据库"><el-input v-model="config.checkpoint.mysql.database" /></el-form-item>
            </template>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="沙箱" name="sandbox">
          <el-form label-width="160px" v-if="config?.sandbox">
            <el-form-item label="启用沙箱"><el-switch v-model="config.sandbox.enabled" /></el-form-item>
            <el-form-item label="基础目录"><el-input v-model="config.sandbox.base_dir" /></el-form-item>
            <el-form-item label="允许 Bash"><el-switch v-model="config.sandbox.allow_bash" /></el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="Memory" name="memory">
          <el-form label-width="160px" v-if="config?.memory">
            <el-form-item label="启用 Memory"><el-switch v-model="config.memory.enabled" /></el-form-item>
            <el-form-item label="立即记忆大小"><el-input-number v-model="config.memory.immediate_size" /></el-form-item>
            <el-form-item label="短期记忆大小"><el-input-number v-model="config.memory.short_term_size" /></el-form-item>
            <el-form-item label="短期记忆TTL(小时)"><el-input-number v-model="config.memory.short_term_ttl_hours" /></el-form-item>
            <el-form-item label="长期记忆大小"><el-input-number v-model="config.memory.long_term_size" /></el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="配额/评测" name="quota">
          <el-form label-width="200px" v-if="config?.quota">
            <el-form-item label="配额降级备用模型">
              <el-select v-model="config.quota.fallback_model_id" placeholder="degrade 模式超限时切该模型（空=仅记日志）" filterable clearable style="width: 100%;">
                <el-option v-for="m in llmModels" :key="m.id" :label="m.display_name || m.model_name" :value="m.id" />
              </el-select>
              <div class="form-tip">配额 degrade 模式超限时，自动切换到此备用模型（tb_model_config 的 id）</div>
            </el-form-item>
          </el-form>
          <el-form label-width="200px" v-if="config?.eval">
            <el-form-item label="评测 Judge 模型">
              <el-select v-model="config.eval.judge_model_id" placeholder="LLM-as-Judge 评分模型（空=用默认 LLM）" filterable clearable style="width: 100%;">
                <el-option v-for="m in llmModels" :key="m.id" :label="m.display_name || m.model_name" :value="m.id" />
              </el-select>
              <div class="form-tip">端到端评测 LLM-as-Judge 用的模型（空=项目默认 LLM）</div>
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="原始 JSON" name="raw">
          <el-input type="textarea" :model-value="JSON.stringify(config, null, 2)" :rows="25" readonly />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { systemApi, modelApi } from '../api/index.js'
import { ElMessage, ElMessageBox } from 'element-plus'

const config = ref(null)
const loading = ref(false)
const saving = ref(false)
const activeTab = ref('llm')
const llmModels = ref([])

// 模型管理（从 MainLayout 合并）
const modelList = ref([])
const modelTypeFilter = ref('')
const modelFormVisible = ref(false)
const modelFormTitle = ref('')
const modelSaving = ref(false)
const defaultModelForm = () => ({ id: '', model_name: '', provider: 'openai', model_type: 'LLM', display_name: '', api_key: '', api_endpoint_url: '' })
const modelForm = ref(defaultModelForm())
const loadModelList = async () => {
  try { const res = await modelApi.list(modelTypeFilter.value || null); modelList.value = res.list || [] } catch (e) { ElMessage.error('加载模型列表失败') }
}
const openModelForm = (row = null) => { modelFormTitle.value = row ? '编辑模型' : '新增模型'; modelForm.value = row ? { ...row } : defaultModelForm(); modelFormVisible.value = true }
const doSaveModel = async () => {
  if (!modelForm.value.model_name) { ElMessage.warning('模型名称必填'); return }
  modelSaving.value = true
  try {
    if (modelForm.value.id) { await modelApi.update(modelForm.value.id, modelForm.value); ElMessage.success('更新成功') }
    else { await modelApi.create(modelForm.value); ElMessage.success('创建成功') }
    modelFormVisible.value = false; loadModelList()
  } catch (e) { ElMessage.error('保存失败') } finally { modelSaving.value = false }
}
const doDeleteModel = async (row) => {
  try { await ElMessageBox.confirm(`确认删除「${row.display_name || row.model_name}」？`, '提示', { type: 'warning' }); await modelApi.delete(row.id); ElMessage.success('删除成功'); loadModelList() } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

const loadLlmModels = async () => {
  try {
    const res = await modelApi.list('LLM')
    llmModels.value = res.list || []
  } catch (e) { /* 降级 */ }
}

const loadData = async () => {
  loading.value = true
  try {
    config.value = await systemApi.getConfig()
  } catch (e) {
    ElMessage.warning('加载失败，请确保后端服务已启动')
  } finally {
    loading.value = false
  }
}

const save = async () => {
  saving.value = true
  try {
    await systemApi.updateConfig(config.value)
    ElMessage.success('配置已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadData()
  loadLlmModels()
  loadModelList()
})
</script>
