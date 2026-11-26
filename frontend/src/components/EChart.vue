<template>
  <div ref="el" class="echart" :style="{ height: `${height}px` }" role="img" :aria-label="ariaLabel"></div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import type { ECharts, EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

// 按需引入：只注册统计页用到的图表、组件和渲染器。
echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = withDefaults(
  defineProps<{
    option: EChartsCoreOption
    height?: number
    ariaLabel?: string
  }>(),
  { height: 300, ariaLabel: '统计图表' },
)

const el = ref<HTMLDivElement>()
// 图表实例不需要深度响应式，用 shallowRef 避免 Vue 代理 ECharts 内部对象。
const chart = shallowRef<ECharts>()

function onResize(): void {
  chart.value?.resize()
}

onMounted(() => {
  if (!el.value) return
  chart.value = echarts.init(el.value)
  chart.value.setOption(props.option)
  window.addEventListener('resize', onResize)
})

watch(
  () => props.option,
  (option) => chart.value?.setOption(option, true),
)

// 容器高度变化（如课程数量变化）后需要重新计算画布。
watch(
  () => props.height,
  () => chart.value?.resize(),
  { flush: 'post' },
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart.value?.dispose()
  chart.value = undefined
})
</script>

<style scoped>
.echart {
  width: 100%;
}
</style>
