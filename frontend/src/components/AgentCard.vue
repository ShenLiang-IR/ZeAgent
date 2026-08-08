<template>
  <el-card class="agent-card" shadow="hover" body-style="padding: 12px 14px">
    <div class="ac-header">
      <span class="ac-name">{{ agent?.agent_name || '未命名 Agent' }}</span>
      <div class="ac-badges">
        <el-tag v-if="agent?.is_public === 1" size="small" type="success">公</el-tag>
        <el-tag v-else size="small" type="info">私</el-tag>
        <el-tag size="small" :type="agent?.status === '1' ? 'success' : 'info'">
          {{ agent?.status === '1' ? '启用' : '停用' }}
        </el-tag>
      </div>
    </div>
    <div class="ac-desc">{{ agent?.agent_description || '暂无描述' }}</div>
    <div class="ac-capabilities">
      <div class="ac-cap-row">
        <span class="ac-cap-label">Skills</span>
        <template v-if="(agent?.tools || []).length">
          <el-tag v-for="t in agent.tools" :key="t" size="small" style="margin: 2px">{{ t }}</el-tag>
        </template>
        <span v-else class="ac-empty">无</span>
      </div>
      <div class="ac-cap-row">
        <span class="ac-cap-label">MCP</span>
        <template v-if="(agent?.mcp_tools || []).length">
          <el-tag v-for="m in agent.mcp_tools" :key="m" size="small" type="warning" style="margin: 2px">{{ m }}</el-tag>
        </template>
        <span v-else class="ac-empty">无</span>
      </div>
      <div v-if="(agent?.external_tools || []).length" class="ac-cap-row">
        <span class="ac-cap-label">外部工具</span>
        <el-tag v-for="e in agent.external_tools" :key="e" size="small" type="danger" style="margin: 2px">{{ e }}</el-tag>
      </div>
    </div>
  </el-card>
</template>

<script setup>
/**
 * AgentCard：可复用的 agent 能力卡（A4 能力卡的前端呈现）。
 * 紧凑展示 name + 描述 + 能力标签（Skills/MCP/外部工具）+ 可见性 + 状态。
 * 复用点：AgentList 详情、调度/chat agent 选择器、auto_plan plan-review（下一步）。
 */
defineProps({
  agent: { type: Object, default: () => ({}) },
})
</script>

<style scoped>
.agent-card { border-radius: 8px; }
.ac-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.ac-name {
  font-weight: 600;
  font-size: 15px;
  color: #1E293B;
}
.ac-badges { display: flex; gap: 4px; }
.ac-desc {
  font-size: 13px;
  color: #64748B;
  margin-bottom: 8px;
  line-height: 1.5;
}
.ac-capabilities { display: flex; flex-direction: column; gap: 4px; }
.ac-cap-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
}
.ac-cap-label {
  font-size: 12px;
  color: #64748B;
  width: 56px;
  flex-shrink: 0;
}
.ac-empty {
  font-size: 12px;
  color: #94A3B8;
}
</style>
