// frontend/src/api/errorHandler.test.js
// axios 拦截器错误处理统一测试（任务 1 前端）
//
// 验证：handleApiError(error) 函数统一处理后端 {code, message, data} 格式错误
// - 4xx：ElMessage.error(message)
// - 429：ElMessage.warning('请求过于频繁')
// - 401：清 token + 跳转 /login
// - 5xx：ElMessage.error('服务器错误: ...')
// - 网络错误（无 response）：ElMessage.error('网络错误')
import { describe, it, expect, vi, beforeEach } from 'vitest'

// ── mock element-plus ElMessage ──
const { msgError, msgWarning, msgSuccess } = vi.hoisted(() => ({
  msgError: vi.fn(),
  msgWarning: vi.fn(),
  msgSuccess: vi.fn(),
}))

vi.mock('element-plus', () => {
  const fn = Object.assign(msgError, {
    success: msgSuccess,
    error: msgError,
    warning: msgWarning,
  })
  return {
    ElMessage: fn,
    ElMessageBox: { confirm: vi.fn() },
  }
})

describe('handleApiError 错误处理统一', () => {
  beforeEach(() => {
    msgError.mockClear()
    msgWarning.mockClear()
    msgSuccess.mockClear()
    localStorage.clear()
  })

  it('应可从 api/index.js 导入 handleApiError', async () => {
    const { handleApiError } = await import('./index.js')
    expect(typeof handleApiError).toBe('function')
  })

  it('400 错误应 ElMessage.error(message)', async () => {
    const { handleApiError } = await import('./index.js')
    const error = {
      response: {
        status: 400,
        data: { code: '9999999999999999', message: 'trigger_id 已存在', data: null },
      },
    }
    handleApiError(error).catch(() => {})
    expect(msgError).toHaveBeenCalledWith('trigger_id 已存在')
  })

  it('404 错误应 ElMessage.error(message)', async () => {
    const { handleApiError } = await import('./index.js')
    const error = {
      response: {
        status: 404,
        data: { code: '9999999999999999', message: 'trigger 不存在', data: null },
      },
    }
    handleApiError(error).catch(() => {})
    expect(msgError).toHaveBeenCalledWith('trigger 不存在')
  })

  it('429 rate limit 应 ElMessage.warning("请求过于频繁")', async () => {
    const { handleApiError } = await import('./index.js')
    const error = {
      response: {
        status: 429,
        data: { code: '9999999999999999', message: 'Too Many Requests', data: null },
      },
    }
    handleApiError(error).catch(() => {})
    expect(msgWarning).toHaveBeenCalledWith(expect.stringContaining('频繁'))
  })

  it('401 未授权应清 token + 跳转 /login', async () => {
    const { handleApiError } = await import('./index.js')
    localStorage.setItem('auth_token', 'fake_token')
    // mock window.location
    const originalLocation = window.location
    delete window.location
    window.location = { href: '', ...originalLocation }
    const error = {
      response: {
        status: 401,
        data: { code: '9999999999999999', message: '未授权', data: null },
      },
    }
    handleApiError(error).catch(() => {})
    expect(localStorage.getItem('auth_token')).toBeNull()
    expect(window.location.href).toBe('/login')
    window.location = originalLocation
  })

  it('500 服务器错误应 ElMessage.error("服务器错误: ...")', async () => {
    const { handleApiError } = await import('./index.js')
    const error = {
      response: {
        status: 500,
        data: { code: '9999999999999999', message: '内部错误: RuntimeError', data: null },
      },
    }
    handleApiError(error).catch(() => {})
    expect(msgError).toHaveBeenCalledWith(expect.stringContaining('服务器错误'))
    expect(msgError).toHaveBeenCalledWith(expect.stringContaining('内部错误'))
  })

  it('无 response（网络错误）应 ElMessage.error("网络错误")', async () => {
    const { handleApiError } = await import('./index.js')
    const error = { message: 'Network Error' }  // 无 response
    handleApiError(error).catch(() => {})
    expect(msgError).toHaveBeenCalledWith(expect.stringContaining('网络'))
  })

  it('无 message 字段应 fallback 到 error.message', async () => {
    const { handleApiError } = await import('./index.js')
    const error = {
      response: {
        status: 400,
        data: {},  // 无 message 字段
      },
      message: 'fallback error msg',
    }
    handleApiError(error).catch(() => {})
    expect(msgError).toHaveBeenCalledWith('fallback error msg')
  })
})
