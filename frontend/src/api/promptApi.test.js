// promptApi 契约测试：验证与后端 api/admin/prompt_template.py 路由一致
//   - list() → GET /admin/prompts
//   - detail(name) → GET /admin/prompts/{name}
//   - create(params) → POST /admin/prompts
//   - update(id, params) → PUT /admin/prompts/{id}
//   - render(params) → POST /admin/prompts/render
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('axios', () => {
  const http = {
    get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  }
  return { default: { create: () => http } }
})

import { promptApi } from './index'
import axios from 'axios'

const http = axios.create()

beforeEach(() => {
  Object.values(http).forEach((fn) => fn && fn.mockClear && fn.mockClear())
})

describe('promptApi 契约', () => {
  it('应导出全部预期方法', () => {
    expect(typeof promptApi.list).toBe('function')
    expect(typeof promptApi.detail).toBe('function')
    expect(typeof promptApi.create).toBe('function')
    expect(typeof promptApi.update).toBe('function')
    expect(typeof promptApi.render).toBe('function')
  })

  it('list 应调 GET /admin/prompts', async () => {
    http.get.mockResolvedValue({ data: { templates: [] } })
    await promptApi.list()
    expect(http.get).toHaveBeenCalledWith('/admin/prompts')
  })

  it('detail 应调 GET /admin/prompts/{name}', async () => {
    http.get.mockResolvedValue({ data: {} })
    await promptApi.detail('greeting')
    expect(http.get).toHaveBeenCalledWith('/admin/prompts/greeting')
  })

  it('create 应调 POST /admin/prompts 并传 params', async () => {
    http.post.mockResolvedValue({ data: {} })
    const params = { name: 'greeting', content: 'Hello {{name}}', variables: ['name'] }
    await promptApi.create(params)
    expect(http.post).toHaveBeenCalledWith('/admin/prompts', params)
  })

  it('update 应调 PUT /admin/prompts/{id} 并传 params', async () => {
    http.put.mockResolvedValue({ data: {} })
    const params = { content: 'updated' }
    await promptApi.update(5, params)
    expect(http.put).toHaveBeenCalledWith('/admin/prompts/5', params)
  })

  it('render 应调 POST /admin/prompts/render 并传 params', async () => {
    http.post.mockResolvedValue({ data: { rendered: 'Hello Alice' } })
    const params = { name: 'greeting', variables: { name: 'Alice' } }
    await promptApi.render(params)
    expect(http.post).toHaveBeenCalledWith('/admin/prompts/render', params)
  })
})
