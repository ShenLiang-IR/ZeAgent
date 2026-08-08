// frontend/src/views/TeamList.test.js
// TeamList.vue 组件测试：团队管理 - 新增团队 / 成员管理
//
// 关键契约：后端团队 + 邮箱路由统一用 wrap_response，返回
//   { code, message, data: <实际数据> }
// 前端 axios 响应拦截器 (response) => response.data 已提取一层，
// 故 teamApi.*() 实际拿到 { code, message, data }。
// 组件必须从 res.data 取业务字段，而非顶层。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'

// ── vi.hoisted：mock 变量与 vi.mock 同步提升，避免引用未初始化变量 ──
const { teamApiStub, agentApiStub, msgSuccess, msgError, msgWarning, confirmFn } = vi.hoisted(() => ({
  teamApiStub: {
    list: vi.fn(),
    detail: vi.fn(),
    create: vi.fn(),
    addMember: vi.fn(),
    getMembers: vi.fn(),
    sendMessage: vi.fn(),
    pollMessages: vi.fn(),
    ackMessage: vi.fn(),
  },
  agentApiStub: {
    getList: vi.fn(),
  },
  msgSuccess: vi.fn(),
  msgError: vi.fn(),
  msgWarning: vi.fn(),
  confirmFn: vi.fn(),
}))

vi.mock('../api', () => ({
  teamApi: teamApiStub,
  agentApi: agentApiStub,
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

const sampleAgents = [
  { pr_key_id: 7, agent_name: 'researcher-agent' },
]

const sampleTeam = {
  pr_key_id: 1,
  team_id: 'TEAM_abc',
  name: '调研团队',
  description: '负责调研',
  members: JSON.stringify([{ agent_id: '7', role: 'researcher' }]),
  enabled: '1',
}

// 模拟真实运行时拦截器输出：后端 wrap_response → response.data 提取一层
const wrapList = (teams) => ({
  code: '0000000000000000',
  message: 'success',
  data: { teams, total: teams.length },
})
const wrap = (data) => ({
  code: '0000000000000000',
  message: 'success',
  data,
})

const mountOpts = () => ({ global: { plugins: [ElementPlus] } })

beforeEach(() => {
  Object.values(teamApiStub).forEach((fn) => fn.mockReset())
  Object.values(agentApiStub).forEach((fn) => fn.mockReset())
  msgSuccess.mockClear()
  msgError.mockClear()
  msgWarning.mockClear()
  confirmFn.mockClear()
  confirmFn.mockResolvedValue('confirm')
  // loadAgents 默认返回 Agent 列表
  agentApiStub.getList.mockResolvedValue({ agents: sampleAgents })
})

describe('TeamList.vue 团队管理', () => {
  it('loadData 应从 wrap_response.data.teams 加载团队列表', async () => {
    teamApiStub.list.mockResolvedValue(wrapList([sampleTeam]))
    const { default: TeamList } = await import('./TeamList.vue')
    const wrapper = mount(TeamList, mountOpts())
    await flushPromises()
    expect(teamApiStub.list).toHaveBeenCalled()
    // 团队名称应出现在页面（表格渲染）
    expect(wrapper.text()).toContain('调研团队')
  })

  it('loadData 失败应友好降级（不抛异常）', async () => {
    teamApiStub.list.mockRejectedValue(new Error('network'))
    const { default: TeamList } = await import('./TeamList.vue')
    const wrapper = mount(TeamList, mountOpts())
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(msgError).toHaveBeenCalled()
  })

  it('新建团队 save 成功后应调 create 并刷新列表', async () => {
    teamApiStub.list.mockResolvedValue(wrapList([]))
    teamApiStub.create.mockResolvedValue(wrap({ ...sampleTeam, name: '新团队' }))
    const { default: TeamList } = await import('./TeamList.vue')
    const wrapper = mount(TeamList, mountOpts())
    await flushPromises()
    expect(teamApiStub.list).toHaveBeenCalledTimes(1)

    // 点击「新建团队」打开弹窗
    const newBtn = wrapper.findAll('button').find((b) => b.text().includes('新建团队'))
    expect(newBtn).toBeDefined()
    await newBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.el-dialog').exists()).toBe(true)

    // 填写团队名称（弹窗内第一个 input 即 name）
    const nameInput = wrapper.find('.el-dialog input')
    expect(nameInput.exists()).toBe(true)
    await nameInput.setValue('新团队')
    await flushPromises()

    // 点击「保存」
    const saveBtn = wrapper.findAll('button').find((b) => b.text().includes('保存'))
    expect(saveBtn).toBeDefined()
    await saveBtn.trigger('click')
    await flushPromises()

    expect(teamApiStub.create).toHaveBeenCalledWith(expect.objectContaining({ name: '新团队' }))
    expect(msgSuccess).toHaveBeenCalled()
    // 成功后应刷新列表（list 再调一次）
    expect(teamApiStub.list).toHaveBeenCalledTimes(2)
  })

  it('openMembers 应从 wrap_response.data.members 加载成员', async () => {
    teamApiStub.list.mockResolvedValue(wrapList([sampleTeam]))
    teamApiStub.detail.mockResolvedValue(
      wrap({
        ...sampleTeam,
        members: JSON.stringify([{ agent_id: '7', role: 'researcher' }]),
      }),
    )
    const { default: TeamList } = await import('./TeamList.vue')
    const wrapper = mount(TeamList, mountOpts())
    await flushPromises()

    // 点击「成员」按钮
    const memBtn = wrapper.findAll('button').find((b) => b.text().includes('成员'))
    expect(memBtn).toBeDefined()
    await memBtn.trigger('click')
    await flushPromises()

    expect(teamApiStub.detail).toHaveBeenCalledWith('TEAM_abc')
    // 成员表格应解析 agent_id=7 → agent_name「researcher-agent」
    const dialog = wrapper.find('.el-dialog')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('researcher-agent')
  })
})
