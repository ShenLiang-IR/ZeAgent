<template>
  <div class="page-container">
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span>出站事件订阅</span>
          <el-button type="primary" @click="openCreate">新建订阅</el-button>
        </div>
      </template>
      <el-table :data="subscriptions" v-loading="loading" border>
        <el-table-column prop="name" label="名称" width="150" />
        <el-table-column prop="event_type" label="事件类型" width="180">
          <template #default="{ row }">
            <el-tag size="small">{{ row.event_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="callback_url" label="回调 URL" show-overflow-tooltip />
        <el-table-column label="验签" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.secret ? 'success' : 'info'">{{ row.secret ? '有' : '无' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" type="success" @click="testNotify(row)">测试通知</el-button>
            <el-button size="small" type="danger" @click="doDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建订阅 -->
    <el-dialog v-model="createVisible" title="新建事件订阅" width="560px">
      <el-form label-width="100px">
        <el-form-item label="名称"><el-input v-model="form.name" placeholder="订阅名称" /></el-form-item>
        <el-form-item label="事件类型">
          <el-select v-model="form.event_type" style="width:100%;">
            <el-option label="调度完成 (dispatch_completed)" value="dispatch_completed" />
            <el-option label="调度失败 (dispatch_failed)" value="dispatch_failed" />
            <el-option label="配额超限 (quota_exceeded)" value="quota_exceeded" />
            <el-option label="Agent 错误 (agent_error)" value="agent_error" />
            <el-option label="全部事件 (all)" value="all" />
          </el-select>
        </el-form-item>
        <el-form-item label="回调 URL"><el-input v-model="form.callback_url" placeholder="https://your-system.com/webhook" /></el-form-item>
        <el-form-item label="验签密钥"><el-input v-model="form.secret" placeholder="HMAC-SHA256 密钥（可选，用于 X-Signature 验签）" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="save" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { subscriptionApi } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const subscriptions = ref([])
const loading = ref(false)
const createVisible = ref(false)
const saving = ref(false)
const form = ref({ name: '', event_type: 'dispatch_completed', callback_url: '', secret: '' })

const loadData = async () => {
  loading.value = true
  try {
    const res = await subscriptionApi.list()
    subscriptions.value = res.subscriptions || []
  } catch (e) { ElMessage.error('加载失败') }
  finally { loading.value = false }
}

const openCreate = () => {
  form.value = { name: '', event_type: 'dispatch_completed', callback_url: '', secret: '' }
  createVisible.value = true
}

const save = async () => {
  if (!form.value.name || !form.value.callback_url) { ElMessage.warning('名称和回调 URL 必填'); return }
  saving.value = true
  try {
    await subscriptionApi.create(form.value)
    ElMessage.success('创建成功')
    createVisible.value = false
    loadData()
  } catch (e) { ElMessage.error('创建失败') }
  finally { saving.value = false }
}

const testNotify = async (row) => {
  try {
    const res = await subscriptionApi.notify({
      event_type: row.event_type,
      payload: { test: true, subscription: row.name, message: '测试通知' },
    })
    ElMessage.success(`测试通知已发送（成功 ${res.success_count} 个）`)
  } catch (e) { ElMessage.error('测试失败') }
}

const doDelete = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除订阅「${row.name}」？`, '提示', { type: 'warning' })
    await subscriptionApi.delete(row.subscription_id)
    ElMessage.success('已删除')
    loadData()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

onMounted(loadData)
</script>
