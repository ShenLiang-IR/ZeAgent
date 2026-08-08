// toolApi 契约测试：验证与后端 api/admin/tools.py 路由一致
//   - getList() → GET /admin/tools（带 skip/limit，工具管理页用，全局）
//   - getStats(workspaceId?) → GET /admin/tools/stats（统计概览用，按 workspace 筛选绑定工具数）
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('axios', () => {
  const http = {
    get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  }
  return { default: { create: () => http } }
})

import { toolApi } from './index'
import axios from 'axios'

const http = axios.create()

beforeEach(() => {
  Object.values(http).forEach((fn) => fn && fn.mockClear && fn.mockClear())
})

describe('toolApi 契约', () => {
  it('应导出 getList 与 getStats', () => {
    expect(typeof toolApi.getList).toBe('function')
    expect(typeof toolApi.getStats).toBe('function')
  })

  it('getList 无参应调 GET /admin/tools 带 skip/limit', async () => {
    http.get.mockResolvedValue({ data: { tools: [], total: 0 } })
    await toolApi.getList()
    expect(http.get).toHaveBeenCalledWith('/admin/tools', { params: { skip: 0, limit: 100 } })
  })

  it('getStats 无参（全部用户）应调 GET /admin/tools/stats 不带 workspace_id', async () => {
    http.get.mockResolvedValue({ data: { success: true, data: { total: 0 } } })
    await toolApi.getStats()
    expect(http.get).toHaveBeenCalledWith('/admin/tools/stats', { params: {} })
  })

  it('getStats 传 workspaceId 应带 workspace_id query（按用户筛选）', async () => {
    http.get.mockResolvedValue({ data: { success: true, data: { total: 3 } } })
    await toolApi.getStats(2)
    expect(http.get).toHaveBeenCalledWith('/admin/tools/stats', { params: { workspace_id: 2 } })
  })

  it('getStats 传 null 应不带 workspace_id（全部用户视角）', async () => {
    http.get.mockResolvedValue({ data: { success: true, data: { total: 0 } } })
    await toolApi.getStats(null)
    expect(http.get).toHaveBeenCalledWith('/admin/tools/stats', { params: {} })
  })
})
