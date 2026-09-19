<script setup lang="ts">
// 数据统计页：页面负责筛选和 Store 生命周期，统计内容由展示组件承载。
import { computed, defineAsyncComponent, onMounted } from 'vue'
import StatsSummaryCards from '../components/stats/StatsSummaryCards.vue'
import StatsToolbar from '../components/stats/StatsToolbar.vue'
import { useStatsStore } from '../stores/stats'

const StatsDashboard = defineAsyncComponent(() => import('../components/stats/StatsDashboard.vue'))

const store = useStatsStore()
const hasData = computed(() => (store.summary?.cards.total ?? 0) > 0)

onMounted(() => {
  void store.reload()
})
</script>

<template>
  <div class="stats-view">
    <StatsToolbar
      :days="store.days"
      :mode="store.mode"
      :loading="store.loading"
      @days-change="store.setDays"
      @mode-change="store.setMode"
      @refresh="store.reload"
    />
    <StatsSummaryCards v-if="store.summary" :cards="store.summary.cards" />
    <StatsDashboard v-if="hasData && store.summary" :summary="store.summary" />

    <!-- 空态 -->
    <el-empty
      v-if="!store.loading && !hasData"
      description="当前筛选条件下暂无问答数据，先到问答页发起几次问答"
    />
  </div>
</template>

<style scoped>
.stats-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 16px 20px;
  gap: 12px;
  box-sizing: border-box;
  overflow-y: auto;
}

</style>
