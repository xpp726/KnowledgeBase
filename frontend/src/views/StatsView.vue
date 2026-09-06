<script setup lang="ts">
// 数据统计页（阶段 3）：指标卡 + 趋势图（柱=问答量/线=命中率）+ Top 问题/文档 + kb 分布
import { computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useStatsStore } from '../stores/stats'

use([BarChart, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const store = useStatsStore()

const cards = computed(() => store.summary?.cards)
const hasData = computed(() => (store.summary?.cards.total ?? 0) > 0)

function fmtMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`
}

// 趋势图：柱 = 按天问答量，线 = 命中率%（双轴）
const trendOption = computed(() => {
  const t = store.summary?.trend ?? []
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      triggerOn: 'click',
      renderMode: 'richText' as const,
      confine: true,
    },
    legend: { data: ['问答量', '命中率'], top: 0 },
    grid: { left: 48, right: 56, top: 40, bottom: 28, containLabel: true },
    xAxis: {
      type: 'category',
      data: t.map((p) => p.date.slice(5)), // MM-DD
      axisLabel: { color: '#666', fontSize: 11, hideOverlap: true },
    },
    yAxis: [
      { type: 'value', name: '问答量', axisLabel: { color: '#666', fontSize: 11 } },
      { type: 'value', name: '命中率%', min: 0, max: 100, axisLabel: { color: '#666', fontSize: 11 } },
    ],
    series: [
      {
        name: '问答量',
        type: 'bar',
        data: t.map((p) => p.count),
        itemStyle: { color: '#8BC8EA', borderRadius: [4, 4, 0, 0] },
        label: { show: false },
      },
      {
        name: '命中率',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: t.map((p) => p.hit_rate),
        itemStyle: { color: '#52C41A' },
        lineStyle: { color: '#52C41A', width: 2 },
        label: { show: false },
      },
    ],
  }
})

// kb 分布饼图
const kbOption = computed(() => {
  const d = store.summary?.kb_dist ?? []
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      triggerOn: 'click',
      renderMode: 'richText' as const,
      confine: true,
      formatter: (p: { name: string; value: number; percent: number }) =>
        `${p.name}: ${p.value} 次（${p.percent}%）`,
    },
    legend: { bottom: 0, type: 'scroll' as const },
    series: [
      {
        type: 'pie',
        radius: ['38%', '62%'],
        center: ['50%', '46%'],
        avoidLabelOverlap: true,
        label: { formatter: '{b}\n{d}%', color: '#555', fontSize: 11 },
        data: d.map((x) => ({
          name: x.kb_id === 'default' ? '默认知识库' : x.kb_id,
          value: x.count,
        })),
      },
    ],
  }
})

onMounted(() => {
  void store.reload()
})
</script>

<template>
  <div class="stats-view">
    <!-- 工具栏 -->
    <div class="toolbar">
      <el-select
        :model-value="store.days"
        class="days-select"
        @update:model-value="(v: number | null) => store.setDays(v)"
      >
        <el-option label="近 7 天" :value="7" />
        <el-option label="近 30 天" :value="30" />
        <el-option label="全部" :value="null" />
      </el-select>

      <el-select
        :model-value="store.mode"
        class="mode-select"
        @update:model-value="(v: string) => store.setMode(v)"
      >
        <el-option label="知识库问答" value="kb" />
        <el-option label="通用问答" value="general" />
        <el-option label="全部口径" value="all" />
      </el-select>

      <el-button class="refresh-btn" :loading="store.loading" @click="store.reload()">
        刷新
      </el-button>
    </div>

    <!-- 指标卡 -->
    <div v-if="cards" class="cards">
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

    <!-- 内容区 -->
    <div v-if="hasData" class="content">
      <!-- 趋势图 -->
      <div class="panel trend-panel">
        <div class="panel-title">问答趋势（按天）</div>
        <v-chart class="chart" :option="trendOption" autoresize />
      </div>

      <!-- 双栏：Top 问题 + Top 文档 -->
      <div class="panel-row">
        <div class="panel top-panel">
          <div class="panel-title">高频问题 Top10</div>
          <el-table :data="store.summary?.top_questions ?? []" size="small" class="top-table">
            <el-table-column type="index" label="#" width="48" align="center" />
            <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
            <el-table-column prop="count" label="次数" width="80" align="right" />
          </el-table>
        </div>
        <div class="panel top-panel">
          <div class="panel-title">Top 引用文档 Top10</div>
          <el-table :data="store.summary?.top_docs ?? []" size="small" class="top-table">
            <el-table-column type="index" label="#" width="48" align="center" />
            <el-table-column prop="doc_name" label="文档" min-width="200" show-overflow-tooltip />
            <el-table-column prop="count" label="引用问答数" width="90" align="right" />
          </el-table>
        </div>
      </div>

      <!-- kb 分布 -->
      <div class="panel kb-panel">
        <div class="panel-title">知识库问答分布</div>
        <v-chart class="chart kb-chart" :option="kbOption" autoresize />
      </div>
    </div>

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

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.days-select {
  width: 130px;
}

.mode-select {
  width: 140px;
}

.refresh-btn {
  margin-left: auto;
}

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

.card-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.card-value {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 600;
  color: var(--text-color);
}

.card-value .unit {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 400;
}

.content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel {
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 14px 16px;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--text-color);
}

.trend-panel .chart {
  height: 300px;
}

.panel-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 12px;
}

.kb-panel .chart {
  height: 260px;
  max-width: 520px;
}

.top-table {
  width: 100%;
}
</style>
