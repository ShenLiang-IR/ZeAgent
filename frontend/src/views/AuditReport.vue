<template>
  <el-card>
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span>审计报表</span>
        <div style="display: flex; gap: 8px; align-items: center;">
          <el-date-picker v-model="dateRange" type="daterange" range-separator="至"
            start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD"
            style="width: 260px;" @change="load" />
          <el-button @click="load">刷新</el-button>
        </div>
      </div>
    </template>
    <el-row :gutter="16" v-loading="loading">
      <el-col :span="8"><div class="stat-card"><div class="stat-num">{{ data.total || 0 }}</div><div class="stat-label">总操作数</div></div></el-col>
      <el-col :span="8"><div class="stat-card"><div class="stat-num">{{ data.by_user?.length || 0 }}</div><div class="stat-label">活跃用户</div></div></el-col>
      <el-col :span="8"><div class="stat-card"><div class="stat-num" :style="{ color: failRate > 5 ? '#F56C6C' : '#67C23A' }">{{ failRate }}%</div><div class="stat-label">失败率（非2xx）</div></div></el-col>
    </el-row>
    <el-row :gutter="16" style="margin-top: 16px;">
      <el-col :span="8">
        <v-chart :option="pieOpt(data.by_resource_type, '按资源类型')" style="height: 240px;" autoresize @click="p => onPieClick(p, 'resource_type')" />
      </el-col>
      <el-col :span="8">
        <v-chart :option="pieOpt(data.by_action, '按操作类型')" style="height: 240px;" autoresize @click="p => onPieClick(p, 'action')" />
      </el-col>
      <el-col :span="8">
        <v-chart :option="pieOpt(data.by_status, '按状态码')" style="height: 240px;" autoresize />
      </el-col>
    </el-row>
    <el-row :gutter="16" style="margin-top: 16px;">
      <el-col :span="12">
        <v-chart :option="pieOpt(data.by_user, '按用户 Top10')" style="height: 240px;" autoresize @click="p => onPieClick(p, 'username')" />
      </el-col>
      <el-col :span="12">
        <v-chart :option="barOpt(data.by_date, '按日期趋势')" style="height: 240px;" autoresize />
      </el-col>
    </el-row>
    <div style="text-align: center; color: #999; font-size: 12px; margin-top: 8px;">
      提示：点击饼图块可跳转审计明细并按该维度筛选
    </div>
  </el-card>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { auditApi } from '../api/index.js'
import { ElMessage } from 'element-plus'

const router = useRouter()
const data = ref({})
const loading = ref(false)
const dateRange = ref([])

const failRate = computed(() => {
  const s = data.value.by_status || []
  const fail = s.filter(x => !String(x.key).startsWith('2')).reduce((a, x) => a + x.count, 0)
  return data.value.total ? Math.round(fail / data.value.total * 100) : 0
})

const pieOpt = (arr, title) => ({
  title: { text: title, left: 'center', top: 0, textStyle: { fontSize: 13 } },
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  series: [{
    type: 'pie',
    radius: ['38%', '65%'],
    label: { formatter: '{b}: {d}%', fontSize: 10 },
    data: (arr || []).map(d => ({ name: d.key, value: d.count })),
  }],
})

const barOpt = (arr, title) => ({
  title: { text: title, left: 'center', top: 0, textStyle: { fontSize: 13 } },
  tooltip: { trigger: 'axis' },
  grid: { top: 40, bottom: 40, left: 40, right: 20 },
  xAxis: { type: 'category', data: (arr || []).map(d => d.key), axisLabel: { rotate: 30, fontSize: 10 } },
  yAxis: { type: 'value' },
  series: [{ type: 'bar', data: (arr || []).map(d => d.count), itemStyle: { color: '#409EFF' } }],
})

const onPieClick = (p, dim) => {
  // 点饼图块跳转明细 + 带该维度筛选
  const query = {}
  if (dim === 'resource_type') query.resource_type = p.name
  else if (dim === 'action') query.action = p.name
  else if (dim === 'username') query.username = p.name
  if (dateRange.value?.[0]) query.start_date = dateRange.value[0]
  if (dateRange.value?.[1]) query.end_date = dateRange.value[1]
  router.push({ path: '/stats/audit', query })
}

const load = async () => {
  loading.value = true
  try {
    const params = {}
    if (dateRange.value?.[0]) params.start_date = dateRange.value[0]
    if (dateRange.value?.[1]) params.end_date = dateRange.value[1]
    const res = await auditApi.summary(params)
    data.value = res?.data || res || {}
  } catch (e) {
    ElMessage.error('报表加载失败：' + (e.message || ''))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.stat-card { text-align: center; padding: 12px; background: #F1F5F9; border-radius: 4px; }
.stat-num { font-size: 28px; font-weight: bold; color: #409EFF; }
.stat-label { color: #999; font-size: 13px; margin-top: 4px; }
</style>
