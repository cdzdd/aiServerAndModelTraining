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
const stateLabels={queued:'等待客服',human:'人工处理中',closed:'已关闭'}
const sources=computed(()=>{
  const visible=messages.value.filter(message=>!message.evidence_hidden).flatMap(message=>message.citations)
  return [...new Map(visible.map(source=>[source.chunk_id,source])).values()]
})
const timeFormat=new Intl.DateTimeFormat('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})
const formatTime=(value:string)=>timeFormat.format(new Date(value))
</script>
<template>
  <section class="handoff-page" aria-label="人工会话">
    <header class="bar"><RouterLink to="/handoffs">人工客服</RouterLink><span aria-hidden="true">/</span><h1>会话工作台</h1><ElButton @click="load">刷新会话</ElButton></header>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="loading" role="status" class="notice">正在加载会话…</p>
    <div v-else-if="transfer && conversation" class="handoff-grid">
      <div class="thread">
        <header class="topic"><div class="meta"><code>#{{ transfer.id.slice(0,8) }}</code><span class="badge" :class="{live:transfer.state==='human'}">{{ stateLabels[transfer.state] }}</span></div>
          <h2>{{ conversation.title }}</h2>
        </header>
        <ElButton v-if="messagePage>1" :disabled="olderLoading" @click="older">加载更早消息</ElButton>
        <MessageList :messages="messages" @citations="citations=$event" />
        <CitationPanel v-if="citations" :items="citations" @close="citations=null" />
        <form v-if="canReply" class="composer" @submit.prevent="reply">
          <label class="sr-only" for="agent-reply">回复内容</label>
          <textarea id="agent-reply" v-model="draft" aria-label="回复内容" placeholder="输入回复…" maxlength="2000" rows="2" :disabled="sending" />
          <div class="composer-foot"><span>以客服身份回复</span><ElButton type="primary" native-type="submit" :disabled="sending">发送回复</ElButton></div>
        </form>
        <p v-else-if="transfer.state==='closed'" class="muted">会话已关闭，仅可阅读历史。</p>
      </div>
      <aside class="details" aria-label="会话信息"><h3>会话信息</h3>
        <dl><dt>申请时间</dt><dd>{{ formatTime(transfer.requested_at) }}</dd>
          <template v-if="transfer.claimed_at"><dt>接入时间</dt><dd>{{ formatTime(transfer.claimed_at) }}</dd></template>
          <template v-if="transfer.closed_at"><dt>结束时间</dt><dd>{{ formatTime(transfer.closed_at) }}</dd></template>
        </dl>
        <section v-if="sources.length"><h3>本次引用</h3><button v-for="source in sources" :key="source.chunk_id" class="source" @click="citations=[source]">{{ source.title }}</button></section>
        <ElButton v-if="canClose" :disabled="closing" @click="close">{{ closing?'关闭中…':'关闭会话' }}</ElButton>
      </aside>
    </div>
    <p v-else class="notice">当前无可查看的会话。</p>
  </section>
</template>
<style scoped>
.bar {display:flex;align-items:center;gap:12px;min-height:56px;padding:8px 24px;border-bottom:1px solid #e6e6e4;font-size:13px}
.bar a{color:#656561;text-decoration:none}.bar span{color:#aaaba7}.bar h1{font-size:14px;letter-spacing:0;margin:0;font-weight:550}.bar .el-button{margin-left:auto;border:none}
.notice{padding:0 24px}.handoff-grid{display:grid;grid-template-columns:minmax(0,1fr) clamp(195px,17vw,260px);min-height:calc(100dvh - 56px)}
.thread{display:flex;flex-direction:column;gap:18px;min-width:0;padding:32px clamp(20px,4.5vw,80px) 26px}
.topic{border-bottom:1px solid #e7e7e5;padding-bottom:18px}.meta{display:flex;align-items:center;gap:12px;color:#70706c;font-size:12px}
.topic h2{font-size:clamp(22px,2.05vw,28px);font-weight:500;letter-spacing:-.035em;line-height:1.4;margin:10px 0 0;overflow-wrap:anywhere}
.badge{border-radius:99px;background:#f3f3f1;padding:2px 8px;font-size:11px}.badge.live{background:#eff6ef;color:#395e42}.badge.live::before{content:'●';font-size:8px;margin-right:5px}
.details{padding:28px 20px;border-left:1px solid #e7e7e5}.details h3{font-size:14px;font-weight:600;margin:0 0 16px}.details dl{display:grid;grid-template-columns:auto 1fr;gap:10px;font-size:12px;border-bottom:1px solid #e6e6e4;padding-bottom:20px;margin:0 0 20px}.details dt,.composer-foot span{color:#6c6c68}.details dd{margin:0;text-align:right}.details .el-button{width:100%}.details section{margin-bottom:20px}.source{display:block;border:0;background:none;text-align:left;text-decoration:underline;cursor:pointer;padding:5px 0}
.thread :deep(.message-list){gap:20px}.thread :deep(.message){border:0;background:none;padding:0;max-width:94%}.thread :deep(.message.user){justify-self:end}.thread :deep(.message-heading){justify-content:flex-start;gap:10px;align-items:baseline;flex-direction:row;font-size:12px}.thread :deep(.user .message-heading){justify-content:flex-end}.thread :deep(.message-heading small){color:#777773;font-size:11px}.thread :deep(.message-content){margin:6px 0;font-size:14px;line-height:1.8}.thread :deep(.user .message-content){background:#f3f3f1;border-radius:14px 4px 14px 14px;padding:9px 14px}
.composer{margin-top:auto;border:1px solid #d4d4d0;border-radius:15px;padding:12px 14px;box-shadow:0 3px 12px #00000006}.composer:focus-within{border-color:#888}.composer textarea{width:100%;resize:vertical;border:0;background:none;font:inherit;outline:none}.composer-foot{display:flex;align-items:center;justify-content:space-between;font-size:12px}
@media(max-width:900px){.handoff-grid{display:flex;flex-direction:column}.thread{flex:1}.details{border-left:0;border-top:1px solid #e7e7e5;padding:16px 20px}.details dl{display:flex;flex-wrap:wrap}.details .el-button{width:auto}}
</style>
