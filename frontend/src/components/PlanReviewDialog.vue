<template>
  <el-dialog v-model="visible" title="人工审核 - Plan Review" width="760px" :close-on-click-modal="false">
    <div v-if="data">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="Dispatch ID">{{ data.dispatch_id }}</el-descriptions-item>
        <el-descriptions-item label="Plan Mode">{{ data.plan?.mode }}</el-descriptions-item>
      </el-descriptions>
      <el-divider content-position="left">执行计划 - 选中的 Agent</el-divider>
      <div v-if="agentCards.length" class="ac-grid">
        <div v-for="c in agentCards" :key="c.task_id" class="ac-cell">
          <AgentCard :agent="c" />
          <div class="ac-task">
            <span class="ac-task-label">任务：</span>{{ c.task_description }}
            <span v-if="c.dependencies && c.dependencies.length" class="ac-dep">依赖：{{ c.dependencies.join(', ') }}</span>
          </div>
        </div>
      </div>
      <el-empty v-else description="无 plan 任务" :image-size="50" />
      <el-divider content-position="left">已完成 Task 结果</el-divider>
      <el-table :data="resultRows" border size="small" style="margin-bottom: 12px;">
        <el-table-column prop="task_id" label="Task ID" width="150" />
        <el-table-column prop="result" label="结果" show-overflow-tooltip />
      </el-table>
      <el-divider content-position="left">操作</el-divider>
      <el-radio-group v-model="action" style="margin-bottom: 12px;">
        <el-radio-button label="approve">批准</el-radio-button>
        <el-radio-button label="modify">修改</el-radio-button>
        <el-radio-button label="reject">拒绝</el-radio-button>
      </el-radio-group>
      <el-input v-if="action === 'modify'" v-model="modifiedPlanJson" type="textarea" :rows="6"
        placeholder='修改后的 plan JSON，如 {"mode":"parallel","tasks":[...]}' />
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">提交审核</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { planApi } from '../api/index.js'
import AgentCard from './AgentCard.vue'

const props = defineProps({ modelValue: Boolean, data: Object })
const emit = defineEmits(['update:modelValue'])
const visible = computed({ get: () => props.modelValue, set: v => emit('update:modelValue', v) })
const action = ref('approve')
const modifiedPlanJson = ref('')
const submitting = ref(false)
const agentCards = computed(() => props.data?.agent_cards || [])
const resultRows = computed(() => {
  const r = props.data?.results || {}
  return Object.entries(r).map(([task_id, result]) => ({ task_id, result: String(result).slice(0, 200) }))
})
watch(() => props.data, () => { action.value = 'approve'; modifiedPlanJson.value = '' })
const submit = async () => {
  if (!props.data?.dispatch_id) return
  submitting.value = true
  try {
    let modifiedPlan = null
    if (action.value === 'modify') {
      try { modifiedPlan = JSON.parse(modifiedPlanJson.value) }
      catch { ElMessage.error('plan JSON 无效'); submitting.value = false; return }
    }
    await planApi.review(props.data.dispatch_id, action.value, modifiedPlan)
    ElMessage.success(`审核已提交: ${action.value}`)
    visible.value = false
  } catch (e) { ElMessage.error('提交失败: ' + e.message) }
  finally { submitting.value = false }
}
</script>

<style scoped>
.ac-grid { display: flex; flex-direction: column; gap: 10px; margin-bottom: 8px; }
.ac-cell { border: 1px solid #E2E8F0; border-radius: 8px; padding: 8px; }
.ac-task { font-size: 13px; color: #64748B; margin-top: 6px; line-height: 1.5; }
.ac-task-label { color: #64748B; }
.ac-dep { margin-left: 8px; color: #64748B; font-size: 12px; }
</style>
