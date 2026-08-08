// 检索结果引用定位展示助手（对齐后端 /api/rag/retrieve 的 citation 字段契约）

/**
 * 格式化检索 chunk 的引用定位串。
 * 优先用后端 citation；缺失时由 doc_name/page/char_start/char_end 拼接（兼容旧响应）。
 * @param {Object} chunk 检索结果块（doc_name/page/char_start/char_end/citation）
 * @returns {string} 如 'report.pdf · p.3 · chars 10-42'；无信息返回 ''
 */
export function formatCitation(chunk) {
  if (!chunk || typeof chunk !== 'object') return ''
  if (chunk.citation) return chunk.citation
  const parts = []
  if (chunk.doc_name) parts.push(chunk.doc_name)
  if (chunk.page) parts.push(`p.${chunk.page}`)
  if (chunk.char_start != null && chunk.char_end != null) {
    parts.push(`chars ${chunk.char_start}-${chunk.char_end}`)
  }
  return parts.join(' · ')
}
