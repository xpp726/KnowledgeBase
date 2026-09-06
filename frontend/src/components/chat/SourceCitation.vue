<script setup lang="ts">
// 引用来源卡片：展开/收起 chunk 原文；点击→高亮正文 [n]；hover→卡片上方浮窗预览（跟随卡片）+ 正文锚点高亮
import { ref } from 'vue'
import type { SourceItem } from '../../types/api'

const props = defineProps<{ sources: SourceItem[] }>()
const emit = defineEmits<{
  select: [index: number]
  hover: [index: number]
  leave: []
}>()

const expanded = ref<number | null>(null)
const tipIndex = ref<number | null>(null)

function toggle(n: number) {
  expanded.value = expanded.value === n ? null : n
}
</script>

<template>
  <div class="source-citation">
    <div class="citation-title">引用来源（{{ sources.length }}）</div>
    <div class="citation-list">
      <div
        v-for="src in sources"
        :key="src.index"
        class="citation-card"
        @click="emit('select', src.index)"
        @mouseenter="tipIndex = src.index; emit('hover', src.index)"
        @mouseleave="tipIndex = null; emit('leave')"
      >
        <div class="citation-head">
          <span class="citation-index">[{{ src.index }}]</span>
          <span class="citation-doc">
            {{ src.doc_name }}<template v-if="src.page"> · 第 {{ src.page }} 页</template>
          </span>
          <span class="citation-score">{{ src.score.toFixed(2) }}</span>
          <el-button link size="small" type="primary" @click.stop="toggle(src.index)">
            {{ expanded === src.index ? '收起' : '展开' }}
          </el-button>
        </div>
        <div v-if="expanded === src.index" class="citation-text">{{ src.text }}</div>
        <div v-if="tipIndex === src.index" class="citation-tip">{{ src.text.slice(0, 140) }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.source-citation {
  margin-top: 8px;
}

.citation-title {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.citation-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.citation-card {
  position: relative;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
  padding: 6px 10px;
  cursor: pointer;
  transition: border-color 0.15s;
}

.citation-card:hover {
  border-color: var(--accent);
}

.citation-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.citation-index {
  color: var(--accent);
  font-weight: 600;
  flex-shrink: 0;
}

.citation-doc {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
}

.citation-score {
  color: var(--text-secondary);
  flex-shrink: 0;
}

.citation-text {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
  border-top: 1px dashed var(--border);
  padding-top: 6px;
  max-height: 140px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

/* hover 浮窗：跟随被 hover 的卡片，显示在卡片正上方 */
.citation-tip {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  z-index: 50;
  width: 320px;
  max-width: 70vw;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text);
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 160px;
  overflow-y: auto;
}
</style>
