<script setup lang="ts">
// 消息滚动容器：自动跟随（检测近底部才吸附）
import { nextTick, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useChatStore } from '../../stores/chat'
import MessageItem from './MessageItem.vue'

const store = useChatStore()
const { messages } = storeToRefs(store)
const listEl = ref<HTMLElement | null>(null)
let stick = true

function nearBottom(): boolean {
  const el = listEl.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 140
}

watch(
  messages,
  async () => {
    if (stick && listEl.value) {
      await nextTick()
      listEl.value.scrollTop = listEl.value.scrollHeight
    }
  },
  { deep: true },
)

function onScroll() {
  stick = nearBottom()
}
</script>

<template>
  <div ref="listEl" class="msg-list" @scroll="onScroll">
    <div v-if="!messages.length" class="msg-empty">
      <div class="msg-empty-title">知识库问答</div>
      <div class="msg-empty-desc">选择或新建会话，输入问题开始提问</div>
    </div>
    <div v-else class="msg-inner">
      <MessageItem v-for="m in messages" :key="m.localId" :message="m" />
    </div>
  </div>
</template>

<style scoped>
.msg-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 24px 24px;
}

.msg-inner {
  max-width: 960px;
  margin: 0 auto;
}

.msg-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.msg-empty-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
}

.msg-empty-desc {
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
