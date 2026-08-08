<template>
  <div class="page-container">
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span>端到端评测管理</span>
          <div>
            <el-button @click="loadResults">查看评测结果</el-button>
            <el-button type="primary" @click="openCreate">新建数据集</el-button>
          </div>
        </div>
      </template>
      <el-table :data="datasets" v-loading="loading" border>
        <el-table-column prop="name" label="名称" width="140" />
        <el-table-column prop="question" label="问题" show-overflow-tooltip />
        <el-table-column prop="expected_output" label="期望输出" show-overflow-tooltip width="200" />
        <el-table-column prop="tags" label="标签" width="120" />
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <el-button size="small" type="success" @click="openJudge(row)">Judge 测试</el-button>
            <el-button size="small" @click="openResults(row)">查看结果</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建数据集 -->
    <el-dialog v-model="createVisible" title="新建评测数据集" width="700px">
      <el-form label-width="100px">
        <el-form-item label="名称"><el-input v-model="form.name" placeholder="数据集名称" /></el-form-item>
        <el-form-item label="问题"><el-input type="textarea" v-model="form.question" :rows="3" /></el-form-item>
        <el-form-item label="期望输出"><el-input type="textarea" v-model="form.expected_output" :rows="3" placeholder="标准答案（可选）" /></el-form-item>
        <el-form-item label="评分标准"><el-input v-model="form.scoring_criteria" placeholder="如：准确性+完整性+简洁性，各占1/3" /></el-form-item>
        <el-form-item label="标签"><el-input v-model="form.tags" placeholder="逗号分隔，如 math,general" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="save" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- Judge 测试 -->
    <el-dialog v-model="judgeVisible" title="LLM-as-Judge 评分测试" width="760px">
      <el-form label-width="100px">
        <el-form-item label="问题"><el-input type="textarea" v-model="judgeForm.question" :rows="2" /></el-form-item>
        <el-form-item label="Agent 回复"><el-input type="textarea" v-model="judgeForm.response" :rows="4" placeholder="被评测的回复" /></el-form-item>
        <el-form-item label="期望输出"><el-input type="textarea" v-model="judgeForm.expected_output" :rows="2" placeholder="标准答案（可选）" /></el-form-item>
        <el-form-item label="评分标准"><el-input v-model="judgeForm.scoring_criteria" /></el-form-item>
        <el-form-item v-if="judgeResult" label="评分结果">
          <el-tag :type="judgeResult.score >= 80 ? 'success' : judgeResult.score >= 60 ? 'warning' : 'danger'" size="large">
            Score: {{ judgeResult.score }}/100
          </el-tag>
          <div style="margin-top:8px;white-space:pre-wrap;background:#f5f5f5;padding:8px;border-radius:4px;">{{ judgeResult.feedback }}</div>
          <div v-if="judgeResult.judge_model" style="color:#999;margin-top:4px;">Judge 模型: {{ judgeResult.judge_model }}</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="judgeVisible = false">关闭</el-button>
        <el-button type="primary" @click="doJudge" :loading="judging">评分</el-button>
      </template>
    </el-dialog>

    <!-- 评测结果 -->
    <el-dialog v-model="resultsVisible" title="评测结果" width="860px">
      <div style="margin-bottom:12px;">
        <el-radio-group v-model="resultsQuery.by" style="margin-right:8px;">
          <el-radio value="dataset">按数据集</el-radio>
          <el-radio value="dispatch">按 dispatch</el-radio>
        </el-radio-group>
        <el-input v-model="resultsQuery.id" :placeholder="resultsQuery.by === 'dataset' ? 'dataset_id' : 'dispatch_id'" style="width:280px;margin-right:8px;" />
        <el-button size="small" @click="loadResultsData" :loading="resultsLoading">查询</el-button>
      </div>
      <el-table :data="results" border size="small" v-loading="resultsLoading">
        <el-table-column prop="score" label="分数" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.score >= 80 ? 'success' : row.score >= 60 ? 'warning' : 'danger'">{{ row.score }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="question" label="问题" show-overflow-tooltip />
        <el-table-column prop="response" label="回复" show-overflow-tooltip />
        <el-table-column prop="judge_feedback" label="评语" show-overflow-tooltip />
        <el-table-column prop="judge_model" label="Judge模型" width="120" />
        <el-table-column prop="create_time" label="时间" width="150" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { evalApi } from '../api'
import { ElMessage } from 'element-plus'

const datasets = ref([])
const loading = ref(false)
const createVisible = ref(false)
const saving = ref(false)
const form = ref({ name: '', question: '', expected_output: '', scoring_criteria: '', tags: '' })
const judgeVisible = ref(false)
const judging = ref(false)
const judgeForm = ref({ question: '', response: '', expected_output: '', scoring_criteria: '' })
const judgeResult = ref(null)
const resultsVisible = ref(false)
const results = ref([])
const resultsLoading = ref(false)
const resultsQuery = ref({ by: 'dataset', id: '' })

const loadData = async () => {
  loading.value = true
  try {
    const res = await evalApi.listDatasets()
    datasets.value = res.datasets || []
  } catch (e) {
    ElMessage.error('加载数据集失败')
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  form.value = { name: '', question: '', expected_output: '', scoring_criteria: '', tags: '' }
  createVisible.value = true
}

const save = async () => {
  if (!form.value.name || !form.value.question) { ElMessage.warning('名称和问题必填'); return }
  saving.value = true
  try {
    await evalApi.createDataset({
      name: form.value.name,
      question: form.value.question,
      expected_output: form.value.expected_output,
      scoring_criteria: form.value.scoring_criteria,
      tags: form.value.tags,
    })
    ElMessage.success('创建成功')
    createVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error('创建失败')
  } finally {
    saving.value = false
  }
}

const openJudge = (row) => {
  judgeForm.value = {
    question: row.question || '',
    response: '',
    expected_output: row.expected_output || '',
    scoring_criteria: row.scoring_criteria || '',
  }
  judgeResult.value = null
  judgeVisible.value = true
}

const doJudge = async () => {
  if (!judgeForm.value.response) { ElMessage.warning('请输入 Agent 回复'); return }
  judging.value = true
  try {
    const res = await evalApi.judge({
      question: judgeForm.value.question,
      response: judgeForm.value.response,
      expected_output: judgeForm.value.expected_output,
      scoring_criteria: judgeForm.value.scoring_criteria,
    })
    judgeResult.value = res
  } catch (e) {
    ElMessage.error('评分失败')
  } finally {
    judging.value = false
  }
}

const openResults = (row) => {
  resultsQuery.value = { by: 'dataset', id: row.dataset_id || '' }
  results.value = []
  resultsVisible.value = true
  if (resultsQuery.value.id) loadResultsData()
}

const loadResults = () => {
  resultsQuery.value = { by: 'dispatch', id: '' }
  results.value = []
  resultsVisible.value = true
}

const loadResultsData = async () => {
  if (!resultsQuery.value.id) { ElMessage.warning('请输入查询 ID'); return }
  resultsLoading.value = true
  try {
    const params = resultsQuery.value.by === 'dataset'
      ? { dataset_id: resultsQuery.value.id }
      : { dispatch_id: resultsQuery.value.id }
    const res = await evalApi.listResults(params)
    results.value = res.results || []
  } catch (e) {
    ElMessage.error('查询失败')
    results.value = []
  } finally {
    resultsLoading.value = false
  }
}

onMounted(loadData)
</script>
