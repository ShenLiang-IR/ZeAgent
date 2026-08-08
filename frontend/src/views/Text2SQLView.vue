<template>
  <div style="padding: 20px;">
    <el-card>
      <template #header>
        <span style="font-size: 18px; font-weight: bold;">Text2SQL 自然语言查库</span>
        <el-tag type="info" size="small" style="margin-left: 10px;">MySQL</el-tag>
      </template>

      <el-form @submit.prevent="doAsk">
        <el-form-item label="问题">
          <el-input
            v-model="question"
            type="textarea"
            :rows="3"
            placeholder="用自然语言提问，如：列出所有 agent 的名称和状态"
            @keydown.enter.ctrl="doAsk"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" :disabled="!question.trim()" @click="doAsk">
            查询 (Ctrl+Enter)
          </el-button>
          <el-input-number v-model="maxRows" :min="1" :max="500" style="margin-left: 12px;" />
          <span style="margin-left: 8px; color: #999; font-size: 12px;">最大行数</span>
        </el-form-item>
      </el-form>

      <!-- 结果区 -->
      <div v-if="result" style="margin-top: 20px;">
        <el-divider content-position="left">查询结果</el-divider>

        <!-- SQL 展示 -->
        <div v-if="result.sql" style="margin-bottom: 15px;">
          <div style="font-weight: bold; margin-bottom: 6px; color: #409eff;">SQL:</div>
          <pre style="background: #F1F5F9; padding: 12px; border-radius: 4px; overflow: auto; font-size: 13px; line-height: 1.5;">{{ result.sql }}</pre>
        </div>

        <!-- 错误 -->
        <el-alert v-if="result.error" :title="result.error" type="error" :closable="false" style="margin-bottom: 15px;" />

        <!-- 数据表格 -->
        <div v-if="result.data && result.data.length > 0">
          <div style="font-weight: bold; margin-bottom: 6px; color: #409eff;">数据 ({{ result.data.length }} 行):</div>
          <el-table :data="result.data" border size="small" max-height="500" style="width: 100%;">
            <el-table-column
              v-for="col in resultColumns"
              :key="col"
              :prop="col"
              :label="col"
              show-overflow-tooltip
              :min-width="120"
            />
          </el-table>
        </div>
        <el-empty v-else-if="result.success && !result.error" description="查询成功，无数据返回" />

        <!-- 统计 -->
        <div style="margin-top: 10px; color: #999; font-size: 12px;">
          工具调用次数: {{ result.tool_calls }} | 成功: {{ result.success ? '是' : '否' }}
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'

const question = ref('')
const maxRows = ref(20)
const loading = ref(false)
const result = ref(null)

const resultColumns = computed(() => {
  if (!result.value || !result.value.data || result.value.data.length === 0) return []
  return Object.keys(result.value.data[0])
})

const doAsk = async () => {
  if (!question.value.trim()) return
  loading.value = true
  result.value = null
  try {
    const token = localStorage.getItem('auth_token') || ''
    const res = await fetch('/api/text2sql/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: token },
      body: JSON.stringify({ question: question.value, max_rows: maxRows.value })
    })
    if (!res.ok) {
      const e = await res.json()
      ElMessage.error(e.detail || '查询失败')
      return
    }
    result.value = await res.json()
    if (result.value.error) {
      ElMessage.warning('查询有错误，查看详情')
    } else if (result.value.success) {
      ElMessage.success('查询成功')
    }
  } catch (e) {
    ElMessage.error('网络错误: ' + e.message)
  } finally {
    loading.value = false
  }
}
</script>
