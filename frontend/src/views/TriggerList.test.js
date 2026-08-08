// frontend/src/views/TriggerList.test.js
// TriggerList.vue 组件测试（阶段 B）
//
// 用真实 Element Plus 组件（global.plugins），jsdom + polyfill 保证渲染
// 测试范围：组件行为契约（mount + API 调用 + 用户交互）
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'

// ── 用 vi.hoisted 让 mock 变量与 vi.mock 一起提升，避免引用未初始化变量 ──
const { triggerApiStub, msgSuccess, msgError, msgWarning, msgInfo, confirmFn } = vi.hoisted(() => ({
  triggerApiStub: {
    list: vi.fn(),
    getDetail: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    enable: vi.fn(),
    disable: vi.fn(),
    test: vi.fn(),
    getLogs: vi.fn(),
  },
  msgSuccess: vi.fn(),
  msgError: vi.fn(),
  msgWarning: vi.fn(),
  msgInfo: vi.fn(),
  confirmFn: vi.fn(),
}))

vi.mock('../api', () => ({
  triggerApi: triggerApiStub,
}))

vi.mock('element-plus', async () => {
  const actual = await vi.importActual('element-plus')
  return {
    ...actual,
    ElMessage: Object.assign(msgSuccess, {
      success: msgSuccess,
      error: msgError,
      warning: msgWarning,
      info: msgInfo,
    }),
    ElMessageBox: { confirm: confirmFn },
  }
})

const sampleTriggers = [
  {
    trigger_id: 'TRG_a',
    trigger_name: '每日报告',
    trigger_type: 'cron',
    enabled: '1',
    config: '{"cron": "0 9 * * *"}',
    target_agent_ids: 'agt_a,agt_b',
    target_mode: 'parallel',
    message_template: '每日报告：{triggered_at}',
    workspace_id: 1,
  },
  {
    trigger_id: 'TRG_b',
    trigger_name: 'Webhook 接收',
    trigger_type: 'webhook',
    enabled: '0',
    config: '{"secret": "xxx"}',
    target_agent_ids: 'agt_c',
    target_mode: 'parallel',
    message_template: 'webhook: {payload}',
    workspace_id: 1,
  },
]

const mountOpts = () => ({
  global: { plugins: [ElementPlus] },
})

beforeEach(() => {
  Object.values(triggerApiStub).forEach((fn) => fn.mockReset())
  msgSuccess.mockClear()
  msgError.mockClear()
  msgWarning.mockClear()
  confirmFn.mockClear()
  confirmFn.mockResolvedValue('confirm')
})

describe('TriggerList.vue 组件', () => {
  it('mount 后应调 triggerApi.list 加载数据', async () => {
    triggerApiStub.list.mockResolvedValue({ data: { triggers: sampleTriggers } })
    const { default: TriggerList } = await import('./TriggerList.vue')
    const wrapper = mount(TriggerList, mountOpts())
    await flushPromises()
    expect(triggerApiStub.list).toHaveBeenCalled()
    const text = wrapper.text()
    expect(text).toContain('TRG_a')
    expect(text).toContain('TRG_b')
  })

  it('list 失败应不抛异常（友好降级）', async () => {
    triggerApiStub.list.mockRejectedValue(new Error('network'))
    const { default: TriggerList } = await import('./TriggerList.vue')
    const wrapper = mount(TriggerList, mountOpts())
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(msgWarning).toHaveBeenCalled()
  })

  it('点击"新建"按钮应打开创建弹窗', async () => {
    triggerApiStub.list.mockResolvedValue({ data: { triggers: [] } })
    const { default: TriggerList } = await import('./TriggerList.vue')
    const wrapper = mount(TriggerList, mountOpts())
    await flushPromises()
    expect(wrapper.find('.el-dialog').exists()).toBe(false)
    const buttons = wrapper.findAll('button')
    const newBtn = buttons.find((b) => b.text().includes('新建'))
    expect(newBtn).toBeDefined()
    await newBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.el-dialog').exists()).toBe(true)
  })

  it('点击"测试"按钮应调 triggerApi.test', async () => {
    triggerApiStub.list.mockResolvedValue({ data: { triggers: sampleTriggers } })
    triggerApiStub.test.mockResolvedValue({ data: { log_id: 'TRG_LOG_test' } })
    const { default: TriggerList } = await import('./TriggerList.vue')
    const wrapper = mount(TriggerList, mountOpts())
    await flushPromises()
    const buttons = wrapper.findAll('button')
    const testBtn = buttons.find((b) => b.text().includes('测试'))
    expect(testBtn).toBeDefined()
    await testBtn.trigger('click')
    await flushPromises()
    expect(triggerApiStub.test).toHaveBeenCalledWith('TRG_a')
    expect(msgSuccess).toHaveBeenCalled()
  })

  it('点击"删除"按钮应先确认再调 triggerApi.delete', async () => {
    triggerApiStub.list.mockResolvedValue({ data: { triggers: sampleTriggers } })
    triggerApiStub.delete.mockResolvedValue({ data: {} })
    const { default: TriggerList } = await import('./TriggerList.vue')
    const wrapper = mount(TriggerList, mountOpts())
    await flushPromises()
    const buttons = wrapper.findAll('button')
    const delBtn = buttons.find((b) => b.text().includes('删除'))
    expect(delBtn).toBeDefined()
    await delBtn.trigger('click')
    await flushPromises()
    expect(confirmFn).toHaveBeenCalled()
    expect(triggerApiStub.delete).toHaveBeenCalledWith('TRG_a')
  })

  it('点击"日志"按钮应调 triggerApi.getLogs 并显示', async () => {
    triggerApiStub.list.mockResolvedValue({ data: { triggers: sampleTriggers } })
    triggerApiStub.getLogs.mockResolvedValue({
      data: { logs: [{ log_id: 'TRG_LOG_1', status: 'completed', duration_ms: 100 }] },
    })
    const { default: TriggerList } = await import('./TriggerList.vue')
    const wrapper = mount(TriggerList, mountOpts())
    await flushPromises()
    const buttons = wrapper.findAll('button')
    const logsBtn = buttons.find((b) => b.text().includes('日志'))
    expect(logsBtn).toBeDefined()
    await logsBtn.trigger('click')
    await flushPromises()
    expect(triggerApiStub.getLogs).toHaveBeenCalledWith('TRG_a', 50)
  })

  it('点击"编辑"按钮应打开编辑弹窗预填数据', async () => {
    triggerApiStub.list.mockResolvedValue({ data: { triggers: sampleTriggers } })
    const { default: TriggerList } = await import('./TriggerList.vue')
    const wrapper = mount(TriggerList, mountOpts())
    await flushPromises()
    const editBtn = wrapper.findAll('button').find((b) => b.text().includes('编辑'))
    expect(editBtn).toBeDefined()
    await editBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.el-dialog').exists()).toBe(true)
    // trigger_id 在 disabled input 的 value 属性里（不在文本节点）
    const dialog = wrapper.find('.el-dialog')
    const triggerIdInput = dialog.find('input[placeholder="TRG_xxx"]')
    expect(triggerIdInput.exists()).toBe(true)
    expect(triggerIdInput.element.value).toBe('TRG_a')
  })
})
