// versionApi 契约测试：验证与后端 api/admin/agent_version.py 路由一致
//   - list(agentId) → GET /admin/agents/{id}/versions
//   - create(agentId, params) → POST /admin/agents/{id}/versions
//   - rollback(agentId, v) → POST /admin/agents/{id}/versions/{v}/rollback
//   - diff(agentId, v1, v2) → GET /admin/agents/{id}/versions/diff?v1=&v2=
//   注：发布不再有直接 publish API——发布统一经审批流（提交审批→审批通过=发布）
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('axios', () => {
  const http = {
    get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  }
  return { default: { create: () => http } }
})

import { versionApi } from './index'
import axios from 'axios'

const http = axios.create()

beforeEach(() => {
  Object.values(http).forEach((fn) => fn && fn.mockClear && fn.mockClear())
})

describe('versionApi 契约', () => {
  it('应导出全部预期方法（无直接 publish）', () => {
    expect(typeof versionApi.list).toBe('function')
    expect(typeof versionApi.create).toBe('function')
    expect(typeof versionApi.rollback).toBe('function')
    expect(typeof versionApi.diff).toBe('function')
    // 发布经审批流，不再提供直接 publish
    expect(versionApi.publish).toBeUndefined()
  })

  it('list 应调 GET /admin/agents/{id}/versions', async () => {
    http.get.mockResolvedValue({ data: { versions: [] } })
    await versionApi.list(7)
    expect(http.get).toHaveBeenCalledWith('/admin/agents/7/versions')
  })

  it('create 应调 POST /admin/agents/{id}/versions 并传 params', async () => {
    http.post.mockResolvedValue({ data: {} })
    const params = { version_no: '1.0.1', version_description: 'fix' }
    await versionApi.create(7, params)
    expect(http.post).toHaveBeenCalledWith('/admin/agents/7/versions', params)
  })

  it('rollback 应调 POST /admin/agents/{id}/versions/{v}/rollback', async () => {
    http.post.mockResolvedValue({ data: {} })
    await versionApi.rollback(7, '1.0.0')
    expect(http.post).toHaveBeenCalledWith('/admin/agents/7/versions/1.0.0/rollback')
  })

  it('diff 应调 GET /admin/agents/{id}/versions/diff 并传 v1+v2', async () => {
    http.get.mockResolvedValue({ data: {} })
    await versionApi.diff(7, '1.0.0', '1.0.1')
    expect(http.get).toHaveBeenCalledWith('/admin/agents/7/versions/diff', {
      params: { v1: '1.0.0', v2: '1.0.1' },
    })
  })
})
