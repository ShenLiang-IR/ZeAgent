// externalToolApi 契约测试：验证与后端 api/admin/external_tools.py 路由一致
//   - getList() → GET /admin/external-tools
//   - create(params) → POST /admin/external-tools（含 visibility 透传）
//   - update(name, params) → PUT /admin/external-tools/{name}（含 visibility 透传）
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('axios', () => {
  const http = {
    get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  }
  return { default: { create: () => http } }
})

import { externalToolApi } from './index'
import axios from 'axios'

const http = axios.create()

beforeEach(() => {
  Object.values(http).forEach((fn) => fn && fn.mockClear && fn.mockClear())
})

describe('externalToolApi 契约', () => {
  it('应导出 getList/create/update 等方法', () => {
    expect(typeof externalToolApi.getList).toBe('function')
    expect(typeof externalToolApi.create).toBe('function')
    expect(typeof externalToolApi.update).toBe('function')
  })

  it('getList 应调 GET /admin/external-tools', async () => {
    http.get.mockResolvedValue({ data: { tools: [], total: 0 } })
    await externalToolApi.getList()
    expect(http.get).toHaveBeenCalledWith('/admin/external-tools')
  })

  it('create 应调 POST /admin/external-tools 透传含 visibility 的 payload', async () => {
    http.post.mockResolvedValue({ data: { success: true } })
    const payload = { name: 't', api_endpoint: '/x', method: 'POST', visibility: 'private' }
    await externalToolApi.create(payload)
    expect(http.post).toHaveBeenCalledWith('/admin/external-tools', payload)
    const [, body] = http.post.mock.calls[0]
    expect(body.visibility).toBe('private')
  })

  it('update 应调 PUT /admin/external-tools/{name} 透传含 visibility 的 payload', async () => {
    http.put.mockResolvedValue({ data: { success: true } })
    const params = { name: 't2', visibility: 'workspace' }
    await externalToolApi.update('t', params)
    expect(http.put).toHaveBeenCalledWith('/admin/external-tools/t', params)
    const [, body] = http.put.mock.calls[0]
    expect(body.visibility).toBe('workspace')
  })
})
