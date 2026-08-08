// skillApi 契约测试：验证 getList 支持可选 params（统计概览按 workspace 筛选）
//   - getList() → GET /admin/skills/list（无参，现有调用方 Dashboard/SkillList 不受影响）
//   - getList({ workspace_id }) → GET /admin/skills/list?workspace_id=X（统计概览按用户筛选）
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('axios', () => {
  const http = {
    get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  }
  return { default: { create: () => http } }
})

import { skillApi } from './index'
import axios from 'axios'

const http = axios.create()

beforeEach(() => {
  Object.values(http).forEach((fn) => fn && fn.mockClear && fn.mockClear())
})

describe('skillApi 契约 - getList 支持可选 params', () => {
  it('getList 无参应调 GET /admin/skills/list（不破坏现有调用方）', async () => {
    http.get.mockResolvedValue({ data: { success: true, data: { skills: [], total: 0 } } })
    await skillApi.getList()
    expect(http.get).toHaveBeenCalledWith('/admin/skills/list')
  })

  it('getList 带 params 应传 query（统计概览按 workspace 筛选）', async () => {
    http.get.mockResolvedValue({ data: { success: true, data: { skills: [], total: 0 } } })
    await skillApi.getList({ workspace_id: 2 })
    expect(http.get).toHaveBeenCalledWith('/admin/skills/list', { params: { workspace_id: 2 } })
  })
})
