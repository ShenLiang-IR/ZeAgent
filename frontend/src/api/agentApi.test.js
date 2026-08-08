// agentApi 契约测试：验证与后端 api/admin/agent_manage.py 路由一致
//   - getList(params?) → GET /admin/agents/list（支持可选 query）
//   - getDetail(id) → GET /admin/agents/{id}
//   - create(params) → POST /admin/agents/create
//   - update(id, params) → PUT /admin/agents/{id}
//   - delete(id) → DELETE /admin/agents/{id}
//   - toggle(id, enabled) → PATCH /admin/agents/{id}/toggle
//   - dispatch(id, params) → POST /admin/agents/{id}/dispatch
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('axios', () => {
  const http = {
    get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  }
  return { default: { create: () => http } }
})

import { agentApi } from './index'
import axios from 'axios'

const http = axios.create()

beforeEach(() => {
  Object.values(http).forEach((fn) => fn && fn.mockClear && fn.mockClear())
})

describe('agentApi 契约', () => {
  it('应导出全部预期方法', () => {
    expect(typeof agentApi.getList).toBe('function')
    expect(typeof agentApi.getDetail).toBe('function')
    expect(typeof agentApi.create).toBe('function')
    expect(typeof agentApi.update).toBe('function')
    expect(typeof agentApi.delete).toBe('function')
    expect(typeof agentApi.toggle).toBe('function')
    expect(typeof agentApi.dispatch).toBe('function')
  })

  it('getList 无参应调 GET /admin/agents/list', async () => {
    http.get.mockResolvedValue({ data: { agents: [] } })
    await agentApi.getList()
    expect(http.get).toHaveBeenCalledWith('/admin/agents/list')
  })

  it('getList 带 params 应传递 query（支持团队选 agent 拉大量 limit）', async () => {
    http.get.mockResolvedValue({ data: { agents: [] } })
    await agentApi.getList({ limit: 100, enabled: true })
    expect(http.get).toHaveBeenCalledWith('/admin/agents/list', {
      params: { limit: 100, enabled: true },
    })
  })

  it('getDetail 应调 GET /admin/agents/{id}', async () => {
    http.get.mockResolvedValue({ data: {} })
    await agentApi.getDetail(7)
    expect(http.get).toHaveBeenCalledWith('/admin/agents/7')
  })

  it('create 应调 POST /admin/agents/create 并传 params', async () => {
    http.post.mockResolvedValue({ data: {} })
    const params = { agent_name: 'team-test-agent' }
    await agentApi.create(params)
    expect(http.post).toHaveBeenCalledWith('/admin/agents/create', params)
  })

  it('update 应调 PUT /admin/agents/{id} 并传 params', async () => {
    http.put.mockResolvedValue({ data: {} })
    const params = { agent_name: 'renamed' }
    await agentApi.update(7, params)
    expect(http.put).toHaveBeenCalledWith('/admin/agents/7', params)
  })

  it('delete 应调 DELETE /admin/agents/{id}', async () => {
    http.delete.mockResolvedValue({ data: {} })
    await agentApi.delete(7)
    expect(http.delete).toHaveBeenCalledWith('/admin/agents/7')
  })

  it('toggle 应调 PATCH /admin/agents/{id}/toggle 并传 { enabled }', async () => {
    http.patch.mockResolvedValue({ data: {} })
    await agentApi.toggle(7, false)
    expect(http.patch).toHaveBeenCalledWith('/admin/agents/7/toggle', { enabled: false })
  })

  it('dispatch 应调 POST /admin/agents/{id}/dispatch 并传 params', async () => {
    http.post.mockResolvedValue({ data: {} })
    await agentApi.dispatch(7, { message: 'hi' })
    expect(http.post).toHaveBeenCalledWith('/admin/agents/7/dispatch', { message: 'hi' })
  })

  it('dispatch 无 params 应传空对象', async () => {
    http.post.mockResolvedValue({ data: {} })
    await agentApi.dispatch(7)
    expect(http.post).toHaveBeenCalledWith('/admin/agents/7/dispatch', {})
  })
})
