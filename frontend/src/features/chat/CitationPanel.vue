<script setup lang="ts">
import { ref } from 'vue'
import { ElButton } from 'element-plus'
import { errorMessage } from '../../shared/api/errors'
import { downloadCitation } from './api'
import type { Citation } from './stream'

defineProps<{items:Citation[]}>()
const emit=defineEmits<{close:[]}>()
const downloading=ref<number|null>(null),error=ref('')
function location(item:Citation) {
  return [item.page_number?`第 ${item.page_number} 页`:'',item.paragraph_number?`第 ${item.paragraph_number} 段`:'',item.line_number?`第 ${item.line_number} 行`:''].filter(Boolean).join(' · ')
}
async function download(item:Citation) {
  if(downloading.value!==null) return
  downloading.value=item.index;error.value=''
  try {
    const blob=await downloadCitation(item)
    const url=URL.createObjectURL(blob),link=document.createElement('a')
    link.href=url;link.download=item.title;link.click()
    setTimeout(()=>URL.revokeObjectURL(url),0)
  } catch(cause) {error.value=errorMessage(cause)}
  finally {downloading.value=null}
}
</script>
<template>
  <aside class="citation-panel panel" aria-label="回答引用">
    <div class="heading"><h3>回答引用</h3><ElButton @click="emit('close')">关闭引用</ElButton></div>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <article v-for="item in items" :key="item.index" class="citation">
      <h4>[{{ item.index }}] {{ item.title }}</h4>
      <p v-if="location(item)" class="muted">{{ location(item) }}</p>
      <blockquote>{{ item.quote }}</blockquote>
      <ElButton v-if="item.source_type==='document'" aria-label="下载来源文件" :disabled="downloading!==null" @click="download(item)">下载来源文件</ElButton>
    </article>
  </aside>
</template>
<style scoped>
.citation-panel{margin-top:16px;min-width:0;overflow-wrap:anywhere}.heading{display:flex;justify-content:space-between;align-items:center;gap:12px}.heading h3{margin:0}.citation{border-top:1px solid #e1e9ed;padding:14px 0}.citation h4{margin:0}.citation blockquote{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 12px;padding-left:12px;border-left:3px solid #9ec7c8}
@media(max-width:500px){.heading{flex-direction:column;align-items:flex-start}}
</style>
