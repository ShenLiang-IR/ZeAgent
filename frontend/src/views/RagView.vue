<template>
  <div style="padding: 20px;">
    <el-card>
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <span style="font-size: 18px; font-weight: bold;">RAG 知识检索</span>
          <el-tag type="info" size="small">{{ config.vector_store_backend || 'chromadb' }}</el-tag>
        </div>
      </template>

      <el-tabs v-model="activeTab">
        <!-- Tab 1: 文档解析（MinerU）-->
        <el-tab-pane label="文档解析" name="parse">
          <el-form label-width="120px" style="max-width: 700px; margin: 20px auto;">
            <el-form-item label="选择文件">
              <el-upload
                ref="parseUploadRef"
                :auto-upload="false"
                :limit="1"
                :on-change="handleParseFileChange"
                accept=".pdf,.docx,.jpeg,.jpg"
              >
                <template #trigger>
                  <el-button type="primary">选择文件</el-button>
                </template>
                <template #tip>
                  <div style="color: #999; font-size: 12px;">支持 PDF/DOCX/JPEG/JPG，MinerU 解析生成 JSON+MD</div>
                </template>
              </el-upload>
            </el-form-item>
            <el-form-item>
              <el-button type="success" :loading="parsing" :disabled="!parseFile" @click="doParse">解析</el-button>
              <el-button @click="resetParse">重置</el-button>
            </el-form-item>
          </el-form>

          <!-- 解析结果 -->
          <div v-if="parseResult" style="max-width: 900px; margin: 0 auto;">
            <el-divider content-position="left">解析结果（{{ parseResult.filename }}）</el-divider>
            <div style="margin-bottom: 12px;">
              <el-radio-group v-model="parseFormat">
                <el-radio-button label="md">Markdown</el-radio-button>
                <el-radio-button label="json">JSON</el-radio-button>
              </el-radio-group>
              <span style="margin-left: 12px; color: #999; font-size: 12px;">
                MD: {{ parseResult.md_path }} | JSON: {{ parseResult.json_path }}
              </span>
            </div>
            <div style="white-space: pre-wrap; line-height: 1.6; background: #F1F5F9; padding: 16px; border-radius: 4px; max-height: 500px; overflow: auto;">
              {{ parseFormat === 'md' ? parseResult.md_content : parseResultJson }}
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 2: 知识库管理 -->
        <el-tab-pane label="知识库管理" name="kb">
          <div style="margin: 20px 0;">
            <el-button type="primary" @click="openKbDialog()">新增知识库</el-button>
            <el-button @click="loadKbList">刷新</el-button>
          </div>
          <el-table :data="kbList" border size="small">
            <el-table-column prop="kb_id" label="知识库ID" width="120" />
            <el-table-column prop="name" label="名称" width="120" />
            <el-table-column prop="description" label="描述" show-overflow-tooltip />
            <el-table-column prop="persist_directory" label="存储路径" width="160" show-overflow-tooltip />
            <el-table-column label="Embedding" width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ row.embedding_provider }} / {{ row.embedding_model }}</template>
            </el-table-column>
            <el-table-column prop="embedding_base_url" label="Embedding URL" width="160" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="70" />
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="openKbDialog(row)">编辑</el-button>
                <el-button size="small" type="primary" @click="openKbVersion(row)">版本</el-button>
                <el-button size="small" type="danger" @click="doDeleteKb(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <!-- 知识库版本管理 -->
          <el-dialog v-model="kbVersionVisible" :title="`版本管理 - ${kbVersionRow?.kb_id || ''}`" width="880px" top="5vh">
            <div style="margin-bottom:16px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              <el-input v-model="kbVerForm.version_no" placeholder="版本号如 1.0.1" style="width:150px;" />
              <el-input v-model="kbVerForm.version_description" placeholder="版本说明" style="width:260px;" />
              <el-button type="primary" @click="createKbVersion" :loading="kbVerSaving">创建快照</el-button>
              <el-button @click="openKbDiff">配置 Diff</el-button>
              <el-button @click="rebuildKbIndex" :loading="rebuilding">增量重建索引</el-button>
            </div>
            <el-table :data="kbVersions" border size="small" v-loading="kbVerLoading">
              <el-table-column prop="version_no" label="版本" width="100" />
              <el-table-column prop="status" label="状态" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.status === 'published' ? 'success' : row.status === 'archived' ? 'info' : 'warning'">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="version_description" label="说明" show-overflow-tooltip />
              <el-table-column prop="create_time" label="创建时间" width="150" />
              <el-table-column label="操作" width="180">
                <template #default="{ row }">
                  <el-button size="small" type="success" v-if="row.status !== 'published'" @click="publishKbVersion(row)">发布</el-button>
                  <el-button size="small" v-if="row.status !== 'draft'" @click="rollbackKbVersion(row)">回滚</el-button>
                </template>
              </el-table-column>
            </el-table>
            <!-- diff 子对话框 -->
            <el-dialog v-model="kbDiffVisible" title="知识库配置 Diff" width="720px" append-to-body>
              <div style="margin-bottom:12px;display:flex;gap:8px;align-items:center;">
                <span>版本1</span>
                <el-select v-model="kbDiffForm.v1" placeholder="选版本" style="width:130px;">
                  <el-option v-for="v in kbVersions" :key="v.version_no" :label="v.version_no" :value="v.version_no" />
                </el-select>
                <span>版本2</span>
                <el-select v-model="kbDiffForm.v2" placeholder="选版本" style="width:130px;">
                  <el-option v-for="v in kbVersions" :key="v.version_no" :label="v.version_no" :value="v.version_no" />
                </el-select>
                <el-button size="small" @click="loadKbDiff" :loading="kbDiffLoading">对比</el-button>
              </div>
              <el-table :data="kbDiffResult" border size="small">
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

          <!-- 新增/编辑 dialog -->
          <el-dialog v-model="kbDialogVisible" :title="kbDialogTitle" width="600px">
            <el-form :model="kbForm" label-width="120px">
              <el-form-item label="知识库ID">
                <el-input v-model="kbForm.kb_id" :disabled="kbEditing" placeholder="唯一标识，创建后不可改" />
              </el-form-item>
              <el-form-item label="名称"><el-input v-model="kbForm.name" /></el-form-item>
              <el-form-item label="描述"><el-input v-model="kbForm.description" type="textarea" :rows="2" /></el-form-item>
              <el-form-item label="存储路径"><el-input v-model="kbForm.persist_directory" placeholder="data/chroma_rag" /></el-form-item>
              <el-form-item label="Embedding类型">
                <el-select v-model="kbForm.embedding_provider" style="width: 200px;">
                  <el-option label="本地模型(local)" value="local" />
                  <el-option label="Ollama" value="ollama" />
                  <el-option label="OpenAI" value="openai" />
                  <el-option label="HuggingFace" value="huggingface" />
                </el-select>
              </el-form-item>
              <el-form-item label="Embedding模型"><el-input v-model="kbForm.embedding_model" placeholder="local 时为目录路径，如 ./bge-small-zh-v1___5" /></el-form-item>
              <el-form-item label="Embedding URL"><el-input v-model="kbForm.embedding_base_url" placeholder="local 无需填写；ollama/openai 时填" /></el-form-item>
              <el-form-item label="分块大小"><el-input-number v-model="kbForm.chunk_size" :min="100" :max="5000" /></el-form-item>
              <el-form-item label="分块重叠"><el-input-number v-model="kbForm.chunk_overlap" :min="0" :max="1000" /></el-form-item>
            </el-form>
            <template #footer>
              <el-button @click="kbDialogVisible = false">取消</el-button>
              <el-button type="primary" :loading="kbSaving" @click="doSaveKb">保存</el-button>
            </template>
          </el-dialog>
        </el-tab-pane>

        <!-- Tab 2: 文档向量化 -->
        <el-tab-pane label="文档向量化" name="ingest">
          <el-form label-width="120px" style="max-width: 600px; margin: 20px auto;">
            <el-form-item label="知识库">
              <el-select v-model="ingestKbId" placeholder="选择知识库" filterable style="width: 100%;">
                <el-option v-for="kb in kbList" :key="kb.kb_id" :label="kb.name" :value="kb.kb_id" />
              </el-select>
            </el-form-item>
            <el-form-item label="选择文件">
              <el-upload
                ref="uploadRef"
                :auto-upload="false"
                :limit="1"
                :on-change="handleFileChange"
                :on-exceed="handleExceed"
                accept=".txt,.md,.pdf"
              >
                <template #trigger>
                  <el-button type="primary">选择文件</el-button>
                </template>
                <template #tip>
                  <div style="color: #999; font-size: 12px;">支持 TXT/MD/PDF 格式</div>
                </template>
              </el-upload>
            </el-form-item>
            <el-form-item>
              <el-button type="success" :loading="ingesting" :disabled="!selectedFile" @click="doIngest">
                上传入库
              </el-button>
              <el-button @click="resetIngest">重置</el-button>
            </el-form-item>
          </el-form>

          <!-- 入库结果 -->
          <el-card v-if="ingestResult" style="margin: 20px auto; max-width: 600px;">
            <template #header>
              <span>入库结果</span>
            </template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="文件名">{{ ingestResult.filename }}</el-descriptions-item>
              <el-descriptions-item label="知识库">{{ ingestResult.kb_id }}</el-descriptions-item>
              <el-descriptions-item label="Chunk 数">
                <el-tag type="success">{{ ingestResult.chunks }}</el-tag>
              </el-descriptions-item>
            </el-descriptions>
          </el-card>

          <!-- 入库历史 -->
          <el-card v-if="ingestHistory.length" style="margin: 20px auto; max-width: 600px;">
            <template #header><span>入库历史</span></template>
            <el-table :data="ingestHistory" border size="small">
              <el-table-column prop="filename" label="文件名" />
              <el-table-column prop="kb_id" label="知识库" width="120" />
              <el-table-column prop="chunks" label="Chunks" width="80" />
            </el-table>
          </el-card>
        </el-tab-pane>

        <!-- Tab 3: 知识检索 -->
        <el-tab-pane label="知识检索" name="retrieve">
          <el-form label-width="120px" style="max-width: 700px; margin: 20px auto;">
            <el-form-item label="知识库">
              <el-select v-model="retrieveKbId" placeholder="选择知识库" filterable style="width: 100%;">
                <el-option v-for="kb in kbList" :key="kb.kb_id" :label="kb.name" :value="kb.kb_id" />
              </el-select>
            </el-form-item>
            <el-form-item label="查询内容">
              <el-input v-model="query" type="textarea" :rows="3" placeholder="输入查询文本" />
            </el-form-item>
            <el-form-item label="返回数量 (K)">
              <el-input-number v-model="topK" :min="1" :max="20" />
            </el-form-item>
            <el-form-item label="检索策略">
              <el-select v-model="strategy" style="width: 200px;">
                <el-option label="混合检索" value="hybrid" />
                <el-option label="语义检索" value="semantic" />
                <el-option label="关键词检索" value="keyword" />
                <el-option label="元数据过滤" value="metadata" />
                <el-option label="自适应检索" value="adaptive" />
              </el-select>
            </el-form-item>
            <el-form-item label="语义占比" v-if="strategy === 'hybrid'">
              <el-slider v-model="semanticRatio" :min="0" :max="1" :step="0.1" show-input style="max-width: 400px;" />
              <span style="color: #999; font-size: 12px; margin-left: 8px;">0=纯关键词，1=纯语义</span>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="retrieving" :disabled="!query.trim()" @click="doRetrieve">
                检索
              </el-button>
              <el-button @click="resetRetrieve">清空</el-button>
            </el-form-item>
          </el-form>

          <!-- 检索结果（表格展示，content 前 200 字 + 点击查看全文）-->
          <div v-if="retrieveResult" style="max-width: 1100px; margin: 0 auto;">
            <el-divider content-position="left">
              检索结果（{{ retrieveResult.total_chunks }} chunks，{{ retrieveResult.latency_ms.toFixed(1) }}ms）
            </el-divider>
            <el-empty v-if="retrieveResult.total_chunks === 0" description="无检索结果" />
            <el-table v-else :data="retrieveResult.chunks" border size="small" max-height="600">
              <el-table-column type="index" label="#" width="50" align="center" />
              <el-table-column prop="doc_name" label="文档名" width="160" show-overflow-tooltip />
              <el-table-column prop="node_title" label="节点" width="120" show-overflow-tooltip />
              <el-table-column label="引用位置" width="200" show-overflow-tooltip>
                <template #default="{ row }">{{ formatCitation(row) }}</template>
              </el-table-column>
              <el-table-column label="内容（点击查看全文）">
                <template #default="{ row }">
                  <el-popover trigger="click" placement="left" :width="600">
                    <template #reference>
                      <span style="cursor: pointer; color: #409eff;">{{ row.content.slice(0, 200) }}{{ row.content.length > 200 ? '...' : '' }}</span>
                    </template>
                    <div style="max-height: 400px; overflow: auto; white-space: pre-wrap; line-height: 1.6;">
                      {{ row.content }}
                    </div>
                  </el-popover>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ragApi, kbVersionApi } from '../api/index.js'
import { formatCitation } from '../utils/citation.js'

const activeTab = ref('kb')

// ===== 知识库版本管理 =====
const kbVersionVisible = ref(false)
const kbVersionRow = ref(null)
const kbVersions = ref([])
const kbVerLoading = ref(false)
const kbVerSaving = ref(false)
const kbVerForm = ref({ version_no: '', version_description: '' })
const kbDiffVisible = ref(false)
const kbDiffForm = ref({ v1: '', v2: '' })
const kbDiffResult = ref([])
const kbDiffLoading = ref(false)
const rebuilding = ref(false)

const openKbVersion = async (row) => {
  kbVersionRow.value = row
  kbVersionVisible.value = true
  kbVerForm.value = { version_no: '', version_description: '' }
  await loadKbVersions(row)
}

const loadKbVersions = async (row) => {
  const kb = row || kbVersionRow.value
  if (!kb) return
  kbVerLoading.value = true
  try {
    const res = await kbVersionApi.list(kb.kb_id)
    kbVersions.value = res.versions || []
  } catch (e) {
    ElMessage.error('加载版本失败')
    kbVersions.value = []
  } finally {
    kbVerLoading.value = false
  }
}

const createKbVersion = async () => {
  if (!kbVerForm.value.version_no) { ElMessage.warning('请输入版本号'); return }
  kbVerSaving.value = true
  try {
    await kbVersionApi.create(kbVersionRow.value.kb_id, kbVerForm.value)
    ElMessage.success('快照已创建（draft）')
    kbVerForm.value = { version_no: '', version_description: '' }
    await loadKbVersions()
  } catch (e) {
    ElMessage.error('创建失败')
  } finally {
    kbVerSaving.value = false
  }
}

const publishKbVersion = async (row) => {
  try {
    await ElMessageBox.confirm(`发布版本 ${row.version_no}？（旧 published 自动归档）`, '确认', { type: 'warning' })
    await kbVersionApi.publish(kbVersionRow.value.kb_id, row.version_no)
    ElMessage.success('已发布')
    await loadKbVersions()
  } catch (e) { /* 取消 */ }
}

const rollbackKbVersion = async (row) => {
  try {
    await ElMessageBox.confirm(`回滚到版本 ${row.version_no}？（知识库配置恢复为该快照）`, '确认', { type: 'warning' })
    await kbVersionApi.rollback(kbVersionRow.value.kb_id, row.version_no)
    ElMessage.success('已回滚')
    await loadKbVersions()
  } catch (e) { /* 取消 */ }
}

const openKbDiff = () => {
  kbDiffForm.value = { v1: '', v2: '' }
  kbDiffResult.value = []
  kbDiffVisible.value = true
}

const loadKbDiff = async () => {
  if (!kbDiffForm.value.v1 || !kbDiffForm.value.v2) { ElMessage.warning('请选两个版本'); return }
  if (kbDiffForm.value.v1 === kbDiffForm.value.v2) { ElMessage.warning('请选不同版本'); return }
  kbDiffLoading.value = true
  try {
    const res = await kbVersionApi.diff(kbVersionRow.value.kb_id, kbDiffForm.value.v1, kbDiffForm.value.v2)
    kbDiffResult.value = Object.entries(res || {})
  } catch (e) {
    ElMessage.error('对比失败')
    kbDiffResult.value = []
  } finally {
    kbDiffLoading.value = false
  }
}

const rebuildKbIndex = async () => {
  try {
    const docDir = await ElMessageBox.prompt('输入文档目录路径（重建索引会重新 ingest 该目录所有文档）', '增量重建索引', { inputPlaceholder: '/path/to/docs' })
    if (!docDir.value) return
    rebuilding.value = true
    const res = await kbVersionApi.rebuildIndex(kbVersionRow.value.kb_id, { doc_dir: docDir.value })
    if (res.success) {
      ElMessage.success(`重建完成：${res.ingested_count}/${res.total} 文档已索引`)
    } else {
      ElMessage.warning(res.error || '重建失败')
    }
  } catch (e) { /* 取消 */ }
  finally { rebuilding.value = false }
}

// ===== 文档解析 Tab（MinerU）=====
const parsing = ref(false)
const parseFile = ref(null)
const parseResult = ref(null)
const parseFormat = ref('md')
const parseUploadRef = ref()

const parseResultJson = computed(() => {
  if (!parseResult.value?.json_content) return ''
  try {
    return JSON.stringify(JSON.parse(parseResult.value.json_content), null, 2)
  } catch {
    return parseResult.value.json_content
  }
})

const handleParseFileChange = (file) => {
  parseFile.value = file
}

const doParse = async () => {
  if (!parseFile.value) return
  parsing.value = true
  parseResult.value = null
  try {
    const formData = new FormData()
    formData.append('file', parseFile.value.raw)
    // 异步：立即返回 task_id，轮询 status（MinerU 解析耗时长）
    const start = await ragApi.parse(formData)
    let status = start
    while (status.status === 'processing') {
      await new Promise(r => setTimeout(r, 3000))
      status = await ragApi.parseStatus(start.task_id)
    }
    if (status.status === 'done') {
      parseResult.value = {
        filename: status.filename,
        md_path: status.md_path,
        json_path: status.json_path,
        md_content: status.md_content || '',
        json_content: status.json_content || '',
      }
      ElMessage.success('解析完成')
    } else {
      ElMessage.error('解析失败: ' + (status.error || '未知错误'))
    }
  } catch (e) {
    ElMessage.error('解析失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    parsing.value = false
  }
}

const resetParse = () => {
  parseFile.value = null
  parseResult.value = null
  parseUploadRef.value?.clearFiles()
}

// ===== 向量化 Tab =====
const ingestKbId = ref('default')
const selectedFile = ref(null)
const ingesting = ref(false)
const ingestResult = ref(null)
const ingestHistory = ref([])
const uploadRef = ref()

const handleFileChange = (file) => {
  selectedFile.value = file
}

const handleExceed = () => {
  ElMessage.warning('只能上传 1 个文件')
}

const doIngest = async () => {
  if (!selectedFile.value) return
  ingesting.value = true
  ingestResult.value = null
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value.raw)
    formData.append('kb_id', ingestKbId.value || 'default')
    // 异步：立即返回 task_id，轮询 status 直到完成（大文档 embedding 耗时长）
    const start = await ragApi.ingest(formData)
    let status = start
    while (status.status === 'processing') {
      await new Promise(r => setTimeout(r, 2000))
      status = await ragApi.ingestStatus(start.task_id)
    }
    if (status.status === 'done') {
      ingestResult.value = {
        filename: status.filename,
        kb_id: status.kb_id,
        chunks: status.chunks,
      }
      ingestHistory.value.unshift(ingestResult.value)
      ElMessage.success(`入库成功：${status.chunks} chunks`)
    } else {
      ElMessage.error('入库失败: ' + (status.error || '未知错误'))
    }
  } catch (e) {
    ElMessage.error('入库失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    ingesting.value = false
  }
}

const resetIngest = () => {
  selectedFile.value = null
  ingestResult.value = null
  uploadRef.value?.clearFiles()
}

// ===== 检索 Tab =====
const retrieveKbId = ref('default')
const query = ref('')
const topK = ref(5)
const strategy = ref('hybrid')
const semanticRatio = ref(0.7)
const retrieving = ref(false)
const retrieveResult = ref(null)

const doRetrieve = async () => {
  if (!query.value.trim()) return
  retrieving.value = true
  try {
    const res = await ragApi.retrieve({
      query: query.value,
      kb_id: retrieveKbId.value || 'default',
      top_k: topK.value,
      strategy: strategy.value,
      ratio: strategy.value === 'hybrid' ? semanticRatio.value : null,
    })
    retrieveResult.value = res
    ElMessage.success(`检索到 ${res.total_chunks} 个结果`)
  } catch (e) {
    ElMessage.error('检索失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    retrieving.value = false
  }
}

const resetRetrieve = () => {
  query.value = ''
  retrieveResult.value = null
}

// ===== 知识库管理 =====
const kbList = ref([])
const kbDialogVisible = ref(false)
const kbDialogTitle = ref('')
const kbEditing = ref(false)
const kbSaving = ref(false)
const defaultKbForm = () => ({
  kb_id: '', name: '', description: '', persist_directory: 'data/chroma_rag',
  embedding_provider: 'local', embedding_model: '', embedding_base_url: '',
  chunk_size: 500, chunk_overlap: 100,
})
const kbForm = ref(defaultKbForm())

const loadKbList = async () => {
  try {
    const res = await ragApi.kbList()
    kbList.value = res.list || []
  } catch (e) {
    ElMessage.error('加载知识库失败: ' + e.message)
  }
}

const openKbDialog = (row = null) => {
  kbEditing.value = !!row
  kbDialogTitle.value = row ? '编辑知识库' : '新增知识库'
  kbForm.value = row ? { ...row } : defaultKbForm()
  kbDialogVisible.value = true
}

const doSaveKb = async () => {
  if (!kbForm.value.kb_id || !kbForm.value.name) {
    ElMessage.warning('知识库ID和名称必填')
    return
  }
  kbSaving.value = true
  try {
    if (kbEditing.value) {
      await ragApi.kbUpdate(kbForm.value.kb_id, kbForm.value)
      ElMessage.success('更新成功')
    } else {
      await ragApi.kbCreate(kbForm.value)
      ElMessage.success('创建成功')
    }
    kbDialogVisible.value = false
    loadKbList()
  } catch (e) {
    ElMessage.error('保存失败: ' + e.message)
  } finally {
    kbSaving.value = false
  }
}

const doDeleteKb = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除知识库「${row.name}」？`, '提示', { type: 'warning' })
    await ragApi.kbDelete(row.kb_id)
    ElMessage.success('删除成功')
    loadKbList()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.message || e))
  }
}

// ===== Config =====
const config = ref({})
const loadConfig = async () => {
  try {
    config.value = await ragApi.getConfig()
  } catch (e) {
    // 降级
  }
}

onMounted(() => {
  loadConfig()
  loadKbList()
})
</script>
