// frontend/src/api/triggerApi.test.js
// triggerApi 客户端测试（阶段 A）
//
// 验证契约与后端 api/admin/trigger.py 的路由定义一致：
//   - list(workspaceId, enabledOnly) → GET /admin/triggers?workspace_id=...&enabled_only=...
//   - getDetail(id) → GET /admin/triggers/{id}
//   - create(params) → POST /admin/triggers
//   - update(id, params) → PUT /admin/triggers/{id}
//   - delete(id) → DELETE /admin/triggers/{id}
//   - enable(id) → POST /admin/triggers/{id}/enable
//   - disable(id) → POST /admin/triggers/{id}/disable
//   - test(id) → POST /admin/triggers/{id}/test
//   - getLogs(id, limit) → GET /admin/triggers/{id}/logs?limit=...
import { describe, it, expect, vi, beforeEach } from 'vitest'

// mock axios：拦截 axios.create 返回的 http 实例的所有方法 + interceptors
vi.mock('axios', () => {
  const http = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    patch: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  }
  return {
    default: { create: () => http },
  }
})

import { triggerApi } from './index'
import axios from 'axios'

// 拿到 mock 后的 http 实例（axios.create 的返回）
const http = axios.create()

beforeEach(() => {
  // 每个测试前清空调用历史
  Object.values(http).forEach((fn) => fn && fn.mockClear && fn.mockClear())
})

describe('triggerApi 契约', () => {
  it('应导出 triggerApi 对象，含全部预期方法', () => {
    expect(triggerApi).toBeDefined()
    expect(typeof triggerApi.list).toBe('function')
    expect(typeof triggerApi.getDetail).toBe('function')
    expect(typeof triggerApi.create).toBe('function')
    expect(typeof triggerApi.update).toBe('function')
    expect(typeof triggerApi.delete).toBe('function')
    expect(typeof triggerApi.enable).toBe('function')
    expect(typeof triggerApi.disable).toBe('function')
    expect(typeof triggerApi.test).toBe('function')
    expect(typeof triggerApi.getLogs).toBe('function')
  })

  it('list 应调 GET /admin/triggers 并传 workspace_id + enabled_only', async () => {
    http.get.mockResolvedValue({ data: { triggers: [] } })
    await triggerApi.list(1, true)
    expect(http.get).toHaveBeenCalledWith('/admin/triggers', {
      params: { workspace_id: 1, enabled_only: true },
    })
  })

  it('list 默认 enabled_only=false', async () => {
    http.get.mockResolvedValue({ data: { triggers: [] } })
    await triggerApi.list(7)
    expect(http.get).toHaveBeenCalledWith('/admin/triggers', {
      params: { workspace_id: 7, enabled_only: false },
    })
  })

  it('getDetail 应调 GET /admin/triggers/{id}', async () => {
    http.get.mockResolvedValue({ data: {} })
    await triggerApi.getDetail('TRG_xxx')
    expect(http.get).toHaveBeenCalledWith('/admin/triggers/TRG_xxx')
  })

  it('create 应调 POST /admin/triggers 并传 params', async () => {
    http.post.mockResolvedValue({ data: {} })
    const params = { trigger_id: 'TRG_a', trigger_type: 'cron' }
    await triggerApi.create(params)
    expect(http.post).toHaveBeenCalledWith('/admin/triggers', params)
  })

  it('update 应调 PUT /admin/triggers/{id} 并传 params', async () => {
    http.put.mockResolvedValue({ data: {} })
    const params = { trigger_name: 'updated' }
    await triggerApi.update('TRG_b', params)
    expect(http.put).toHaveBeenCalledWith('/admin/triggers/TRG_b', params)
  })

  it('delete 应调 DELETE /admin/triggers/{id}', async () => {
    http.delete.mockResolvedValue({ data: {} })
    await triggerApi.delete('TRG_c')
    expect(http.delete).toHaveBeenCalledWith('/admin/triggers/TRG_c')
  })

  it('enable 应调 POST /admin/triggers/{id}/enable', async () => {
    http.post.mockResolvedValue({ data: {} })
    await triggerApi.enable('TRG_d')
    expect(http.post).toHaveBeenCalledWith('/admin/triggers/TRG_d/enable')
  })

  it('disable 应调 POST /admin/triggers/{id}/disable', async () => {
    http.post.mockResolvedValue({ data: {} })
    await triggerApi.disable('TRG_e')
    expect(http.post).toHaveBeenCalledWith('/admin/triggers/TRG_e/disable')
  })

  it('test 应调 POST /admin/triggers/{id}/test', async () => {
    http.post.mockResolvedValue({ data: {} })
    await triggerApi.test('TRG_f')
    expect(http.post).toHaveBeenCalledWith('/admin/triggers/TRG_f/test')
  })

  it('getLogs 应调 GET /admin/triggers/{id}/logs 并传 limit', async () => {
    http.get.mockResolvedValue({ data: { logs: [] } })
    await triggerApi.getLogs('TRG_g', 100)
    expect(http.get).toHaveBeenCalledWith('/admin/triggers/TRG_g/logs', {
      params: { limit: 100 },
    })
  })

  it('getLogs 默认 limit=50', async () => {
    http.get.mockResolvedValue({ data: { logs: [] } })
    await triggerApi.getLogs('TRG_h')
    expect(http.get).toHaveBeenCalledWith('/admin/triggers/TRG_h/logs', {
      params: { limit: 50 },
    })
  })
})
