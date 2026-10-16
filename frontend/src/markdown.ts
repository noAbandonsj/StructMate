import MarkdownIt from 'markdown-it'
import { h, type VNodeChild } from 'vue'

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: false })
type Token = ReturnType<typeof markdown.parse>[number]
const tags = new Set(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 's', 'blockquote', 'ul', 'ol', 'li', 'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td'])
function safeHref(value: string) {
  if (/^#[^\s]*$/.test(value) || /^\/(?!\/|\\)[^\s]*$/.test(value)) return value
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined
  } catch { return undefined }
}

// Build Vue nodes from an explicit token allowlist. Model text never becomes raw HTML,
// event attributes, CSS or automatic image requests.
export function renderMarkdown(content: string, citations: number[] = [], onCitation?: (number: number) => void, onCopy?: (text: string) => void): VNodeChild[] {
  function render(tokens: Token[], inLink = false): VNodeChild[] {
    const root: { tag: string; attrs: Record<string, unknown>; children: VNodeChild[] } = { tag: '', attrs: {}, children: [] }
    const stack = [root]
    const push = (node: VNodeChild) => stack[stack.length - 1]!.children.push(node)
    for (const token of tokens) {
      if (token.nesting === 1) {
        const tag = tags.has(token.tag) ? token.tag : 'span'
        const attrs: Record<string, unknown> = {}
        if (tag === 'a') {
          attrs.href = safeHref(String(token.attrGet('href') || ''))
          if (attrs.href) { attrs.target = '_blank'; attrs.rel = 'noopener noreferrer' }
        }
        if (tag === 'ol' && token.attrGet('start')) attrs.start = Number(token.attrGet('start'))
        stack.push({ tag, attrs, children: [] })
      } else if (token.nesting === -1) {
        if (stack.length > 1) { const node = stack.pop()!; push(h(node.tag, node.attrs, node.children)) }
      } else if (token.type === 'inline') {
        push(render(token.children || [], inLink || stack.some(node => node.tag === 'a')))
      } else if (token.type === 'text') {
        const linked = inLink || stack.some(node => node.tag === 'a')
        for (const piece of token.content.split(/(\[资料\d+\])/)) {
          const match = /^\[资料(\d+)\]$/.exec(piece)
          const number = match ? Number(match[1]) : 0
          push(!linked && onCitation && citations.includes(number)
            ? h('button', { type: 'button', class: 'inline-citation', onClick: () => onCitation(number), 'aria-label': `查看资料 ${number}` }, piece)
            : piece)
        }
      } else if (token.type === 'code_inline') push(h('code', token.content))
      else if (token.type === 'fence' || token.type === 'code_block') {
        push(h('div', { class: 'code-block' }, [
          h('div', { class: 'code-toolbar' }, [h('span', token.info.trim().split(/\s+/)[0] || '代码'), onCopy ? h('button', { type: 'button', onClick: () => onCopy(token.content) }, '复制代码') : null]),
          h('pre', [h('code', token.content)]),
        ]))
      } else if (token.type === 'softbreak' || token.type === 'hardbreak') push(h('br'))
      else if (token.type === 'hr') push(h('hr'))
      else if (token.type === 'image') push(`[图片：${token.content || '未加载'}]`)
      else if (token.content) push(token.content)
    }
    while (stack.length > 1) { const node = stack.pop()!; push(h(node.tag, node.attrs, node.children)) }
    return root.children
  }
  return render(markdown.parse(content, {}))
}
