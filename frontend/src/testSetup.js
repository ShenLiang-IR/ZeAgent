// frontend/src/testSetup.js
// vitest 全局 setup：jsdom 缺失的浏览器 API polyfill
// 让 Element Plus 组件（el-table / el-switch 等）能在 jsdom 下正常渲染

// ResizeObserver：el-table 等组件用
class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
global.ResizeObserver = ResizeObserver

// matchMedia：部分组件用
global.matchMedia = (query) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener() {},
  removeEventListener() {},
  addListener() {},
  removeListener() {},
  dispatchEvent() { return false },
})

// IntersectionObserver：部分弹窗组件用
class IntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return [] }
}
global.IntersectionObserver = IntersectionObserver

// scrollTo：部分组件用
global.scrollTo = () => {}
