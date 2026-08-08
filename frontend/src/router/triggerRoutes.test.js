// frontend/src/router/triggerRoutes.test.js
// 路由 + 菜单测试（阶段 C）
//
// 验证：
//   - router 配置含 /triggers 路由，指向 TriggerList.vue
//   - MainLayout 在 admin 用户登录状态下显示"触发器管理"菜单项
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'

beforeEach(() => {
  // 模拟 admin 用户登录（MainLayout 从 localStorage 读 user_info）
  localStorage.setItem('user_info', JSON.stringify({ username: 'admin', role: 'admin', id: 1 }))
  localStorage.setItem('auth_token', 'fake_token')
})

describe('触发器路由 + 菜单注册', () => {
  it('router 应含 /triggers 路由，指向 TriggerList.vue', async () => {
    const { default: router } = await import('./index')
    const mainRoute = router.options.routes.find((r) => r.path === '/')
    expect(mainRoute).toBeDefined()
    const childRoute = mainRoute.children.find((r) => r.path === 'triggers')
    expect(childRoute).toBeDefined()
    expect(childRoute.name).toBe('TriggerList')
    expect(childRoute.meta?.title).toBe('触发器管理')
    expect(childRoute.meta?.adminOnly).toBe(true)
  })

  it('MainLayout 在 admin 用户下应显示"触发器管理"菜单项', async () => {
    vi.mock('../api/index.js', () => ({
      modelApi: { list: vi.fn().mockResolvedValue({ list: [] }) },
      authApi: {},
    }))

    // MainLayout 用 Composition API 的 useRoute/useRouter，需提供 router 插件
    const { default: MainLayout } = await import('../layouts/MainLayout.vue')
    const { createRouter, createMemoryHistory } = await import('vue-router')
    const testRouter = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' }, children: [
          { path: 'triggers', name: 'TriggerList', component: { template: '<div />' }, meta: { title: '触发器管理', adminOnly: true } },
          { path: 'workspace', name: 'WorkspaceDashboard', component: { template: '<div />' } },
        ]},
      ],
    })
    await testRouter.push('/triggers')
    await testRouter.isReady()

    const wrapper = mount(MainLayout, {
      global: {
        plugins: [ElementPlus, testRouter],
        stubs: ['router-view', 'el-icon'],
      },
    })
    await flushPromises()
    const text = wrapper.text()
    // 菜单 label 是"触发器"（icon 名才是"触发器管理"）
    expect(text).toContain('触发器')
  })
})
