<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  suffix: { type: String, default: '' },
  note: { type: String, default: '' },
  tone: { type: String, default: 'teal' },
  icon: { type: String, default: 'DataLine' }
})
</script>

<template>
  <div class="stat-card" :class="tone">
    <div class="stat-top">
      <span class="stat-label">{{ label }}</span>
      <span class="stat-icon"><el-icon><component :is="icon" /></el-icon></span>
    </div>
    <div class="stat-value">
      <strong>{{ value }}</strong>
      <span v-if="suffix" class="suffix">{{ suffix }}</span>
    </div>
    <div v-if="note" class="stat-note">{{ note }}</div>
  </div>
</template>
