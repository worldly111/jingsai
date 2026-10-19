<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  option: { type: Object, default: null },
  height: { type: [Number, String], default: 320 }
})

const el = ref(null)
let chart = null
let observer = null

const palette = ['#128f85', '#1e5d78', '#c4a15b', '#5ba7a0', '#8a9ba4', '#d38b6a']

function applyOption() {
  if (!chart || !props.option) return
  chart.setOption(
    {
      color: palette,
      textStyle: { fontFamily: 'Inter, PingFang SC, Microsoft YaHei, sans-serif', color: '#546975' },
      animationDuration: 420
    },
    true
  )
  chart.setOption(props.option)
}

onMounted(() => {
  if (!el.value) return
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  applyOption()
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(el.value)
})

watch(
  () => props.option,
  () => applyOption(),
  { deep: true }
)

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="el" class="echart" :style="{ height: typeof height === 'number' ? `${height}px` : height }" />
</template>

<style scoped>
.echart {
  width: 100%;
}
</style>
