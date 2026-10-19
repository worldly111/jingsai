<script setup>
const props = defineProps({
  checks: { type: Array, default: () => [] }
})

const icons = {
  pass: 'CircleCheckFilled',
  info: 'InfoFilled',
  warning: 'WarningFilled',
  error: 'CircleCloseFilled'
}

function levelOf(check) {
  return ['pass', 'info', 'warning', 'error'].includes(check?.level) ? check.level : 'info'
}
</script>

<template>
  <div v-if="props.checks.length" class="checks">
    <div v-for="(check, index) in props.checks" :key="check.code || index" class="check-item" :class="levelOf(check)">
      <el-icon class="check-icon"><component :is="icons[levelOf(check)]" /></el-icon>
      <div class="check-main">
        <div class="check-msg">{{ check.message }}</div>
        <div v-if="check.suggestion" class="check-sug">{{ check.suggestion }}</div>
      </div>
    </div>
  </div>
</template>
