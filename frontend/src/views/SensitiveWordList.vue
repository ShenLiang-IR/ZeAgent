<template>
  <div class="page-container">
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span>敏感词管理</span>
          <div>
            <el-input v-model="searchText" placeholder="搜索敏感词" size="small" style="width: 160px; margin-right: 8px;" clearable @input="onSearch" />
            <el-input v-model="newWord" placeholder="输入新敏感词" size="small" style="width: 180px; margin-right: 8px;" @keydown.enter="addWord" />
            <el-select v-model="newCategory" size="small" style="width: 90px; margin-right: 8px;">
              <el-option label="政治" value="politics" />
              <el-option label="色情" value="porn" />
              <el-option label="暴力" value="violence" />
              <el-option label="其他" value="other" />
            </el-select>
            <el-button type="primary" size="small" @click="addWord">添加</el-button>
          </div>
        </div>
      </template>
      <el-table :data="filteredWords" border size="small" v-loading="loading" empty-text="暂无敏感词" max-height="400">
        <el-table-column prop="word" label="敏感词" width="200" />
        <el-table-column label="分类" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.category === 'politics' ? 'danger' : row.category === 'porn' ? 'warning' : row.category === 'violence' ? 'danger' : 'info'">
              {{ row.category === 'politics' ? '政治' : row.category === 'porn' ? '色情' : row.category === 'violence' ? '暴力' : '其他' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled === 1" size="small" @change="v => toggleWord(row, v)" />
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="添加时间" width="180" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" type="danger" @click="deleteWord(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="margin-top: 16px; color: #909399; font-size: 13px;">
        提示：添加敏感词后，在系统配置中开启"内容安全审查"，聊天中的用户输入命中敏感词将被拦
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const words = ref([])
const loading = ref(false)
const newWord = ref('')
const newCategory = ref('other')
const searchText = ref('')

const filteredWords = computed(() => {
  if (!searchText.value) return words.value
  return words.value.filter(w => w.word.includes(searchText.value))
})

const loadWords = async () => {
  loading.value = true
  try {
    const token = localStorage.getItem('auth_token') || ''
    const res = await fetch('/api/admin/security/sensitive-words', {
      headers: { Authorization: token }
    })
    const data = await res.json()
    words.value = data?.data?.list || data?.list || []
  } catch (e) {
    console.log('loadWords failed', e)
  } finally {
    loading.value = false
  }
}

const addWord = async () => {
  if (!newWord.value.trim()) { ElMessage.warning('请输入敏感词'); return }
  const token = localStorage.getItem('auth_token') || ''
  try {
    await fetch('/api/admin/security/sensitive-words', {
      method: 'POST',
      headers: { Authorization: token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ word: newWord.value.trim(), category: newCategory.value })
    })
    newWord.value = ''
    ElMessage.success('添加成功')
    await loadWords()
  } catch (e) {
    ElMessage.error('添加失败')
  }
}

const toggleWord = async (row, enabled) => {
  const token = localStorage.getItem('auth_token') || ''
  try {
    await fetch(`/api/admin/security/sensitive-words/${row.pr_key_id}/toggle`, {
      method: 'PATCH',
      headers: { Authorization: token }
    })
    row.enabled = enabled ? 1 : 0
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

const deleteWord = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除 "${row.word}"？`, '确认', { type: 'warning' })
  } catch { return }
  const token = localStorage.getItem('auth_token') || ''
  try {
    await fetch(`/api/admin/security/sensitive-words/${row.pr_key_id}`, {
      method: 'DELETE',
      headers: { Authorization: token }
    })
    ElMessage.success('已删除')
    await loadWords()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

onMounted(loadWords)
</script>
