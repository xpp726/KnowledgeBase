<script setup lang="ts">
// 单条消息：角色区分 / 流式光标 / Markdown / 引用联动（D1-c）/ 停止占位 / 错误重试 / 耗时行
import { ref } from 'vue'
import { useChatStore } from '../../stores/chat'
import type { MessageItem as MessageItemType } from '../../types/chat'
import MarkdownView from '../markdown/MarkdownView.vue'
import SourceCitation from './SourceCitation.vue'
import ErrorBubble from './ErrorBubble.vue'

const props = defineProps<{ message: MessageItemType }>()

const store = useChatStore()
const contentEl = ref<HTMLElement | null>(null)

function anchorEl(n: number): HTMLElement | null {
  return contentEl.value?.querySelector(`[data-ref="${n}"]`) ?? null
}

// 点击引用卡片：正文对应 [n] 滚动到可视区 + 短暂高亮
function onCitationSelect(n: number) {
  const el = anchorEl(n)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.add('ref-highlight')
  window.setTimeout(() => el.classList.remove('ref-highlight'), 1400)
}

// hover 引用卡片：正文 [n] 锚点高亮联动（浮窗预览在卡片组件内跟随卡片显示）
function onCitationHover(n: number) {
  const el = anchorEl(n)
  if (!el) return
  el.classList.add('ref-anchor-active')
}

function onCitationLeave() {
  const root = contentEl.value
  if (!root) return
  root.querySelectorAll('.ref-anchor-active').forEach((el) => {
    el.classList.remove('ref-anchor-active')
  })
}

// E1：耗时行（通用模式只显示生成耗时；知识库无命中时省略生成段）
function costLine(): string {
  const meta = props.message.meta
  if (!meta) return ''
  if (store.currentMode === 'general') {
    return `生成 ${(meta.llmMs / 1000).toFixed(1)}s`
  }
  const retr = `检索 ${Math.round(meta.retrievalMs)}ms`
  if (meta.hitCount === 0) return `${retr} · 总耗时 ${meta.elapsed.toFixed(1)}s`
  return `${retr} · 生成 ${(meta.llmMs / 1000).toFixed(1)}s · 总耗时 ${meta.elapsed.toFixed(1)}s`
}
</script>

<template>
  <div class="msg" :class="message.role">
    <div class="msg-avatar">{{ message.role === 'user' ? '我' : '答' }}</div>
    <div class="msg-body">
      <div ref="contentEl" class="msg-content">
        <MarkdownView
          v-if="message.role === 'assistant'"
          :content="message.content"
          :ref-count="message.refs.length"
        />
        <div v-else class="user-text">{{ message.content }}</div>
        <span v-if="message.streaming" class="typing-cursor">▍</span>
      </div>

      <div
        v-if="message.role === 'assistant' && message.refs.length"
        class="msg-refs"
      >
        <SourceCitation
          :sources="message.refs"
          @select="onCitationSelect"
          @hover="onCitationHover"
          @leave="onCitationLeave"
        />
      </div>

      <div v-if="message.stopped" class="stopped-badge">⏹ 已停止生成</div>
      <div
        v-if="
          message.meta &&
          message.meta.hitCount === 0 &&
          !message.error &&
          !message.stopped &&
          store.currentMode !== 'general'
        "
        class="no-hit-tip"
      >
        未命中知识库内容，可换个问法试试
      </div>
      <ErrorBubble
        v-if="message.error"
        :message="message.error"
        @retry="store.retryLast()"
      />
      <div
        v-if="message.meta && !message.error && !message.stopped"
        class="msg-meta-line"
      >
        {{ costLine() }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.msg {
  display: flex;
  gap: 12px;
  padding: 16px 0;
}

.msg-avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
}

.msg.user .msg-avatar {
  background: #8bc8ea;
}

.msg.assistant .msg-avatar {
  background: #9eacea;
}

.msg-body {
  flex: 1;
  min-width: 0;
  max-width: 860px;
}

.msg.user {
  flex-direction: row-reverse;
}

.msg.user .msg-body {
  display: flex;
  justify-content: flex-end;
}

.user-text {
  display: inline-block;
  background: rgba(139, 200, 234, 0.14);
  border: 1px solid rgba(139, 200, 234, 0.35);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.typing-cursor {
  display: inline-block;
  margin-left: 2px;
  color: var(--accent);
  animation: cursor-blink 0.9s steps(1) infinite;
}

@keyframes cursor-blink {
  50% {
    opacity: 0;
  }
}

.stopped-badge {
  display: inline-flex;
  align-items: center;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg);
  border: 1px dashed var(--border);
  border-radius: 6px;
  padding: 3px 8px;
}

.no-hit-tip {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.msg-meta-line {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  font-family: ui-monospace, Consolas, monospace;
}
</style>
