<template>
  <i class="iconfont-icon" ref="el" v-html="svg" :style="`width:${size}px;height:${size}px;display:inline-flex;align-items:center;justify-content:center;`"></i>
</template>

<script setup>
import { computed, ref, onMounted, watch, nextTick } from 'vue'
import svgsRaw from '../assets/iconfont_svgs.json'

const props = defineProps({
  name: { type: String, required: true },
  size: { type: Number, default: 20 }
})

const el = ref(null)

const svg = computed(() => {
  const data = typeof svgsRaw === 'string' ? JSON.parse(svgsRaw) : svgsRaw
  const raw = data[props.name] || ''
  // 覆盖 iconfont 默认 1em 为 100%（由外层 span 控制尺寸）
  return raw.replace('width: 1em;height: 1em', 'width: 100%;height: 100%')
})

// 单色图标 fill 改 currentColor（继承菜单文字色，科技黑底可见 + active 变科技青）；多色保留原色
const applyColor = () => {
  if (!el.value) return
  const svgEl = el.value.querySelector('svg')
  if (!svgEl) return
  const paths = Array.from(svgEl.querySelectorAll('path'))
  const fills = paths.map(p => p.getAttribute('fill')).filter(f => f && f !== 'currentColor')
  const unique = [...new Set(fills)]
  if (unique.length <= 1) {
    paths.forEach(p => p.setAttribute('fill', 'currentColor'))
  }
}
onMounted(applyColor)
watch(() => props.name, () => nextTick(applyColor))
</script>

<style scoped>
.iconfont-icon :deep(svg) {
  display: block;
}
</style>
