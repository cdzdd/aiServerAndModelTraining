<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElButton } from 'element-plus'
import { session } from '../auth/session'
import { ApiError, errorMessage } from '../../shared/api/errors'
import { getConversation, listMessages, postText, type ConversationView, type MessageView } from '../chat/api'
import MessageList from '../chat/MessageList.vue'
import CitationPanel from '../chat/CitationPanel.vue'
import type { Citation } from '../chat/stream'
import { closeHandoff, getHandoff, type HandoffView } from './api'

const route=useRoute(),id=computed(()=>typeof route.params.handoffId==='string'?route.params.handoffId:null)
const transfer=ref<HandoffView|null>(null),conversation=ref<ConversationView|null>(null),messages=ref<MessageView[]>([]),messagePage=ref(1)
const citations=ref<Citation[]|null>(null),draft=ref(''),error=ref(''),loading=ref(false),sending=ref(false),closing=ref(false),olderLoading=ref(false)
let version=0,scopeVersion=0,olderExpanded=false,timer:ReturnType<typeof setTimeout>|undefined
const canReply=computed(()=>transfer.value?.state==='human' && session.state.user?.role==='agent' && transfer.value.assigned_agent_id===session.state.user.id)
const canClose=computed(()=>transfer.value?.state==='human' && (session.state.user?.role==='admin' || canReply.value))
function clear() {version++;scopeVersion++;olderExpanded=false;clearTimeout(timer);transfer.value=null;conversation.value=null;messages.value=[];citations.value=null;loading.value=false;sending.value=false;closing.value=false}
async function load() {
  const selected=id.value
  if(!selected) return
  const current=++version
  clearTimeout(timer);loading.value=!transfer.value
  try {
    const handoff=await getHandoff(selected)
    const [chat,first]=await Promise.all([getConversation(handoff.conversation_id),listMessages(handoff.conversation_id)])
    const lastPage=Math.max(1,Math.ceil(first.total/first.page_size))
    const start=olderExpanded && transfer.value?.id===selected?Math.min(messagePage.value,lastPage):lastPage
    const pages=await Promise.all(Array.from({length:lastPage-start+1},(_,index)=>{
      const target=start+index
      return target===1?Promise.resolve(first):listMessages(handoff.conversation_id,target)
    }))
    if(current!==version) return
    transfer.value=handoff;conversation.value=chat;messages.value=pages.flatMap(page=>page.items).filter((value,index,all)=>all.findIndex(item=>item.id===value.id)===index);messagePage.value=start;citations.value=null
    if(handoff.state==='human' && !sending.value && !closing.value && session.state.user) timer=setTimeout(()=>{void load()},3000)
  } catch(cause) {
    if(current!==version) return
    error.value=errorMessage(cause)
    if(cause instanceof ApiError && (cause.status===403 || cause.status===404)) {clear();error.value='该会话不可访问。'}
  } finally {if(current===version)loading.value=false}
}
async function older() {
  const cid=transfer.value?.conversation_id,target=messagePage.value-1,current=version
  if(!cid || target<1 || olderLoading.value) return
  olderLoading.value=true
  try {const result=await listMessages(cid,target);if(current===version) {const seen=new Set(messages.value.map(item=>item.id));messages.value=[...result.items.filter(item=>!seen.has(item.id)),...messages.value];messagePage.value=target;olderExpanded=true}}
  catch(cause){if(current===version)error.value=errorMessage(cause)}
  finally {olderLoading.value=false}
}
async function reply() {
  const handoffId=id.value,cid=transfer.value?.conversation_id,content=draft.value.trim(),actor=session.state.user?.id,scope=scopeVersion
  if(!cid || !canReply.value || sending.value) return
  if(!content || content.length>2000) {error.value='消息需为 1–2000 个字符。';return}
  const current=++version
  sending.value=true;error.value='';clearTimeout(timer)
  try {await postText(cid,content,crypto.randomUUID());if(current!==version || scope!==scopeVersion || id.value!==handoffId || session.state.user?.id!==actor) return;draft.value='';await load()}
  catch(cause){if(current===version)error.value=errorMessage(cause)}
  finally {if(scope===scopeVersion && id.value===handoffId && session.state.user?.id===actor) {sending.value=false;if(transfer.value?.state==='human') {clearTimeout(timer);timer=setTimeout(()=>{void load()},3000)}}}
}
async function close() {
  if(!id.value || !canClose.value || closing.value) return
  const handoffId=id.value,actor=session.state.user?.id,scope=scopeVersion,current=++version
  closing.value=true;error.value='';clearTimeout(timer)
  try {await closeHandoff(handoffId);if(current===version && scope===scopeVersion && id.value===handoffId && session.state.user?.id===actor) await load()}
  catch(cause){if(current===version)error.value=errorMessage(cause)}
  finally {if(scope===scopeVersion && id.value===handoffId && session.state.user?.id===actor) {closing.value=false;if(transfer.value?.state==='human') {clearTimeout(timer);timer=setTimeout(()=>{void load()},3000)}}}
}
watch(id,()=>{clear();error.value='';draft.value='';void load()},{immediate:true})
watch(()=>[session.state.user?.id,session.state.user?.role],clear)
onUnmounted(clear)
</script>
<template>
  <header class="page-heading"><p class="eyebrow">客户服务</p><h1>会话工作台</h1></header>
  <p v-if="error" role="alert" class="error">{{ error }}</p>
  <section class="panel" aria-label="人工会话">
    <p v-if="loading" role="status">正在加载会话…</p>
    <template v-else-if="transfer && conversation">
      <div class="heading"><h2>{{ conversation.title }}</h2><span class="status-tag">{{ transfer.state==='human'?'人工处理中':transfer.state==='closed'?'已关闭':'等待客服' }}</span></div>
      <div class="actions"><ElButton @click="load">刷新会话</ElButton><ElButton v-if="messagePage>1" :disabled="olderLoading" @click="older">加载更早消息</ElButton><ElButton v-if="canClose" :disabled="closing" @click="close">{{ closing?'关闭中…':'关闭会话' }}</ElButton></div>
      <MessageList :messages="messages" @citations="citations=$event" />
      <CitationPanel v-if="citations" :items="citations" @close="citations=null" />
      <form v-if="canReply" class="composer" @submit.prevent="reply"><label for="agent-reply">回复内容</label><textarea id="agent-reply" v-model="draft" aria-label="回复内容" maxlength="2000" rows="4" :disabled="sending" /><div class="actions"><ElButton type="primary" native-type="submit" :disabled="sending">发送回复</ElButton></div></form>
      <p v-else-if="transfer.state==='closed'" class="muted">会话已关闭，仅可阅读历史。</p>
    </template>
    <p v-else class="muted">当前无可查看的会话。</p>
  </section>
</template>
<style scoped>
.heading{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.heading h2{margin:0;overflow-wrap:anywhere}.composer{margin-top:22px;border-top:1px solid #dce5e9;padding-top:16px}.composer textarea{width:100%;padding:10px;border:1px solid #b7c6cf;border-radius:7px;font:inherit;resize:vertical}.actions{flex-wrap:wrap}.actions .el-button{margin:0}
</style>
