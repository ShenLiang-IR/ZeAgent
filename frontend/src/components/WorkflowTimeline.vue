<template>
  <div v-if="workflowSteps?.length" class="workflow-timeline">
    <div v-for="step in workflowSteps" :key="step.id" class="timeline-step">
      <span class="step-icon">
        {{ step.status === 'done' ? '✅' : step.status === 'failed' ? '❌' : step.status === 'running' ? '🔄' : '⏳' }}
      </span>
      <el-popover trigger="hover" :width="380" placement="right">
        <template #reference>
          <span class="step-name">{{ step.name }}</span>
        </template>
        <div class="step-detail">
          <div v-if="step.description"><b>描述:</b> {{ step.description }}</div>
          <div v-if="step.agent"><b>Agent:</b> {{ step.agent }}</div>
          <div v-if="step.duration != null"><b>耗时:</b> {{ step.duration }}s</div>
          <div v-if="step.toolCalls?.length">
            <b>工具调用:</b>
            <div v-for="(tc, i) in step.toolCalls" :key="i" class="tool-call">• {{ tc.name }}: {{ tc.input }}</div>
          </div>
          <div v-if="step.output"><b>输出:</b> {{ step.output }}</div>
          <div v-if="step.error" style="color: #F56C6C"><b>错误:</b> {{ step.error }}</div>
        </div>
      </el-popover>
      <span v-if="step.duration != null" class="step-duration">{{ step.duration }}s</span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  workflowSteps: { type: Array, default: null },
})
</script>

<style scoped>
.workflow-timeline { margin-bottom: 8px; padding: 6px 0; border-bottom: 1px dashed #E4E7ED; }
.timeline-step { display: flex; align-items: center; gap: 6px; padding: 2px 0; font-size: 13px; line-height: 1.8; }
.step-icon { flex-shrink: 0; width: 18px; text-align: center; }
.step-name { cursor: pointer; color: #409EFF; flex: 1; }
.step-name:hover { text-decoration: underline; }
.step-duration { flex-shrink: 0; font-size: 11px; color: #909399; }
.step-detail { font-size: 13px; line-height: 1.7; }
.tool-call { margin-left: 8px; font-size: 12px; color: #606266; word-break: break-all; }
</style>
