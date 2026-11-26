<script setup lang="ts">
import { ElButton } from 'element-plus'
import type { MessageView } from './api'
import type { Citation, ProgressStage } from './stream'
import { failureReason, progressLabels } from './status'
import FeedbackControl from '../feedback/FeedbackControl.vue'

const props=withDefaults(defineProps<{
  messages:MessageView[];canFeedback?:boolean
  progress?:{messageId:string;stage:ProgressStage}|null
  retryableMessageIds?:string[]
}>(),{canFeedback:false,progress:null,retryableMessageIds:()=>[]})
const emit=defineEmits<{citations:[items:Citation[],messageId:string];retry:[messageId:string]}>()
const roleLabels={user:'用户',assistant:'智能助手',agent:'客服',system:'系统'}
function progressText(messageId:string) {
  return props.progress?.messageId===messageId ? progressLabels[props.progress.stage] : '生成中…'
}
</script>
<template>
  <div class="message-list" aria-label="消息历史">
    <p v-if="!messages.length" class="muted">暂无消息，可以开始提问。</p>
    <article v-for="item in messages" :key="item.id" class="message" :class="item.role">
      <div class="message-heading"><strong>{{ roleLabels[item.role] }}</strong><small>{{ new Date(item.created_at).toLocaleString() }}</small></div>
      <p class="message-content">{{ item.content }}</p>
      <p v-if="item.status==='generating'" class="muted" role="status">{{ progressText(item.id) }}</p>
      <div v-else-if="item.status==='failed' || item.status==='cancelled'" class="message-result">
        <p><strong>{{ item.status==='failed'?'生成失败':'已取消' }}</strong> {{ failureReason(item.error_code,item.status) }}</p>
        <ElButton v-if="retryableMessageIds.includes(item.id)" aria-label="重试这条提问" @click="emit('retry',item.id)">重试这条提问</ElButton>
      </div>
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
.message-result { padding: 9px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--wash); font-size: 13px; }
.message-result p { margin: 0; }
.message-result .el-button { margin-top: 7px; }
</style>
