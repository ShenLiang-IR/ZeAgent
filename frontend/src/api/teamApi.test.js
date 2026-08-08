// teamApi 契约测试：验证与后端 api/admin/agent_team.py 路由一致
//   - list() → GET /admin/teams
//   - detail(teamId) → GET /admin/teams/{teamId}
//   - create(params) → POST /admin/teams
//   - addMember(teamId, params) → POST /admin/teams/{teamId}/members
//   - getMembers(teamId) → GET /admin/teams/{teamId}/members
//   - sendMessage(params) → POST /admin/mailbox/send
//   - pollMessages(agentName) → GET /admin/mailbox/poll?agent_name=
//   - ackMessage(messageId) → POST /admin/mailbox/ack/{messageId}
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('axios', () => {
  const http = {
    get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  }
  return { default: { create: () => http } }
})

import { teamApi } from './index'
import axios from 'axios'

const http = axios.create()

beforeEach(() => {
  Object.values(http).forEach((fn) => fn && fn.mockClear && fn.mockClear())
})

describe('teamApi 契约', () => {
  it('应导出全部预期方法', () => {
    expect(typeof teamApi.list).toBe('function')
    expect(typeof teamApi.detail).toBe('function')
    expect(typeof teamApi.create).toBe('function')
    expect(typeof teamApi.addMember).toBe('function')
    expect(typeof teamApi.getMembers).toBe('function')
    expect(typeof teamApi.sendMessage).toBe('function')
    expect(typeof teamApi.pollMessages).toBe('function')
    expect(typeof teamApi.ackMessage).toBe('function')
  })

  it('list 应调 GET /admin/teams', async () => {
    http.get.mockResolvedValue({ data: { teams: [] } })
    await teamApi.list()
    expect(http.get).toHaveBeenCalledWith('/admin/teams')
  })

  it('detail 应调 GET /admin/teams/{teamId}', async () => {
    http.get.mockResolvedValue({ data: {} })
    await teamApi.detail('TEAM_abc123')
    expect(http.get).toHaveBeenCalledWith('/admin/teams/TEAM_abc123')
  })

  it('create 应调 POST /admin/teams 并传 params', async () => {
    http.post.mockResolvedValue({ data: {} })
    const params = {
      name: 'research-team',
      members: [{ agent_id: '7', role: 'researcher' }],
      description: '调研团队',
    }
    await teamApi.create(params)
    expect(http.post).toHaveBeenCalledWith('/admin/teams', params)
  })

  it('addMember 应调 POST /admin/teams/{teamId}/members 并传 params', async () => {
    http.post.mockResolvedValue({ data: {} })
    const params = { agent_id: '7', role: 'researcher' }
    await teamApi.addMember('TEAM_abc123', params)
    expect(http.post).toHaveBeenCalledWith('/admin/teams/TEAM_abc123/members', params)
  })

  it('getMembers 应调 GET /admin/teams/{teamId}/members', async () => {
    http.get.mockResolvedValue({ data: { agent_ids: [] } })
    await teamApi.getMembers('TEAM_abc123')
    expect(http.get).toHaveBeenCalledWith('/admin/teams/TEAM_abc123/members')
  })

  it('sendMessage 应调 POST /admin/mailbox/send 并传 params', async () => {
    http.post.mockResolvedValue({ data: {} })
    const params = {
      from_agent: 'researcher-agent',
      to_agent: 'summary-agent',
      content: '调研完成',
      msg_type: 'text',
    }
    await teamApi.sendMessage(params)
    expect(http.post).toHaveBeenCalledWith('/admin/mailbox/send', params)
  })

  it('pollMessages 应调 GET /admin/mailbox/poll 并传 agent_name query', async () => {
    http.get.mockResolvedValue({ data: { messages: [] } })
    await teamApi.pollMessages('summary-agent')
    expect(http.get).toHaveBeenCalledWith('/admin/mailbox/poll', {
      params: { agent_name: 'summary-agent' },
    })
  })

  it('ackMessage 应调 POST /admin/mailbox/ack/{messageId}', async () => {
    http.post.mockResolvedValue({ data: {} })
    await teamApi.ackMessage('MSG_abc123')
    expect(http.post).toHaveBeenCalledWith('/admin/mailbox/ack/MSG_abc123')
  })
})
