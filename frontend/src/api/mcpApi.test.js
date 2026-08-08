// mcpApi 契约测试：验证与后端 api/admin/mcp.py 路由一致
//   - page(params, config) → POST /admin/mcp/page
//   - register(params) → POST /admin/mcp/register（含 visibility 透传）
//   - update(params) → POST /admin/mcp/update（含 visibility 透传）
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('axios', () => {
  const http = {
    get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  }
  return { default: { create: () => http } }
})

import { mcpApi } from './index'
import axios from 'axios'

const http = axios.create()

beforeEach(() => {
  Object.values(http).forEach((fn) => fn && fn.mockClear && fn.mockClear())
})

describe('mcpApi 契约', () => {
  it('应导出 page/register/update 等方法', () => {
    expect(typeof mcpApi.page).toBe('function')
    expect(typeof mcpApi.register).toBe('function')
    expect(typeof mcpApi.update).toBe('function')
  })

  it('page 应调 POST /admin/mcp/page 透传 body + config', async () => {
    http.post.mockResolvedValue({ data: { code: '0000000000000000', data: { list: [], total: 0 } } })
    const params = { pageNo: 1, pageSize: 10 }
    const config = { params: { workspace_id: 2 } }
    await mcpApi.page(params, config)
    expect(http.post).toHaveBeenCalledWith('/admin/mcp/page', params, config)
  })

  it('register 应调 POST /admin/mcp/register 透传含 visibility 的 payload', async () => {
    http.post.mockResolvedValue({ data: { code: '0000000000000000', data: {} } })
    const payload = { mcpName: 't', connectionType: 'stdio', visibility: 'public' }
    await mcpApi.register(payload)
    expect(http.post).toHaveBeenCalledWith('/admin/mcp/register', payload)
    // 验证 visibility 字段存在于透传 body
    const [url, body] = http.post.mock.calls[0]
    expect(url).toBe('/admin/mcp/register')
    expect(body.visibility).toBe('public')
  })

  it('update 应调 POST /admin/mcp/update 透传含 visibility 的 payload', async () => {
    http.post.mockResolvedValue({ data: { code: '0000000000000000' } })
    const payload = { prKeyId: '1', visibility: 'workspace' }
    await mcpApi.update(payload)
    expect(http.post).toHaveBeenCalledWith('/admin/mcp/update', payload)
    const [, body] = http.post.mock.calls[0]
    expect(body.visibility).toBe('workspace')
  })
})
