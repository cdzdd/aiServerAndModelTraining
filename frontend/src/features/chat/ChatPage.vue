<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElButton } from 'element-plus'
import { session } from '../auth/session'
import { ApiError, errorMessage } from '../../shared/api/errors'
import { createConversation, deleteConversation, getConversation, getModelStatus, listAvailableKnowledge, listConversations, listMessages, postText, streamQuestion, type ConversationView, type MessageView, type ModelStatus } from './api'
import { decodeChatEvents, type Citation, type ProgressStage } from './stream'
import { requestHandoff } from '../handoff/api'
import ConversationList from './ConversationList.vue'
import MessageList from './MessageList.vue'
import CitationPanel from './CitationPanel.vue'

const route=useRoute(),router=useRouter()
const selectedId=computed(()=>typeof route.params.id==='string'?route.params.id:null)
const conversations=ref<ConversationView[]>([]),conversationPage=ref(1),conversationTotal=ref(0),conversationsLoading=ref(false)
const conversation=ref<ConversationView|null>(null),messages=ref<MessageView[]>([]),messagePage=ref(1),messagesLoading=ref(false),olderLoading=ref(false)
const error=ref(''),notice=ref(''),draft=ref(''),sending=ref(false),lastFailed=ref<string|null>(null),citations=ref<Citation[]|null>(null)
const creating=ref(false),newOpen=ref(false),available=ref<{id:string;name:string}[]>([]),kbPage=ref(1),kbTotal=ref(0),kbLoading=ref(false),selectedKbs=ref<string[]>([])
const handoffBusy=ref(false)
const progress=ref<{messageId:string;stage:ProgressStage}|null>(null)
const modelStatus=ref<ModelStatus|null>(null),modelStatusLoading=ref(false)
let modelStatusVersion=0
let listVersion=0,detailVersion=0,knowledgeVersion=0,streamVersion=0,handoffScope=0,instanceActive=true,olderExpanded=false,activeStream:AbortController|null=null,historyTimer:ReturnType<typeof setTimeout>|undefined
const userId=computed(()=>session.state.user?.id ?? '')
const canSend=computed(()=>{
  const item=conversation.value,user=session.state.user
  if(!item || !user || item.mode==='closed') return false
  if(item.mode==='bot' || item.mode==='queued') return item.user_id===user.id
  return item.user_id===user.id || (user.role==='agent' && item.assigned_agent_id===user.id)
})
const modelStatusLabel=computed(()=>{
  if(modelStatusLoading.value && !modelStatus.value) return '正在检查模型状态…'
  const status=modelStatus.value
  if(!status) return '暂时无法确认模型状态'
  if(status.provider!=='queued') {
    return ({mock:'已配置演示模型',ollama:'已配置本地模型',cloud:'已配置云端模型'} as Record<string,string>)[status.provider] ?? '已配置模型服务'
  }
  return {ready:'本地模型已连接',busy:'本地模型忙碌',offline:'本地模型未连接'}[status.state]
})
const retryableMessageIds=computed(()=>{
  if(conversation.value?.mode!=='bot' || conversation.value.user_id!==userId.value || sending.value) return []
  return messages.value.filter(item=>item.role==='assistant' && ['failed','cancelled'].includes(item.status)
    && messages.value.some(question=>question.id===item.in_reply_to_id && question.role==='user' && question.author_id===userId.value))
    .map(item=>item.id)
})
async function loadModelStatus() {
  if(modelStatusLoading.value || !session.state.user) return
  const current=++modelStatusVersion
  modelStatusLoading.value=true
  try {
    const result=await getModelStatus()
    if(instanceActive && current===modelStatusVersion) modelStatus.value=result
  } catch {
    if(instanceActive && current===modelStatusVersion) modelStatus.value=null
  } finally {
    if(instanceActive && current===modelStatusVersion) modelStatusLoading.value=false
  }
}
async function retryMessage(messageId:string) {
  if(!retryableMessageIds.value.includes(messageId)) return
  const answer=messages.value.find(item=>item.id===messageId)
  const question=messages.value.find(item=>item.id===answer?.in_reply_to_id)
  if(question) await send(question.content)
}
function stop() {activeStream?.abort()}
function cancelStream() {streamVersion++;stop();activeStream=null;sending.value=false;progress.value=null}
async function loadConversations(target=1) {
  const current=++listVersion
  conversationsLoading.value=true
  try {
    const result=await listConversations(target)
    if(current!==listVersion) return
    conversations.value=result.items;conversationPage.value=result.page;conversationTotal.value=result.total
  } catch(cause) {if(current===listVersion)error.value=errorMessage(cause)}
  finally {if(current===listVersion)conversationsLoading.value=false}
}
async function loadSelected(id:string|null) {
  const current=++detailVersion
  clearTimeout(historyTimer)
  if(!id) {conversation.value=null;messages.value=[];return}
  messagesLoading.value=!conversation.value
  try {
    const [item,first]=await Promise.all([getConversation(id),listMessages(id)])
    const lastPage=Math.max(1,Math.ceil(first.total/first.page_size))
    const start=olderExpanded && conversation.value?.id===id?Math.min(messagePage.value,lastPage):lastPage
    const pages=await Promise.all(Array.from({length:lastPage-start+1},(_,index)=>{
      const target=start+index
      return target===1?Promise.resolve(first):listMessages(id,target)
    }))
    if(current!==detailVersion) return
    conversation.value=item;messages.value=pages.flatMap(page=>page.items).filter((value,index,all)=>all.findIndex(item=>item.id===value.id)===index);messagePage.value=start;citations.value=null
    if(!sending.value) {
      const delay=messages.value.some(value=>value.status==='generating')?2000:item.mode==='queued' || item.mode==='human'?3000:0
      if(delay) historyTimer=setTimeout(()=>{if(selectedId.value===id && session.state.user)void loadSelected(id)},delay)
    }
  } catch(cause) {if(current===detailVersion) {error.value=errorMessage(cause);if(cause instanceof ApiError && (cause.status===403 || cause.status===404)) {conversation.value=null;messages.value=[];citations.value=null}}}
  finally {if(current===detailVersion)messagesLoading.value=false}
}
async function older() {
  const id=selectedId.value,target=messagePage.value-1,current=detailVersion
  if(!id || target<1 || olderLoading.value) return
  olderLoading.value=true
  try {const result=await listMessages(id,target);if(current===detailVersion) {const seen=new Set(messages.value.map(value=>value.id));messages.value=[...result.items.filter(value=>!seen.has(value.id)),...messages.value];messagePage.value=target;olderExpanded=true}}
  catch(cause){if(current===detailVersion)error.value=errorMessage(cause)}
  finally {olderLoading.value=false}
}
async function loadKnowledge(target=1) {
  const current=++knowledgeVersion
  kbLoading.value=true;error.value=''
  try {const result=await listAvailableKnowledge(target);if(current===knowledgeVersion) {available.value=result.items;kbPage.value=result.page;kbTotal.value=result.total}}
  catch(cause){if(current===knowledgeVersion)error.value=errorMessage(cause)}
  finally {if(current===knowledgeVersion)kbLoading.value=false}
}
function openNew() {newOpen.value=true;selectedKbs.value=[];void loadKnowledge(1)}
async function create() {
  if(creating.value) return
  if(!selectedKbs.value.length || selectedKbs.value.length>50) {error.value='请选择 1–50 个知识库。';return}
  creating.value=true;error.value=''
  try {const item=await createConversation(selectedKbs.value);newOpen.value=false;await loadConversations(1);await router.push('/chat/'+item.id)}
  catch(cause){error.value=errorMessage(cause)}
  finally {creating.value=false}
}
async function remove(id:string) {
  const item=conversations.value.find(value=>value.id===id)
  if(!window.confirm('确定删除会话“'+(item?.title ?? '')+'”？')) return
  error.value=''
  try {await deleteConversation(id);if(selectedId.value===id) {cancelStream();await router.push('/chat')}await loadConversations(1)}
  catch(cause){error.value=errorMessage(cause)}
}
function optimistic(id:string,role:'user'|'assistant',content:string,status:MessageView['status']):MessageView {
  return {id,conversation_id:selectedId.value!,role,author_id:role==='user'?userId.value:null,content,status,citations:[],client_message_id:null,in_reply_to_id:null,answer_status:null,evidence_level:null,intent:null,latency_ms:null,error_code:null,created_at:new Date().toISOString(),evidence_hidden:false}
}
async function handoff() {
  const item=conversation.value,id=selectedId.value
  if(!item || !id || item.mode!=='bot' || item.user_id!==userId.value || handoffBusy.value) return
  const owner=userId.value,scope=handoffScope
  const valid=()=>instanceActive && scope===handoffScope && selectedId.value===id && userId.value===owner
  handoffBusy.value=true;error.value=''
  try {
    await requestHandoff(id)
    if(!valid()) return
    cancelStream()
    await loadSelected(id)
    if(valid()) await loadConversations(conversationPage.value)
  } catch(cause) {if(valid()) error.value=errorMessage(cause)}
  finally {if(valid()) handoffBusy.value=false}
}
async function send(again?:string) {
  const item=conversation.value,id=selectedId.value
  if(!item || !id || !canSend.value || sending.value) return
  const content=(again ?? draft.value).trim()
  if(!content || content.length>2000) {error.value='消息需为 1–2000 个字符。';return}
  const key=crypto.randomUUID(),current=++streamVersion
  clearTimeout(historyTimer)
  if(item.mode==='bot' && (!again || draft.value.trim()===content)) draft.value=''
  lastFailed.value=null;error.value='';notice.value='';sending.value=true
  let assistantId:string|null=null
  try {
    if(item.mode==='bot') {
      const controller=new AbortController()
      activeStream=controller
      let done=false
      for await(const event of decodeChatEvents(streamQuestion(id,content,key,controller.signal))) {
        if(current!==streamVersion) return
        if(event.type==='meta') {
          assistantId=event.assistant_message_id
          messages.value=[...messages.value,optimistic(event.user_message_id,'user',content,'complete'),optimistic(assistantId,'assistant','','generating')]
          progress.value={messageId:assistantId,stage:'preparing'}
        } else if(event.type==='progress' && assistantId) {
          progress.value={messageId:assistantId,stage:event.stage}
        } else if(event.type==='delta' && assistantId) {
          messages.value=messages.value.map(value=>value.id===assistantId?{...value,content:value.content+event.text}:value)
        } else if(event.type==='citations' && assistantId) {
          messages.value=messages.value.map(value=>value.id===assistantId?{...value,citations:event.items}:value)
        } else if(event.type==='done' && assistantId) {
          done=true
          messages.value=messages.value.map(value=>value.id===assistantId?{...value,status:'complete' as const,answer_status:event.answer_status,evidence_level:event.evidence_level,intent:event.intent}:value)
        } else if(event.type==='error') throw new ApiError(0,event.code,event.message)
      }
      if(!done) throw new ApiError(0,'STREAM_PROTOCOL','回答流中断，请刷新历史后重试。')
    } else {
      const saved=await postText(id,content,key)
      if(current===streamVersion) {messages.value=[...messages.value,saved];draft.value=''}
    }
  } catch(cause) {
    if(current===streamVersion) {
      lastFailed.value=content
      error.value=cause instanceof ApiError && cause.code==='CANCELLED'?'已停止生成；可手动重试。':errorMessage(cause)
      if(item.mode==='bot' && !draft.value) draft.value=content
      if(assistantId) {
        const code=cause instanceof ApiError?cause.code:'GENERATION_FAILED'
        messages.value=messages.value.map(value=>value.id===assistantId?{...value,status:code==='CANCELLED'?'cancelled':'failed',error_code:code}:value)
      }
    }
  } finally {
    if(current===streamVersion) {activeStream=null;sending.value=false;progress.value=null;await loadSelected(id);await loadConversations(conversationPage.value);void loadModelStatus()}
  }
}
watch(selectedId,id=>{handoffScope++;handoffBusy.value=false;cancelStream();clearTimeout(historyTimer);olderExpanded=false;conversation.value=null;messages.value=[];citations.value=null;error.value='';notice.value='';lastFailed.value=null;void loadSelected(id)},{immediate:true})
watch(()=>[session.state.user?.id,session.state.user?.role],()=>{handoffScope++;handoffBusy.value=false;cancelStream();clearTimeout(historyTimer);detailVersion++;conversation.value=null;messages.value=[];citations.value=null;modelStatusVersion++;modelStatus.value=null;modelStatusLoading.value=false;void loadModelStatus()})
onMounted(()=>{void loadConversations();void loadModelStatus()})
onUnmounted(()=>{instanceActive=false;handoffScope++;cancelStream();clearTimeout(historyTimer);listVersion++;detailVersion++;knowledgeVersion++;modelStatusVersion++})
</script>
<template>
  <header class="page-heading"><p class="eyebrow">知识与服务</p><h1>问答与会话</h1><p class="muted">选择可访问的知识库发起会话。回答、来源和历史以当前权限为准。</p></header>
  <div class="model-status" aria-label="模型服务状态">
    <span role="status">{{ modelStatusLabel }}</span>
    <ElButton aria-label="刷新模型状态" :disabled="modelStatusLoading" @click="loadModelStatus">刷新模型状态</ElButton>
    <small v-if="modelStatus?.provider==='queued' && modelStatus.state==='offline'">知识提问可能暂时无法生成，仍可查看历史或申请人工客服。</small>
  </div>
  <p v-if="error" role="alert" class="error">{{ error }}</p>
  <p v-if="notice" role="status" class="success">{{ notice }}</p>
  <div v-if="session.state.user" class="chat-layout">
    <div>
      <ConversationList :items="conversations" :selected-id="selectedId" :user-id="userId" :role="session.state.user.role" :page="conversationPage" :total="conversationTotal" :loading="conversationsLoading" @select="router.push('/chat/'+$event)" @create="openNew" @delete="remove" @page="loadConversations" />
      <section v-if="newOpen" class="panel new-conversation" aria-label="新建会话"><h2>选择知识库</h2><p class="muted">只显示当前可访问的知识库，可跨页选择。</p>
        <p v-if="kbLoading" role="status">正在加载知识库…</p><p v-else-if="!available.length">暂无可用知识库。</p>
        <form @submit.prevent="create"><fieldset :disabled="creating">
          <label v-for="kb in available" :key="kb.id" class="checkbox"><input v-model="selectedKbs" type="checkbox" :value="kb.id" :aria-label="kb.name">{{ kb.name }}</label>
          <nav v-if="kbTotal>20" class="pagination" aria-label="知识库选择分页"><ElButton :disabled="kbLoading || kbPage===1" @click="loadKnowledge(kbPage-1)">上一页知识库</ElButton><span>第 {{ kbPage }} 页</span><ElButton :disabled="kbLoading || kbPage*20>=kbTotal" @click="loadKnowledge(kbPage+1)">下一页知识库</ElButton></nav>
          <div class="actions"><ElButton type="primary" native-type="submit" :disabled="creating || kbLoading">创建会话</ElButton><ElButton :disabled="creating" @click="newOpen=false">取消</ElButton></div>
        </fieldset></form>
      </section>
    </div>
    <section class="chat-main panel" aria-label="当前会话">
      <p v-if="messagesLoading" role="status">正在加载历史…</p>
      <template v-else-if="conversation">
        <div class="chat-heading"><h2>{{ conversation.title }}</h2><span class="status-tag">{{ conversation.mode==='bot'?'智能问答':conversation.mode==='queued'?'等待客服':conversation.mode==='human'?'人工处理中':'已关闭' }}</span></div>
        <p v-if="conversation.mode==='queued'" class="muted">消息将作为待处理留言保存。</p>
        <p v-if="conversation.mode==='closed'" class="muted">会话已关闭，仅可阅读历史。</p>
        <div class="actions"><ElButton :disabled="messagesLoading" @click="loadSelected(selectedId)">刷新历史</ElButton><ElButton v-if="messagePage>1" :disabled="olderLoading" @click="older">加载更早消息</ElButton><ElButton v-if="conversation.mode==='bot' && conversation.user_id===userId" :disabled="handoffBusy" @click="handoff">{{ handoffBusy?'申请中…':'申请人工客服' }}</ElButton></div>
        <MessageList :can-feedback="conversation?.user_id===userId" :messages="messages" :progress="progress" :retryable-message-ids="retryableMessageIds" @citations="citations=$event" @retry="retryMessage" />
        <CitationPanel v-if="citations" :items="citations" @close="citations=null" />
        <form v-if="canSend" class="composer" @submit.prevent="send()"><label class="sr-only" for="chat-message">消息内容</label><textarea id="chat-message" v-model="draft" aria-label="消息内容" :placeholder="conversation.mode==='bot'?'输入你的问题…':'输入留言…'" maxlength="2000" rows="2" :disabled="sending" />
          <div class="actions"><ElButton type="primary" native-type="submit" :disabled="sending">{{ conversation.mode==='bot'?'发送问题':'发送留言' }}</ElButton><ElButton v-if="sending && conversation.mode==='bot'" @click="stop">停止生成</ElButton><ElButton v-if="lastFailed && !sending && conversation.mode==='bot'" @click="send(lastFailed)">重试提问</ElButton></div>
        </form>
        <p v-else-if="conversation.mode!=='closed'" class="muted">当前账号可阅读此会话，无法代替会话所有者发送消息。</p>
      </template>
      <p v-else class="muted">选择会话，或新建会话开始提问。</p>
    </section>
  </div>
</template>
<style scoped>
.model-status { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; margin: -6px 0 20px; color: var(--muted); font-size: 12px; }
.model-status small { flex-basis: 100%; margin: 0; }
.chat-layout { display: grid; grid-template-columns: minmax(195px, 24%) minmax(0,1fr); align-items: start; gap: clamp(16px,2vw,30px); }
.chat-main { display: flex; flex-direction: column; gap: 15px; min-height: 52vh; min-width: 0; border: 0; border-left: 1px solid var(--line); border-radius: 0; padding: 2px 0 4px clamp(16px,2vw,30px); }
.chat-main > .muted { margin: 0; }
.chat-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.chat-heading h2 { margin: 0; font-size: 20px; font-weight: 500; }
.status-tag { flex-shrink: 0; }
.chat-main > .actions { margin: 0; padding-bottom: 14px; border-bottom: 1px solid var(--line); }
.composer { margin-top: auto; padding: 12px 14px; border: 1px solid var(--edge); border-radius: 15px; }
.composer:focus-within { border-color: #848480; }
.composer textarea { display: block; padding: 0; border: 0; outline: 0; }
.composer .actions { justify-content: flex-end; margin-top: 6px; }
.new-conversation { margin-top: 12px; padding: 14px; }
.new-conversation .checkbox { margin: 9px 0; overflow-wrap: anywhere; }
@media (max-width:760px) { .chat-layout { grid-template-columns: minmax(0,1fr); } .chat-main { border: 0; padding: 6px 0; } }
</style>
