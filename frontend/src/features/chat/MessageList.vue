<script setup lang="ts">
import { ElButton } from 'element-plus'
import type { MessageView } from './api'
import type { Citation } from './stream'
import FeedbackControl from '../feedback/FeedbackControl.vue'

withDefaults(defineProps<{messages:MessageView[];canFeedback?:boolean}>(),{canFeedback:false})
const emit=defineEmits<{citations:[items:Citation[],messageId:string]}>()
const roleLabels={user:'用户',assistant:'智能助手',agent:'客服',system:'系统'}
const statusLabels={generating:'生成中…',complete:'',failed:'生成失败',cancelled:'已取消'}
</script>
<template>
  <div class="message-list" aria-label="消息历史">
    <p v-if="!messages.length" class="muted">暂无消息，可以开始提问。</p>
    <article v-for="item in messages" :key="item.id" class="message" :class="item.role">
      <div class="message-heading"><strong>{{ roleLabels[item.role] }}</strong><small>{{ new Date(item.created_at).toLocaleString() }}</small></div>
      <p class="message-content">{{ item.content }}</p>
      <p v-if="item.status!=='complete'" class="muted">{{ statusLabels[item.status] }}</p>
      <ElButton v-if="item.citations.length && !item.evidence_hidden" aria-label="查看引用" @click="emit('citations',item.citations,item.id)">查看引用（{{ item.citations.length }}）</ElButton>
      <FeedbackControl v-if="canFeedback && item.role==='assistant' && item.status==='complete'" :key="item.id" :message-id="item.id" />
    </article>
  </div>
</template>
<style scoped>
.message-list { display: grid; gap: 20px; }
.message { min-width: 0; max-width: 94%; overflow-wrap: anywhere; }
.message.user { justify-self: end; }
.message-heading { display: flex; align-items: baseline; gap: 10px; font-size: 12px; }
.message-heading small { margin: 0; font-size: 11px; }
.user .message-heading { justify-content: flex-end; }
.message-content { white-space: pre-wrap; margin: 6px 0; line-height: 1.8; }
.user .message-content { background: #f3f3f1; padding: 9px 14px; border-radius: 14px 4px 14px 14px; }
</style>
