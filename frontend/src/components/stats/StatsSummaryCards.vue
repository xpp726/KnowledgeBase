<script setup lang="ts">
import type { StatsCards } from '../../types/observability'

defineProps<{
  cards: StatsCards
}>()

function fmtMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`
}
</script>

<template>
  <div class="cards">
    <div class="card">
      <div class="card-label">问答总数</div>
      <div class="card-value">{{ cards.total }}</div>
    </div>
    <div class="card">
      <div class="card-label">命中率</div>
      <div class="card-value">{{ cards.hit_rate }}<span class="unit">%</span></div>
    </div>
    <div class="card">
      <div class="card-label">平均检索耗时</div>
      <div class="card-value">{{ fmtMs(cards.avg_retrieval_ms) }}</div>
    </div>
    <div class="card">
      <div class="card-label">平均生成耗时</div>
      <div class="card-value">{{ fmtMs(cards.avg_llm_ms) }}</div>
    </div>
    <div class="card">
      <div class="card-label">平均总耗时</div>
      <div class="card-value">{{ fmtMs(cards.avg_total_ms) }}</div>
    </div>
    <div class="card">
      <div class="card-label">无命中问题</div>
      <div class="card-value">{{ cards.no_hit_count }}</div>
    </div>
  </div>
</template>

<style scoped>
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}

.card {
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 14px 16px;
}

.card-label { font-size: 12px; color: var(--text-secondary); }
.card-value { margin-top: 6px; font-size: 24px; font-weight: 600; color: var(--text-color); }
.card-value .unit { font-size: 13px; color: var(--text-secondary); font-weight: 400; }
</style>
