import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8072',
        changeOrigin: true,
      },
    },
  },
  build: {
    // element-plus / mermaid 自身体积超 500kB（已按 vendor 拆分，调高告警阈值避免噪音）
    // 真正根治需 element-plus 按需导入 + mermaid 动态 import（后续优化）
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        // 拆分大 vendor，避免单个 app chunk 过大
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router'],
          'vendor-element': ['element-plus', '@element-plus/icons-vue'],
          'vendor-mermaid': ['mermaid'],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/testSetup.js'],
    coverage: {
      reporter: ['text', 'html'],
    },
  },
})
