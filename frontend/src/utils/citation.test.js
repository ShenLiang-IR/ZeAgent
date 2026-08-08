import { describe, it, expect } from 'vitest'
import { formatCitation } from './citation.js'

describe('formatCitation', () => {
  it('优先使用后端返回的 citation 字段', () => {
    const chunk = { citation: 'report.pdf · p.3 · chars 10-42', doc_name: 'x.pdf' }
    expect(formatCitation(chunk)).toBe('report.pdf · p.3 · chars 10-42')
  })

  it('无 citation 字段时由 doc_name/page/char 偏移拼接（旧响应兼容）', () => {
    const chunk = { doc_name: 'report.pdf', page: 3, char_start: 10, char_end: 42 }
    expect(formatCitation(chunk)).toBe('report.pdf · p.3 · chars 10-42')
  })

  it('无页码（txt/md）时只拼字符偏移', () => {
    const chunk = { doc_name: 'note.txt', char_start: 0, char_end: 5 }
    expect(formatCitation(chunk)).toBe('note.txt · chars 0-5')
  })

  it('仅有 doc_name 时退化为文档名', () => {
    expect(formatCitation({ doc_name: 'report.pdf' })).toBe('report.pdf')
  })

  it('空输入返回空串', () => {
    expect(formatCitation(null)).toBe('')
    expect(formatCitation(undefined)).toBe('')
    expect(formatCitation({})).toBe('')
  })
})
