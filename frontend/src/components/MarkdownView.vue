<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps({
  content: { type: String, default: '' }
})

marked.setOptions({ gfm: true, breaks: true })

const html = computed(() => {
  if (!props.content) return ''
  return DOMPurify.sanitize(marked.parse(props.content), {
    ADD_ATTR: ['target', 'rel']
  })
})
</script>

<template>
  <div class="md-body" v-html="html" />
</template>
