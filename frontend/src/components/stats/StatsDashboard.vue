<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { StatsSummary } from '../../types/observability'

use([BarChart, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{
  summary: StatsSummary
}>()

const trendOption = computed(() => {
  const trend = props.summary.trend
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', triggerOn: 'click', renderMode: 'richText' as const, confine: true },
    legend: { data: ['问答量', '命中率'], top: 0 },
    grid: { left: 48, right: 56, top: 40, bottom: 28, containLabel: true },
    xAxis: { type: 'category', data: trend.map((point) => point.date.slice(5)), axisLabel: { color: '#666', fontSize: 11, hideOverlap: true } },
    yAxis: [
      { type: 'value', name: '问答量', axisLabel: { color: '#666', fontSize: 11 } },
      { type: 'value', name: '命中率%', min: 0, max: 100, axisLabel: { color: '#666', fontSize: 11 } },
    ],
    series: [
      { name: '问答量', type: 'bar', data: trend.map((point) => point.count), itemStyle: { color: '#8BC8EA', borderRadius: [4, 4, 0, 0] }, label: { show: false } },
      { name: '命中率', type: 'line', yAxisIndex: 1, smooth: true, data: trend.map((point) => point.hit_rate), itemStyle: { color: '#52C41A' }, lineStyle: { color: '#52C41A', width: 2 }, label: { show: false } },
    ],
  }
})

const kbOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: {
    trigger: 'item',
    triggerOn: 'click',
    renderMode: 'richText' as const,
    confine: true,
    formatter: (point: { name: string; value: number; percent: number }) => `${point.name}: ${point.value} 次（${point.percent}%）`,
  },
  legend: { bottom: 0, type: 'scroll' as const },
  series: [{
    type: 'pie',
    radius: ['38%', '62%'],
    center: ['50%', '46%'],
    avoidLabelOverlap: true,
    label: { formatter: '{b}\n{d}%', color: '#555', fontSize: 11 },
    data: props.summary.kb_dist.map((item) => ({ name: item.kb_id === 'default' ? '默认知识库' : item.kb_id, value: item.count })),
  }],
}))
</script>

<template>
  <div class="content">
    <div class="panel trend-panel">
      <div class="panel-title">问答趋势（按天）</div>
      <v-chart class="chart" :option="trendOption" autoresize />
    </div>

    <div class="panel-row">
      <div class="panel top-panel">
        <div class="panel-title">高频问题 Top10</div>
        <el-table :data="summary.top_questions" size="small" class="top-table">
          <el-table-column type="index" label="#" width="48" align="center" />
          <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
          <el-table-column prop="count" label="次数" width="80" align="right" />
        </el-table>
      </div>
      <div class="panel top-panel">
        <div class="panel-title">Top 引用文档 Top10</div>
        <el-table :data="summary.top_docs" size="small" class="top-table">
          <el-table-column type="index" label="#" width="48" align="center" />
          <el-table-column prop="doc_name" label="文档" min-width="200" show-overflow-tooltip />
          <el-table-column prop="count" label="引用问答数" width="90" align="right" />
        </el-table>
      </div>
    </div>

    <div class="panel kb-panel">
      <div class="panel-title">知识库问答分布</div>
      <v-chart class="chart kb-chart" :option="kbOption" autoresize />
    </div>
  </div>
</template>

<style scoped>
.content { display: flex; flex-direction: column; gap: 12px; }
.panel { background: #fff; border: 1px solid var(--border-color); border-radius: 10px; padding: 14px 16px; }
.panel-title { font-size: 14px; font-weight: 600; margin-bottom: 10px; color: var(--text-color); }
.trend-panel .chart { height: 300px; }
.panel-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 12px; }
.kb-panel .chart { height: 260px; max-width: 520px; }
.top-table { width: 100%; }
</style>
