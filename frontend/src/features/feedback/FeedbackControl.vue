<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { session } from '../auth/session'
import { ApiError, errorMessage } from '../../shared/api/errors'
import { editFeedback, getOwnFeedback, submitFeedback, type FeedbackView, type Rating } from './api'

const props=defineProps<{messageId:string}>()
const feedback=ref<FeedbackView|null>(null)
const rating=ref<Rating|null>(null)
const comment=ref('')
const loading=ref(true)
const busy=ref(false)
const error=ref('')
let scope=0
let alive=true
onUnmounted(()=>{alive=false;scope++})
watch(()=>[props.messageId,session.state.user?.id],async()=>{
  const current=++scope
  loading.value=true;busy.value=false;feedback.value=null;rating.value=null;comment.value='';error.value=''
  try {
    const result=await getOwnFeedback(props.messageId)
    if(!alive || current!==scope) return
    feedback.value=result;rating.value=result?.rating??null;comment.value=result?.comment??''
  } catch(cause) {if(alive && current===scope) error.value=errorMessage(cause)}
  finally {if(alive && current===scope) loading.value=false}
},{immediate:true})
async function save() {
  if(busy.value || loading.value || !rating.value) return
  const current=scope
  const messageId=props.messageId
  const prior=feedback.value
  const body={rating:rating.value,comment:comment.value}
  busy.value=true;error.value=''
  try {
    const result=prior?await editFeedback(prior.id,body):await submitFeedback(messageId,body)
    if(!alive || current!==scope) return
    feedback.value=result;rating.value=result.rating;comment.value=result.comment
  } catch(cause) {
    if(!alive || current!==scope) return
    error.value=errorMessage(cause)
    if(cause instanceof ApiError && cause.status===409 && !prior) {
      try {
        const existing=await getOwnFeedback(messageId)
        if(alive && current===scope && existing) {
          feedback.value=existing;rating.value=existing.rating;comment.value=existing.comment
          error.value='反馈已存在，请修改后保存。'
        }
      } catch { /* keep the original error */ }
    }
  } finally {if(alive && current===scope) busy.value=false}
}
</script>
<template>
  <section class="feedback-control" :aria-label="'回答反馈 '+messageId">
    <p class="feedback-title">回答反馈</p>
    <p v-if="loading" class="muted">正在读取反馈…</p>
    <template v-else>
      <p v-if="feedback" class="muted">{{ feedback.status==='resolved'?'已处理':'待处理' }}<span v-if="feedback.resolution">：{{ feedback.resolution }}</span></p>
      <div class="ratings" role="group" aria-label="评价">
        <label><input v-model="rating" type="radio" value="up" :disabled="busy" />有帮助</label>
        <label><input v-model="rating" type="radio" value="down" :disabled="busy" />没帮助</label>
      </div>
      <label class="comment-label">补充说明（可选）<textarea v-model="comment" maxlength="2000" rows="2" :disabled="busy" /></label>
      <button type="button" :aria-label="feedback?'保存反馈修改':'提交反馈'" :disabled="busy || !rating" @click="save">{{ feedback?'保存修改':'提交反馈' }}</button>
    </template>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.feedback-control{border-top:1px solid #e1e8eb;margin-top:12px;padding-top:10px;display:grid;gap:8px;min-width:0}.feedback-control p{margin:0}.feedback-title{font-weight:600}.ratings{display:flex;flex-wrap:wrap;gap:16px}.ratings label{display:flex;gap:5px;align-items:center}.comment-label{display:grid;gap:4px}.comment-label textarea{width:100%;box-sizing:border-box;resize:vertical;font:inherit;border:1px solid #bdcbd2;border-radius:6px;padding:7px}.feedback-control button{justify-self:start;border:1px solid #7c9da5;background:#f0f9f8;border-radius:6px;padding:6px 12px;cursor:pointer}.feedback-control button:disabled{opacity:.5;cursor:default}[role=alert]{color:#b42318;overflow-wrap:anywhere}
</style>
