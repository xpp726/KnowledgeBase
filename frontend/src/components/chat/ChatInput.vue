<script setup lang="ts">
// 输入区：发送/停止切换（B1/B2）；Enter 发送、Shift+Enter 换行、中文输入法组合期不触发
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useChatStore } from '../../stores/chat'

const store = useChatStore()
const { streamState } = storeToRefs(store)
const text = ref('')

const busy = computed(
  () => streamState.value === 'connecting' || streamState.value === 'streaming',
)

function onSend() {
  const q = text.value.trim()
  if (!q || busy.value) return
  void store.sendMessage(q)
  text.value = ''
}

function onStop() {
  store.stopGeneration()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    onSend()
  }
}
</script>

<template>
  <div class="chat-input-bar">
    <div class="chat-input-wrap">
      <el-input
        v-model="text"
        type="textarea"
        :autosize="{ minRows: 1, maxRows: 6 }"
        :disabled="busy"
        placeholder="输入问题，Enter 发送，Shift+Enter 换行"
        resize="none"
        @keydown="onKeydown"
      />
      <div class="input-actions">
        <el-button v-if="busy" type="danger" plain @click="onStop">
          <el-icon><VideoPause /></el-icon>
          <span>停止生成</span>
        </el-button>
        <el-button v-else type="primary" :disabled="!text.trim()" @click="onSend">
          <el-icon><Promotion /></el-icon>
          <span>发送</span>
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-input-bar {
  border-top: 1px solid var(--border);
  background: var(--card);
  padding: 12px 24px 16px;
}

.chat-input-wrap {
  max-width: 960px;
  margin: 0 auto;
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.chat-input-wrap :deep(.el-textarea) {
  flex: 1;
}

.input-actions {
  flex-shrink: 0;
  padding-bottom: 2px;
}
</style>
