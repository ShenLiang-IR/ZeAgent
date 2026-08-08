<template>
  <div class="calendar-widget">
    <div class="cal-title-row">
      <h3 class="cal-title">我的日常</h3>
      <span class="cal-desc">日程安排，高效规划</span>
    </div>
    <div class="calendar-nav">
      <span class="header-year">{{ currentYear }}年</span>
      <span class="header-month">{{ currentMonth }}月</span>
      <div class="header-nav">
        <span class="nav-btn" @click="prevMonth">&lt;</span>
        <span class="nav-btn nav-today" @click="goToday">今</span>
        <span class="nav-btn" @click="nextMonth">&gt;</span>
      </div>
    </div>
    <div class="calendar-weekdays">
      <span v-for="d in weekDays" :key="d" class="weekday">{{ d }}</span>
    </div>
    <div class="calendar-days">
      <div
        v-for="(cell, idx) in calendarCells"
        :key="idx"
        class="day-cell"
        :class="{
          'day-today': cell.isToday,
          'day-current': cell.isCurrentMonth,
          'day-other': !cell.isCurrentMonth,
          'has-todo': cell.hasTodo,
        }"
      >
        <span class="day-num">{{ cell.day }}</span>
        <span v-if="cell.hasTodo" class="day-dot"></span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  todoDates: { type: Array, default: () => [] },  // 有待办事项的日期字符串数组，如 ["2026-08-03"]
})

const weekDays = ['一', '二', '三', '四', '五', '六', '日']

const now = new Date()
const currentYear = ref(now.getFullYear())
const currentMonth = ref(now.getMonth() + 1) // 1-12

const today = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
})

const todoSet = computed(() => new Set(props.todoDates || []))

const calendarCells = computed(() => {
  const year = currentYear.value
  const month = currentMonth.value
  // 当月第一天
  const firstDay = new Date(year, month - 1, 1)
  // 当月最后一天
  const lastDay = new Date(year, month, 0)
  // 第一天是周几（0=周日 → 映射到 6）
  const startDow = firstDay.getDay() === 0 ? 6 : firstDay.getDay() - 1
  // 最后一天是周几
  const endDow = lastDay.getDay() === 0 ? 6 : lastDay.getDay() - 1

  const cells = []
  // 上月填充
  const prevLastDay = new Date(year, month - 1, 0).getDate()
  for (let i = startDow - 1; i >= 0; i--) {
    const d = prevLastDay - i
    cells.push({ day: d, isCurrentMonth: false, isToday: false, hasTodo: false })
  }
  // 当月
  for (let d = 1; d <= lastDay.getDate(); d++) {
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    cells.push({
      day: d,
      isCurrentMonth: true,
      isToday: dateStr === today.value,
      hasTodo: todoSet.value.has(dateStr),
    })
  }
  // 下月填充
  const remaining = 7 - ((cells.length % 7) || 7)
  for (let d = 1; d <= remaining && cells.length < 42; d++) {
    cells.push({ day: d, isCurrentMonth: false, isToday: false, hasTodo: false })
  }
  return cells
})

const prevMonth = () => {
  if (currentMonth.value === 1) {
    currentYear.value--
    currentMonth.value = 12
  } else {
    currentMonth.value--
  }
}

const nextMonth = () => {
  if (currentMonth.value === 12) {
    currentYear.value++
    currentMonth.value = 1
  } else {
    currentMonth.value++
  }
}

const goToday = () => {
  const d = new Date()
  currentYear.value = d.getFullYear()
  currentMonth.value = d.getMonth() + 1
}
</script>

<style scoped>
.calendar-widget {
  width: 280px;
  background: #fff;
  border: 1px solid #E2E8F0;
  border-radius: 12px;
  padding: 12px 10px 10px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
  user-select: none;
}
.cal-title-row {
  display: flex; align-items: baseline; gap: 8px;
  margin-bottom: 10px; padding: 0 4px;
}
.cal-title {
  font-size: 15px; font-weight: 700; color: #1E293B; margin: 0;
}
.cal-desc {
  font-size: 11px; color: #94A3B8;
}
.calendar-nav {
  display: flex; align-items: center;
  margin-bottom: 8px; padding: 0 4px;
}
.header-year { font-size: 13px; color: #94A3B8; margin-right: 6px; }
.header-month { font-size: 16px; font-weight: 700; color: #1E293B; }
.header-nav { margin-left: auto; display: flex; gap: 4px; }
.nav-btn {
  width: 22px; height: 22px; display: flex; align-items: center; justify-content: center;
  border-radius: 4px; font-size: 12px; color: #64748B; cursor: pointer; transition: all 0.15s ease;
}
.nav-btn:hover { background: #F1F5F9; color: #6366F1; }
.nav-today {
  font-size: 11px; font-weight: 600; width: auto; padding: 0 6px;
}
.calendar-weekdays {
  display: grid; grid-template-columns: repeat(7, 1fr);
  margin-bottom: 4px;
}
.weekday {
  text-align: center; font-size: 11px; color: #94A3B8; padding: 4px 0; font-weight: 500;
}
.calendar-days {
  display: grid; grid-template-columns: repeat(7, 1fr);
}
.day-cell {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  height: 34px;
  border-radius: 6px;
  cursor: default;
  position: relative;
  transition: background 0.15s ease;
}
.day-cell.day-current:hover { background: #F1F5F9; }
.day-num {
  font-size: 13px; color: #334155; line-height: 1;
}
.day-other .day-num { color: #CBD5E1; }
.day-today {
  background: linear-gradient(135deg, #6366F1, #22D3EE);
  border-radius: 8px;
}
.day-today .day-num {
  color: #fff; font-weight: 700;
}
.day-dot {
  width: 4px; height: 4px; border-radius: 50%;
  background: #F59E0B;
  margin-top: 2px;
}
.day-today .day-dot { background: #FDE68A; }
.has-todo { /* parent marker */ }
</style>
