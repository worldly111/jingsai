<script setup>
import { ref } from 'vue'

const props = defineProps({
  steps: { type: Array, default: () => [] },
  defaultOpen: { type: Boolean, default: false }
})

const open = ref(props.defaultOpen)

function level(node) {
  return node?.level || 'info'
}
</script>

<template>
  <div v-if="props.steps.length" class="trace-panel">
    <div class="trace-toggle" @click="open = !open">
      <el-icon color="#5b7c88"><Connection /></el-icon>
      <span>工作流执行轨迹</span>
      <span class="tag-soft">{{ props.steps.length }} 个节点</span>
      <span class="trace-toggle-hint">{{ open ? '收起' : '展开' }}</span>
      <el-icon :style="{ transition: 'transform .2s', transform: open ? 'rotate(180deg)' : 'none' }">
        <ArrowDown />
      </el-icon>
    </div>
    <div v-show="open" class="trace-wrap">
      <div v-for="(step, index) in props.steps" :key="`${step.node}-${index}`" class="trace-item">
        <div class="trace-node" :class="level(step)">{{ index + 1 }}</div>
        <div class="trace-content">
          <div class="trace-title">
            <span>{{ step.title || step.node }}</span>
            <span v-if="step.level && step.level !== 'info'" class="tag-soft" :class="{ gold: step.level === 'warning' }">
              {{ step.level }}
            </span>
            <span v-if="step.duration_ms !== undefined" class="trace-duration">{{ step.duration_ms }} ms</span>
          </div>
          <div v-if="step.summary" class="trace-summary">{{ step.summary }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.trace-panel {
  border: 1px solid var(--line);
  border-radius: 11px;
  background: #fcfdfd;
  overflow: hidden;
}

.trace-toggle {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 11px 15px;
  font-size: 12px;
  font-weight: 600;
  color: #52707c;
  cursor: pointer;
  user-select: none;
}

.trace-toggle-hint {
  margin-left: auto;
  font-size: 10.5px;
  font-weight: 400;
  color: var(--muted-2);
}

.trace-wrap {
  border-top: 1px solid #edf2f3;
  border-radius: 0;
  padding: 14px 16px 2px;
  background: #fff;
}

.trace-node.warning {
  background: #fdf5e7;
  border-color: #ecd9b3;
  color: #a67326;
}

.trace-node.error {
  background: #fcf0ef;
  border-color: #eed3d0;
  color: #b94b46;
}
</style>
