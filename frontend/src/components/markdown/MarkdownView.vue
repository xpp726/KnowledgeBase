<script setup lang="ts">
// markdown-it + hljs 封装；渲染后把正文中 n∈[1,refCount] 的 [n] 锚点化（D1-c 联动基础）
import { nextTick, onMounted, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import sql from 'highlight.js/lib/languages/sql'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'
import 'highlight.js/styles/github.css'

hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('yaml', yaml)

const props = defineProps<{
  content: string
  refCount: number
}>()

const contentEl = ref<HTMLElement | null>(null)

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

const md = new MarkdownIt({
  html: false, // 不渲染原始 HTML，防注入
  linkify: true,
  breaks: false,
  highlight(str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(str, { language: lang }).value}</code></pre>`
      } catch {
        // 高亮失败走兜底
      }
    }
    return `<pre class="hljs"><code>${escapeHtml(str)}</code></pre>`
  },
})

// 把 [n] 文本节点替换为 .ref-anchor span；跳过代码块内文本
function anchorize(root: HTMLElement) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const textNodes: Text[] = []
  let node: Node | null = walker.nextNode()
  while (node) {
    const tn = node as Text
    if (!tn.parentElement?.closest('pre, code')) textNodes.push(tn)
    node = walker.nextNode()
  }
  for (const tn of textNodes) {
    const text = tn.nodeValue ?? ''
    const re = /\[(\d+)\]/g
    let match: RegExpExecArray | null
    let changed = false
    const parts: Array<string | number> = []
    let last = 0
    while ((match = re.exec(text)) !== null) {
      const n = Number(match[1])
      if (n >= 1 && n <= props.refCount) {
        if (match.index > last) parts.push(text.slice(last, match.index))
        parts.push(n)
        last = match.index + match[0].length
        changed = true
      }
    }
    if (!changed) continue
    if (last < text.length) parts.push(text.slice(last))
    const frag = document.createDocumentFragment()
    for (const p of parts) {
      if (typeof p === 'string') {
        frag.appendChild(document.createTextNode(p))
      } else {
        const span = document.createElement('span')
        span.className = 'ref-anchor'
        span.dataset.ref = String(p)
        span.textContent = `[${p}]`
        frag.appendChild(span)
      }
    }
    tn.parentNode?.replaceChild(frag, tn)
  }
}

// 流式增量：content 变化时重锚点化
watch(
  () => props.content,
  async () => {
    await nextTick()
    if (contentEl.value) anchorize(contentEl.value)
  },
)

// 静态初始（历史消息挂载即带完整内容）：onMounted 时 DOM 已渲染，补一次锚点化
onMounted(async () => {
  await nextTick()
  if (contentEl.value) anchorize(contentEl.value)
})
</script>

<template>
  <div ref="contentEl" class="markdown-body" v-html="md.render(content)" />
</template>
