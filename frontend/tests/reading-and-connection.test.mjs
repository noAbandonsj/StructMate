import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { createServer } from 'vite'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'

let server, markdown, connection, client, options
const originalFetch = globalThis.fetch
const response = (value, status = 200) => new Response(JSON.stringify(value), { status })
before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  markdown = await server.ssrLoadModule('/src/markdown.ts')
  connection = await server.ssrLoadModule('/src/state/connection.ts')
  client = await server.ssrLoadModule('/src/api/client.ts')
  options = await server.ssrLoadModule('/src/learning-options.ts')
})
after(async () => { globalThis.fetch = originalFetch; await server.close() })
const html = (text, citations = []) => renderToString(createSSRApp({ render: () => h('div', markdown.renderMarkdown(text, citations, () => {}, () => {})) }))

test('reading supports headings, tables and code without interpreting raw HTML or remote images', async () => {
  const value = await html('## 栈\n\n|操作|复杂度|\n|---|---|\n|push|O(1)|\n\n```c\nprintf("<script>alert(1)</script>");\n```\n\n<img src=x onerror=alert(1)>\n\n![图](https://example.com/track)\n\n[危险](javascript:alert(1))\n\n[正常](https://example.com/course)')
  assert.match(value.replace(/<!--.*?-->/g, ''), /<h2>栈<\/h2>/)
  assert.match(value, /<table>/)
  assert.match(value, /<pre><code>/)
  assert.match(value, /复制代码/)
  assert.doesNotMatch(value, /<(script|img|iframe)|href="javascript:|onerror="/i)
  assert.match(value, /href="https:\/\/example.com\/course" target="_blank" rel="noopener noreferrer"/)
})

test('only known prose citations become buttons; code, links and unknown numbers stay literal', async () => {
  const value = await html('依据 **[资料1]**，未知 [资料99]。`[资料1]`\n\n```text\n[资料1]\n```\n\n[链接[资料1]](https://example.com)', [1])
  assert.equal((value.match(/class="inline-citation"/g) || []).length, 1)
  assert.match(value, /<code>\[资料1\]<\/code>/)
  assert.match(value, /\[资料99\]/)
  assert.doesNotMatch(value, /<a[^>]*>[^<]*<button/)
})

test('network and server failures invalidate health immediately; a new health check recovers', async () => {
  globalThis.fetch = async () => response({ status: 'ok' })
  await connection.checkService()
  assert.equal(connection.serviceState.status, 'connected')
  globalThis.fetch = async () => { throw new Error('offline') }
  await assert.rejects(client.request('/learning/overview'))
  assert.equal(connection.serviceState.status, 'disconnected')
  globalThis.fetch = async () => response({ status: 'ok' })
  await connection.checkService()
  globalThis.fetch = async () => response({ message: '失败' }, 503)
  await assert.rejects(client.request('/practice-sessions'))
  assert.equal(connection.serviceState.status, 'disconnected')
  globalThis.fetch = async () => response({ status: 'ok' })
  await connection.checkService()
  assert.equal(connection.serviceState.status, 'connected')
})

test('validation errors and intentionally cancelled reads do not report a disconnected service', async () => {
  globalThis.fetch = async () => response({ status: 'ok' })
  await connection.checkService()
  globalThis.fetch = async () => response({ message: '输入有误' }, 422)
  await assert.rejects(client.request('/practice-sessions'))
  const controller = new AbortController(); controller.abort()
  globalThis.fetch = async () => { throw new Error('aborted') }
  await assert.rejects(client.request('/practice-sessions', { signal: controller.signal }))
  assert.equal(connection.serviceState.status, 'connected')
})

test('a stale successful probe cannot erase a newer business request failure', async () => {
  let release
  globalThis.fetch = () => new Promise(resolve => { release = resolve })
  const pending = connection.checkService()
  connection.markServiceUnavailable()
  release(response({ status: 'ok' }))
  await pending
  assert.equal(connection.serviceState.status, 'disconnected')
})

test('date shortcuts include both ends and follow Shanghai dates across month and year boundaries', () => {
  assert.deepEqual(options.recentDateRange(7, new Date('2026-12-31T16:30:00Z')), { from_date: '2026-12-26', to_date: '2027-01-01' })
  assert.deepEqual(options.recentDateRange(30, new Date('2028-03-01T00:00:00Z')), { from_date: '2028-02-01', to_date: '2028-03-01' })
})
