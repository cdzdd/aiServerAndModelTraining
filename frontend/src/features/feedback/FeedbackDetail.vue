<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { session } from '../auth/session'
import { ApiError, errorMessage } from '../../shared/api/errors'
import { getFeedbackDetail, resolveFeedback, type FeedbackDetailView } from './api'

const route=useRoute()
const detail=ref<FeedbackDetailView|null>(null),loading=ref(false),busy=ref(false),error=ref(''),notice=ref(''),resolution=ref(''),refresh=ref(0)
let scope=0,alive=true
onUnmounted(()=>{alive=false;scope++})
watch(()=>[route.params.feedbackId,session.state.user?.id,session.state.user?.role,refresh.value],async(value,oldValue)=>{
  const current=++scope,id=String(route.params.feedbackId??'')
  loading.value=true;detail.value=null;error.value='';notice.value='';busy.value=false;resolution.value=''
  if(oldValue && (oldValue[1]!==value[1] || oldValue[2]!==value[2]) && session.state.user?.role!=='admin') {loading.value=false;return}
  try {
    const result=await getFeedbackDetail(id)
    if(!alive || current!==scope) return
    detail.value=result;resolution.value=result.feedback.resolution
  } catch(cause) {if(alive && current===scope) {
    if(cause instanceof ApiError && [401,403,404].includes(cause.status)) {detail.value=null;resolution.value=''}
    error.value=errorMessage(cause)
  }}
  finally {if(alive && current===scope) loading.value=false}
},{immediate:true})
async function update(status:'open'|'resolved') {
  if(busy.value || !detail.value) return
  const id=detail.value.feedback.id,current=scope
  if(status==='resolved' && !resolution.value.trim()) {error.value='请填写处理说明。';return}
  busy.value=true;error.value='';notice.value=''
  try {
    const result=await resolveFeedback(id,{status,resolution:status==='resolved'?resolution.value:''})
    if(!alive || current!==scope) return
    detail.value={...detail.value,feedback:result};resolution.value=result.resolution;notice.value=status==='resolved'?'反馈已处理。':'反馈已重新打开。'
  } catch(cause) {if(alive && current===scope) {
    if(cause instanceof ApiError && [401,403,404].includes(cause.status)) {detail.value=null;resolution.value='';scope++}
    error.value=errorMessage(cause)
  }}
  finally {if(alive && current===scope) busy.value=false}
}
</script>
<template>
  <header class="page-heading"><p class="eyebrow">服务反馈</p><h1>反馈详情</h1><p><RouterLink to="/admin/feedback">返回反馈列表</RouterLink></p></header>
  <p v-if="error" role="alert" class="error">{{ error }}</p><button v-if="error && !detail" type="button" :disabled="loading" @click="refresh++">重试加载</button><p v-if="notice" role="status" class="success">{{ notice }}</p>
  <section v-if="loading" class="panel">正在加载反馈…</section>
  <template v-else-if="detail">
    <section class="panel detail"><h2>{{ detail.feedback.rating==='up'?'有帮助':'没帮助' }} · {{ detail.feedback.status==='open'?'待处理':'已处理' }}</h2>
      <p><strong>用户说明</strong></p><p class="body">{{ detail.feedback.comment || '未填写说明' }}</p>
      <p v-if="detail.feedback.resolution"><strong>处理说明</strong></p><p v-if="detail.feedback.resolution" class="body">{{ detail.feedback.resolution }}</p>
      <p class="muted">提交于 {{ new Date(detail.feedback.created_at).toLocaleString() }}</p>
    </section>
    <section class="panel"><h2>原回答</h2><p v-if="!detail.message_available || !detail.message" class="muted">原回答不可查看。</p><template v-else><p class="body">{{ detail.message.content }}</p><p v-if="detail.message.evidence_hidden" class="muted">回答引用当前不可访问。</p></template></section>
    <section class="panel"><h2>处理反馈</h2><label class="resolve-label">处理说明<textarea v-model="resolution" aria-label="处理说明" maxlength="2000" rows="3" :disabled="busy" /></label><div class="actions"><button v-if="detail.feedback.status==='open'" type="button" aria-label="标记已处理" :disabled="busy || !resolution.trim()" @click="update('resolved')">标记已处理</button><button v-else type="button" aria-label="重新打开反馈" :disabled="busy" @click="update('open')">重新打开</button></div></section>
  </template>
</template>
<style scoped>
.detail,.panel{min-width:0;overflow-wrap:anywhere}.body{white-space:pre-wrap;overflow-wrap:anywhere}.resolve-label{display:grid;gap:6px}.resolve-label textarea{width:100%;box-sizing:border-box;font:inherit;border:1px solid #b7c6cf;border-radius:6px;padding:8px;resize:vertical}.actions{margin-top:12px}.actions button{font:inherit;border:1px solid #7c9da5;background:#f0f9f8;border-radius:6px;padding:8px 14px}.actions button:disabled{opacity:.5}
</style>
