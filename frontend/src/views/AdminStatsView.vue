<template>
  <div class="page">
    <div class="page-head">
      <h2 class="page-title">统计</h2>
      <div class="days">
        <span class="days-label">统计天数</span>
        <el-select v-model="days" class="days-select" :disabled="loading" @change="load">
          <el-option v-for="option in DAY_OPTIONS" :key="option" :label="`近 ${option} 天`" :value="option" />
        </el-select>
      </div>
    </div>

    <LoadError v-if="error" :message="error" :loading="loading" @retry="load" />

    <el-skeleton v-else-if="!stats" :rows="8" animated />

    <div v-else v-loading="loading" class="content">
      <el-row :gutter="16" class="cards">
        <el-col :xs="24" :sm="8">
          <el-card shadow="never" class="stat-card">
            <div class="stat-label">近 {{ stats.days }} 天问答总数</div>
            <div class="stat-value">{{ stats.qa_total }}</div>
          </el-card>
        </el-col>
        <el-col :xs="24" :sm="8">
          <el-card shadow="never" class="stat-card">
            <div class="stat-label">证据不足次数</div>
            <div class="stat-value">{{ stats.insufficient_evidence_total }}</div>
          </el-card>
        </el-col>
        <el-col :xs="24" :sm="8">
          <el-card shadow="never" class="stat-card">
            <div class="stat-label">证据不足占比</div>
            <div class="stat-value">{{ ratioText }}</div>
          </el-card>
        </el-col>
      </el-row>

      <el-card shadow="never" class="chart-card">
        <template #header>各课程已发布资源数</template>
        <el-empty v-if="stats.courses.length === 0" description="暂无课程" :image-size="60" />
        <EChart v-else :option="courseOption" :height="courseHeight" aria-label="各课程已发布资源数柱状图" />
      </el-card>

      <el-row :gutter="16">
        <el-col :xs="24" :md="12">
          <el-card shadow="never" class="chart-card">
            <template #header>审核状态分布</template>
            <EChart :option="reviewOption" :height="280" aria-label="审核状态分布柱状图" />
          </el-card>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-card shadow="never" class="chart-card">
            <template #header>索引状态分布</template>
            <EChart :option="indexOption" :height="280" aria-label="索引状态分布柱状图" />
          </el-card>
        </el-col>
      </el-row>

      <el-card shadow="never" class="chart-card">
        <template #header>近 {{ stats.days }} 天每日问答</template>
        <EChart :option="dailyOption" :height="320" aria-label="每日问答次数与证据不足次数折线图" />
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import { api } from '../api'
import type { AdminStats } from '../api'
import EChart from '../components/EChart.vue'
import LoadError from '../components/LoadError.vue'
import { useApiError } from '../composables/useApiError'
import { INDEX_STATUS_LABELS, REVIEW_STATUS_LABELS } from '../utils/resource'

const DAY_OPTIONS = [7, 30, 90, 180]

// 配色取自 dataviz 参考调色板分类色前两位（蓝、橙），已用校验脚本验证相邻色的色觉差异分离度。
// 橙色在白底上对比度 2.88:1 略低于 3:1，因此折线图保留图例并在提示框中给出数值。
const SERIES_1 = '#257de0'
const SERIES_2 = '#f47230'
const TEXT = '#1f2d3d'
const TEXT_SECONDARY = '#5e6d82'
const GRID = '#e4e7ed'

const { handle } = useApiError()

const days = ref(30)
const stats = ref<AdminStats | null>(null)
const loading = ref(false)
const error = ref('')
let token = 0

async function load(): Promise<void> {
  const mine = ++token
  loading.value = true
  error.value = ''
  try {
    const result = await api.getAdminStats(days.value)
    if (mine !== token) return
    stats.value = result
  } catch (e) {
    const described = await handle(e, '统计数据加载失败，请稍后重试。')
    if (mine !== token) return
    stats.value = null
    error.value = described.message
  } finally {
    if (mine === token) loading.value = false
  }
}

const ratioText = computed(() => {
  const s = stats.value
  if (!s || s.qa_total === 0) return '-'
  return `${(s.insufficient_evidence_ratio * 100).toFixed(1)}%`
})

const courseHeight = computed(() => Math.max(220, (stats.value?.courses.length ?? 0) * 36 + 60))

const axisCommon = {
  axisLine: { lineStyle: { color: GRID } },
  axisTick: { show: false },
  axisLabel: { color: TEXT_SECONDARY },
}

const tooltipCommon = {
  backgroundColor: '#ffffff',
  borderColor: GRID,
  textStyle: { color: TEXT },
}

/** 单系列柱状图：类别轴 + 数量轴，柱顶带数值，只有端部圆角。 */
function barOption(categories: string[], values: number[], horizontal: boolean): EChartsCoreOption {
  const category = { type: 'category' as const, data: categories, ...axisCommon, inverse: horizontal }
  const value = {
    type: 'value' as const,
    minInterval: 1,
    axisLabel: { color: TEXT_SECONDARY },
    splitLine: { lineStyle: { color: GRID } },
  }
  return {
    grid: { left: 12, right: 32, top: 16, bottom: 12, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...tooltipCommon },
    xAxis: horizontal ? value : category,
    yAxis: horizontal ? category : value,
    series: [
      {
        type: 'bar',
        data: values,
        barMaxWidth: 28,
        itemStyle: { color: SERIES_1, borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0] },
        label: { show: true, position: horizontal ? 'right' : 'top', color: TEXT },
      },
    ],
  }
}

const courseOption = computed<EChartsCoreOption>(() => {
  const list = stats.value?.courses ?? []
  return barOption(
    list.map((c) => c.course_name),
    list.map((c) => c.published_resources),
    true,
  )
})

const reviewOption = computed<EChartsCoreOption>(() => {
  const counts = stats.value?.review_status
  const keys = Object.keys(REVIEW_STATUS_LABELS) as (keyof typeof REVIEW_STATUS_LABELS)[]
  return barOption(
    keys.map((k) => REVIEW_STATUS_LABELS[k]),
    keys.map((k) => counts?.[k] ?? 0),
    false,
  )
})

const indexOption = computed<EChartsCoreOption>(() => {
  const counts = stats.value?.index_status
  const keys = Object.keys(INDEX_STATUS_LABELS) as (keyof typeof INDEX_STATUS_LABELS)[]
  return barOption(
    keys.map((k) => INDEX_STATUS_LABELS[k]),
    keys.map((k) => counts?.[k] ?? 0),
    false,
  )
})

const dailyOption = computed<EChartsCoreOption>(() => {
  const daily = stats.value?.daily_qa ?? []
  const showSymbol = daily.length <= 31
  const line = (name: string, color: string, data: number[]) => ({
    name,
    type: 'line' as const,
    data,
    showSymbol,
    symbolSize: 8,
    lineStyle: { width: 2, color },
    itemStyle: { color, borderColor: '#ffffff', borderWidth: 2 },
  })
  return {
    grid: { left: 12, right: 24, top: 40, bottom: 12, containLabel: true },
    legend: { top: 0, left: 0, textStyle: { color: TEXT }, icon: 'roundRect' },
    tooltip: { trigger: 'axis', ...tooltipCommon },
    xAxis: {
      type: 'category',
      data: daily.map((d) => d.date.slice(5)),
      boundaryGap: false,
      ...axisCommon,
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: TEXT_SECONDARY },
      splitLine: { lineStyle: { color: GRID } },
    },
    series: [
      line('问答次数', SERIES_1, daily.map((d) => d.total)),
      line('证据不足次数', SERIES_2, daily.map((d) => d.insufficient_evidence)),
    ],
  }
})

onMounted(load)
</script>

<style scoped>
.page {
  min-width: 0;
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.page-title {
  margin: 0;
  font-size: 20px;
}

.days {
  display: flex;
  align-items: center;
  gap: 8px;
}

.days-label {
  color: var(--text-secondary);
  font-size: 14px;
}

.days-select {
  width: 130px;
}

.cards {
  margin-bottom: 16px;
}

.stat-card {
  margin-bottom: 16px;
}

.stat-label {
  font-size: 14px;
  color: var(--text-secondary);
}

.stat-value {
  margin-top: 4px;
  font-size: 32px;
  font-weight: 600;
  line-height: 1.3;
}

.chart-card {
  margin-bottom: 16px;
}

.content {
  min-height: 120px;
}
</style>
