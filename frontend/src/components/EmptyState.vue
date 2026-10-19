<script setup>
defineProps({
  icon: { type: String, default: 'Files' },
  title: { type: String, default: '暂无内容' },
  description: { type: String, default: '' }
})
</script>

<template>
  <div class="empty-block">
    <div class="empty-icon"><el-icon><component :is="icon" /></el-icon></div>
    <h4>{{ title }}</h4>
    <p v-if="description">{{ description }}</p>
    <div v-if="$slots.default" style="margin-top: 14px">
      <slot />
    </div>
  </div>
</template>
