<script setup lang="ts">
import { ElButton } from 'element-plus'
import type { MessageView } from './api'
import type { Citation } from './stream'

defineProps<{messages:MessageView[]}>()
const emit=defineEmits<{citations:[items:Citation[]]}>()
const roleLabels={user:'我',assistant:'智能助手',agent:'客服',system:'系统'}
const statusLabels={generating:'生成中…',complete:'',failed:'生成失败',cancelled:'已取消'}
</script>
<template>
  <div class="message-list" aria-label="消息历史">
    <p v-if="!messages.length" class="muted">暂无消息，可以开始提问。</p>
    <article v-for="item in messages" :key="item.id" class="message" :class="item.role">
      <div class="message-heading"><strong>{{ roleLabels[item.role] }}</strong><small>{{ new Date(item.created_at).toLocaleString() }}</small></div>
      <p class="message-content">{{ item.content }}</p>
      <p v-if="item.status!=='complete'" class="muted">{{ statusLabels[item.status] }}</p>
      <ElButton v-if="item.citations.length && !item.evidence_hidden" aria-label="查看引用" @click="emit('citations',item.citations)">查看引用（{{ item.citations.length }}）</ElButton>
    </article>
  </div>
</template>
<style scoped>
.message-list{display:grid;gap:12px}.message{border:1px solid #dce5e9;border-radius:14px;padding:16px;background:#fff;min-width:0;overflow-wrap:anywhere}.message.user{background:#eaf5f4}.message-heading{display:flex;justify-content:space-between;gap:12px;align-items:baseline}.message-heading small{color:#647887}.message-content{white-space:pre-wrap;overflow-wrap:anywhere;margin-bottom:8px}
@media(max-width:500px){.message-heading{flex-direction:column;gap:2px}}
</style>
