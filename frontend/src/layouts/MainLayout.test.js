// frontend/src/layouts/MainLayout.test.js
// 右上角用户菜单（下拉）测试：修改密码 / 切换工作空间 / 退出登录
//
// 契约：
//   - 触发器只显示用户名（去掉旧版 role）
//   - 下拉三项：修改密码、切换工作空间、退出登录（普通用户通用）
//   - 修改密码调 authApi.changePassword(old, new)
//   - 切换工作空间调 authApi.workspaces() 加载列表、authApi.switchWorkspace(id) 切换并更新本地 token
//   - 退出登录清 localStorage 并跳 /login
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'

const { modelApiStub, authApiStub, msgSuccess, msgError, msgWarning, confirmFn, routerPush } = vi.hoisted(() => ({
  modelApiStub: { list: vi.fn().mockResolvedValue({ list: [] }) },
  authApiStub: {
    changePassword: vi.fn(),
    workspaces: vi.fn(),
    switchWorkspace: vi.fn(),
  },
  msgSuccess: vi.fn(),
  msgError: vi.fn(),
  msgWarning: vi.fn(),
  confirmFn: vi.fn(),
  routerPush: vi.fn(),
}))

vi.mock('../api/index.js', () => ({
  modelApi: modelApiStub,
  authApi: authApiStub,
}))

// useRouter()（组合式）→ 返回带 push spy 的对象；模板里的 $route 由 mocks 提供
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
  useRoute: () => ({ path: '/dashboard', meta: { title: '仪表盘' } }),
}))

vi.mock('element-plus', async () => {
  const actual = await vi.importActual('element-plus')
  return {
    ...actual,
    ElMessage: Object.assign(msgSuccess, {
      success: msgSuccess,
      error: msgError,
      warning: msgWarning,
      info: msgSuccess,
    }),
    ElMessageBox: { confirm: confirmFn },
  }
})

const USER = { id: 2, username: 'alice', role: 'user', workspace_id: 1 }
let activeWrapper = null

beforeEach(() => {
  localStorage.setItem('user_info', JSON.stringify(USER))
  localStorage.setItem('auth_token', 'old_token')
  Object.values(authApiStub).forEach((fn) => fn.mockReset())
  msgSuccess.mockClear()
  msgError.mockClear()
  msgWarning.mockClear()
  routerPush.mockClear()
})

afterEach(() => {
  // 切换工作空间成功后会 setTimeout(300) 调 reload（jsdom 不支持导航）
  vi.clearAllTimers()
  // 卸载组件 + 清理 teleport 到 body 的残留（dropdown 菜单/弹窗）
  if (activeWrapper) { activeWrapper.unmount(); activeWrapper = null }
  document.body.innerHTML = ''
})

const mountLayout = async () => {
  const { default: MainLayout } = await import('../layouts/MainLayout.vue')
  activeWrapper = mount(MainLayout, {
    global: {
      plugins: [ElementPlus],
      stubs: ['router-view', 'el-icon'],
      mocks: {
        $route: { path: '/dashboard', meta: { title: '仪表盘' } },
        $router: { push: routerPush },
      },
    },
  })
  return activeWrapper
}

// el-dropdown 菜单 teleport 到 body：先点触发器，再从 wrapper 或 body 找菜单项点击
const clickDropdownItem = async (wrapper, text) => {
  await wrapper.find('.user-trigger').trigger('click')
  await flushPromises()
  let items = wrapper.findAll('.el-dropdown-menu__item')
  if (items.length) {
    const it = items.find((w) => w.text().includes(text))
    if (it) { await it.trigger('click'); await flushPromises(); return }
  }
  const domItems = document.body.querySelectorAll('.el-dropdown-menu__item')
  const target = [...domItems].find((e) => e.textContent.includes(text))
  if (!target) throw new Error(`下拉项未找到: ${text}`)
  target.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  await flushPromises()
}

// el-dialog 在 jsdom 下渲染在组件树内（非 teleport），但内容需在打开后多一次 flush 才稳定
const flushAll = async () => {
  await flushPromises()
  await new Promise((r) => setTimeout(r, 0))
}
const findDialog = (wrapper) => wrapper.find('.el-dialog')

describe('MainLayout 右上角用户菜单', () => {
  it('触发器只显示用户名（不显示 role）', async () => {
    const wrapper = await mountLayout()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('alice')
    // 旧版显示「用户名（role）」，新版不应出现 role 拼接
    expect(text).not.toContain('（user）')
  })

  it('下拉含 修改密码 / 切换工作空间 / 退出登录 三项', async () => {
    const wrapper = await mountLayout()
    await flushPromises()
    await wrapper.find('.user-trigger').trigger('click')
    await flushPromises()
    const allText = `${wrapper.text()} ${document.body.textContent || ''}`
    expect(allText).toContain('修改密码')
    expect(allText).toContain('切换工作空间')
    expect(allText).toContain('退出登录')
  })

  it('修改密码：填表提交应调 authApi.changePassword(old, new)', async () => {
    authApiStub.changePassword.mockResolvedValue({})
    const wrapper = await mountLayout()
    await flushPromises()
    await clickDropdownItem(wrapper, '修改密码')
    await flushAll()

    const dialog = findDialog(wrapper)
    expect(dialog.exists()).toBe(true)
    const inputs = dialog.findAll('input[type="password"]')
    expect(inputs.length).toBeGreaterThanOrEqual(3)
    await inputs[0].setValue('old123')
    await inputs[1].setValue('new123')
    await inputs[2].setValue('new123')
    await flushPromises()

    const confirmBtn = dialog.findAll('button').find((b) => b.text().includes('确认'))
    expect(confirmBtn).toBeDefined()
    await confirmBtn.trigger('click')
    await flushPromises()

    expect(authApiStub.changePassword).toHaveBeenCalledWith('old123', 'new123')
    expect(msgSuccess).toHaveBeenCalled()
  })

  it('修改密码：两次新密码不一致应 warning 且不调 API', async () => {
    authApiStub.changePassword.mockResolvedValue({})
    const wrapper = await mountLayout()
    await flushPromises()
    await clickDropdownItem(wrapper, '修改密码')
    await flushAll()

    const dialog = findDialog(wrapper)
    const inputs = dialog.findAll('input[type="password"]')
    await inputs[0].setValue('old123')
    await inputs[1].setValue('new123')
    await inputs[2].setValue('different456')
    await flushPromises()
    const confirmBtn = dialog.findAll('button').find((b) => b.text().includes('确认'))
    await confirmBtn.trigger('click')
    await flushPromises()

    expect(msgWarning).toHaveBeenCalled()
    expect(authApiStub.changePassword).not.toHaveBeenCalled()
  })

  it('切换工作空间：加载列表 + 切换并更新本地 token', async () => {
    authApiStub.workspaces.mockResolvedValue({
      list: [
        { workspace_id: 1, name: '默认空间' },
        { workspace_id: 2, name: '研发空间' },
      ],
    })
    authApiStub.switchWorkspace.mockResolvedValue({ token: 'new_token', workspace_id: 2 })

    const wrapper = await mountLayout()
    await flushPromises()
    await clickDropdownItem(wrapper, '切换工作空间')
    await flushAll()

    expect(authApiStub.workspaces).toHaveBeenCalled()
    const dialog = findDialog(wrapper)
    expect(dialog.exists()).toBe(true)
    const dialogText = dialog.text()
    expect(dialogText).toContain('默认空间')
    expect(dialogText).toContain('研发空间')

    // 默认选中 currentWorkspaceId=1，直接点「切换」
    const switchBtn = dialog.findAll('button').find((b) => b.text().includes('切换'))
    await switchBtn.trigger('click')
    await flushPromises()

    expect(authApiStub.switchWorkspace).toHaveBeenCalledWith(1)
    expect(localStorage.getItem('auth_token')).toBe('Bearer new_token')
    // user_info.workspace_id 应同步更新为切换后的值
    expect(JSON.parse(localStorage.getItem('user_info')).workspace_id).toBe(2)
    expect(msgSuccess).toHaveBeenCalled()
  })

  it('切换工作空间：选另一个空间后切换应传选中的 id', async () => {
    authApiStub.workspaces.mockResolvedValue({
      list: [
        { workspace_id: 1, name: '默认空间' },
        { workspace_id: 2, name: '研发空间' },
      ],
    })
    authApiStub.switchWorkspace.mockResolvedValue({ token: 'new_token', workspace_id: 2 })

    const wrapper = await mountLayout()
    await flushPromises()
    await clickDropdownItem(wrapper, '切换工作空间')
    await flushAll()
    const dialog = findDialog(wrapper)

    // 选第 2 个 radio（workspace_id=2）
    // EP el-radio 用 vModelRadio 监听 input 的 change 事件更新选中值；
    // jsdom 不模拟 label→input 关联，故直接触发 input change
    const radioInputs = dialog.findAll('input[type="radio"]')
    expect(radioInputs.length).toBeGreaterThanOrEqual(2)
    radioInputs[1].element.checked = true
    await radioInputs[1].trigger('change')
    await flushPromises()

    const switchBtn = dialog.findAll('button').find((b) => b.text().includes('切换'))
    await switchBtn.trigger('click')
    await flushPromises()

    expect(authApiStub.switchWorkspace).toHaveBeenCalledWith(2)
  })

  it('退出登录：清 localStorage 并跳 /login', async () => {
    const wrapper = await mountLayout()
    await flushPromises()
    await clickDropdownItem(wrapper, '退出登录')
    await flushPromises()
    expect(localStorage.getItem('auth_token')).toBeNull()
    expect(localStorage.getItem('user_info')).toBeNull()
    expect(routerPush).toHaveBeenCalledWith('/login')
  })
})

describe('MainLayout 菜单 adminOnly 过滤', () => {
  // el-sub-menu 折叠时 children 不渲染到 DOM，故直接断言 allGroups computed 数据
  const sessionChildren = (wrapper) => {
    const groups = wrapper.vm.allGroups || (wrapper.vm._ && wrapper.vm._.setupState && wrapper.vm._.setupState.allGroups) || []
    const g = groups.find((x) => x.index === '/session-group')
    return (g && g.children ? g.children : []).map((c) => c.index)
  }

  it('普通用户不见 记忆管理 / 会话跟踪（session-group 不含 memory/observability）', async () => {
    // beforeEach 已设 USER(role=user)
    const wrapper = await mountLayout()
    await flushPromises()
    const idx = sessionChildren(wrapper)
    expect(idx).not.toContain('/memory')
    expect(idx).not.toContain('/observability')
  })

  it('admin 可见 记忆管理 / 会话跟踪', async () => {
    localStorage.setItem('user_info', JSON.stringify({ ...USER, role: 'admin' }))
    const wrapper = await mountLayout()
    await flushPromises()
    const idx = sessionChildren(wrapper)
    expect(idx).toContain('/memory')
    expect(idx).toContain('/observability')
  })
})
