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
const editing=ref(false)
const error=ref('')
let scope=0
let alive=true
onUnmounted(()=>{alive=false;scope++})
watch(()=>[props.messageId,session.state.user?.id],async()=>{
  const current=++scope
  editing.value=false
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
    editing.value=false
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
    <p v-if="loading" class="muted">正在读取反馈…</p>
    <template v-else>
      <p v-if="feedback" class="muted">{{ feedback.status==='resolved'?'已处理':'待处理' }}<span v-if="feedback.resolution">：{{ feedback.resolution }}</span></p>
      <div class="ratings" role="group" aria-label="评价">
        <label><input v-model="rating" type="radio" value="up" :disabled="busy" @change="editing=true" />有帮助</label>
        <label><input v-model="rating" type="radio" value="down" :disabled="busy" @change="editing=true" />没帮助</label>
        <button v-if="feedback && !editing" type="button" @click="editing=true">修改反馈</button>
      </div>
      <div v-if="editing" class="feedback-editor">
        <label class="comment-label">补充说明（可选）<textarea v-model="comment" maxlength="2000" rows="2" :disabled="busy" /></label>
        <button type="button" :aria-label="feedback?'保存反馈修改':'提交反馈'" :disabled="busy || !rating" @click="save">{{ feedback?'保存修改':'提交反馈' }}</button>
      </div>
    </template>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.feedback-control { margin-top: 9px; display: grid; gap: 8px; font-size: 12px; }
.feedback-control p { margin: 0; }
.ratings { display: flex; gap: 8px; flex-wrap: wrap; }
.ratings label { display: inline-flex; align-items: center; white-space: nowrap; gap: 6px; margin: 0; padding: 3px 9px; font-size: 12px; font-weight: 400; border: 1px solid var(--line); border-radius: 8px; cursor: pointer; }
.ratings label:has(:checked) { background: var(--wash); border-color: var(--muted); }
.ratings input { width: 13px; height: 13px; }
.feedback-editor { max-width: 420px; }
.comment-label { display: grid; gap: 5px; margin: 0 0 8px; }
.feedback-control [role=alert] { color: var(--danger); }
</style>
