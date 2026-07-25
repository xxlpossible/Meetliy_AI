import MarkdownIt from 'markdown-it'

// ============================================================
// Markdown 渲染器 — 全局单例
// ============================================================

const md = new MarkdownIt({
  html: false,            // 禁止原始 HTML（安全）
  linkify: true,          // 自动识别链接
  typographer: true,      // 智能引号等排版优化
  breaks: true,           // \n 转为 <br>
})

/**
 * 将 Markdown 字符串渲染为 HTML
 */
export function renderMarkdown(content: string): string {
  if (!content || typeof content !== 'string') return ''
  try {
    return md.render(content)
  } catch {
    return `<p class="md-error">${escapeHtml(content)}</p>`
  }
}

/**
 * 行内模式渲染（不包裹 <p>）
 */
export function renderInline(content: string): string {
  if (!content || typeof content !== 'string') return ''
  try {
    return md.renderInline(content)
  } catch {
    return escapeHtml(content)
  }
}

/** 简单的 HTML 转义 */
function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export default md
