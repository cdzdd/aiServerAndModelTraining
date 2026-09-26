<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElButton } from 'element-plus'
import { session } from '../auth/session'
import { ApiError, errorMessage } from '../../shared/api/errors'
import { createConversation, deleteConversation, getConversation, listAvailableKnowledge, listConversations, listMessages, postText, streamQuestion, type ConversationView, type MessageView } from './api'
import { decodeChatEvents, type Citation } from './stream'
import ConversationList from './ConversationList.vue'
import MessageList from './MessageList.vue'
import CitationPanel from './CitationPanel.vue'

const route=useRoute(),router=useRouter()
const selectedId=computed(()=>typeof route.params.id==='string'?route.params.id:null)
const conversations=ref<ConversationView[]>([]),conversationPage=ref(1),conversationTotal=ref(0),conversationsLoading=ref(false)
const conversation=ref<ConversationView|null>(null),messages=ref<MessageView[]>([]),messagePage=ref(1),messagesLoading=ref(false),olderLoading=ref(false)
const error=ref(''),notice=ref(''),draft=ref(''),sending=ref(false),lastFailed=ref<string|null>(null),citations=ref<Citation[]|null>(null)
const creating=ref(false),newOpen=ref(false),available=ref<{id:string;name:string}[]>([]),kbPage=ref(1),kbTotal=ref(0),kbLoading=ref(false),selectedKbs=ref<string[]>([])
let listVersion=0,detailVersion=0,knowledgeVersion=0,streamVersion=0,activeStream:AbortController|null=null,historyTimer:ReturnType<typeof setTimeout>|undefined
const userId=computed(()=>session.state.user?.id ?? '')
const canSend=computed(()=>{
  const item=conversation.value,user=session.state.user
  if(!item || !user || item.mode==='closed') return false
  if(item.mode==='bot' || item.mode==='queued') return item.user_id===user.id
  return item.user_id===user.id || (user.role==='agent' && item.assigned_agent_id===user.id)
})
function stop() {activeStream?.abort()}
function cancelStream() {streamVersion++;stop();activeStream=null;sending.value=false}
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
    const history=lastPage===1?first:await listMessages(id,lastPage)
    if(current!==detailVersion) return
    conversation.value=item;messages.value=history.items;messagePage.value=lastPage;citations.value=null
    if(!sending.value && messages.value.some(value=>value.status==='generating')) historyTimer=setTimeout(()=>{if(selectedId.value===id && session.state.user)void loadSelected(id)},2000)
  } catch(cause) {if(current===detailVersion)error.value=errorMessage(cause)}
  finally {if(current===detailVersion)messagesLoading.value=false}
}
async function older() {
  const id=selectedId.value,target=messagePage.value-1,current=detailVersion
  if(!id || target<1 || olderLoading.value) return
  olderLoading.value=true
  try {const result=await listMessages(id,target);if(current===detailVersion) {const seen=new Set(messages.value.map(value=>value.id));messages.value=[...result.items.filter(value=>!seen.has(value.id)),...messages.value];messagePage.value=target}}
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
async function send(again?:string) {
  const item=conversation.value,id=selectedId.value
  if(!item || !id || !canSend.value || sending.value) return
  const content=(again ?? draft.value).trim()
  if(!content || content.length>2000) {error.value='消息需为 1–2000 个字符。';return}
  const key=crypto.randomUUID(),current=++streamVersion
  clearTimeout(historyTimer)
  draft.value='';lastFailed.value=null;error.value='';notice.value='';sending.value=true
  try {
    if(item.mode==='bot') {
      const controller=new AbortController()
      activeStream=controller
      let assistantId:string|null=null,done=false
      for await(const event of decodeChatEvents(streamQuestion(id,content,key,controller.signal))) {
        if(current!==streamVersion) return
        if(event.type==='meta') {
          assistantId=event.assistant_message_id
          messages.value=[...messages.value,optimistic(event.user_message_id,'user',content,'complete'),optimistic(assistantId,'assistant','','generating')]
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
      if(current===streamVersion) messages.value=[...messages.value,saved]
    }
  } catch(cause) {
    if(current===streamVersion) {lastFailed.value=content;error.value=cause instanceof ApiError && cause.code==='CANCELLED'?'已停止生成；可手动重试。':errorMessage(cause)}
  } finally {
    if(current===streamVersion) {activeStream=null;sending.value=false;await loadSelected(id);await loadConversations(conversationPage.value)}
  }
}
watch(selectedId,id=>{cancelStream();clearTimeout(historyTimer);conversation.value=null;messages.value=[];citations.value=null;error.value='';notice.value='';lastFailed.value=null;void loadSelected(id)},{immediate:true})
watch(()=>[session.state.user?.id,session.state.user?.role],()=>{cancelStream();clearTimeout(historyTimer)})
onMounted(()=>{void loadConversations()})
onUnmounted(()=>{cancelStream();clearTimeout(historyTimer);listVersion++;detailVersion++;knowledgeVersion++})
</script>
<template>
  <header class="page-heading"><p class="eyebrow">知识与服务</p><h1>问答与会话</h1><p class="muted">选择可访问的知识库发起会话。回答、来源和历史以当前权限为准。</p></header>
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
        <div class="actions"><ElButton :disabled="messagesLoading" @click="loadSelected(selectedId)">刷新历史</ElButton><ElButton v-if="messagePage>1" :disabled="olderLoading" @click="older">加载更早消息</ElButton></div>
        <MessageList :can-feedback="conversation?.user_id===userId" :messages="messages" @citations="citations=$event" />
        <CitationPanel v-if="citations" :items="citations" @close="citations=null" />
        <form v-if="canSend" class="composer" @submit.prevent="send()"><label for="chat-message">消息内容</label><textarea id="chat-message" v-model="draft" aria-label="消息内容" maxlength="2000" rows="4" :disabled="sending" />
          <div class="actions"><ElButton type="primary" native-type="submit" :disabled="sending">{{ conversation.mode==='bot'?'发送问题':'发送留言' }}</ElButton><ElButton v-if="sending && conversation.mode==='bot'" @click="stop">停止生成</ElButton><ElButton v-if="lastFailed && !sending && conversation.mode==='bot'" @click="send(lastFailed)">重试提问</ElButton></div>
        </form>
        <p v-else-if="conversation.mode!=='closed'" class="muted">当前账号可阅读此会话，无法代替会话所有者发送消息。</p>
      </template>
      <p v-else class="muted">选择会话，或新建会话开始提问。</p>
    </section>
  </div>
</template>
<style scoped>
.page-heading{margin:20px 0}.chat-layout{display:grid;grid-template-columns:minmax(220px,300px) minmax(0,1fr);gap:18px;align-items:start}.chat-main{min-width:0}.chat-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.chat-heading h2{margin:0;overflow-wrap:anywhere}.status-tag{flex-shrink:0}.composer{margin-top:22px;border-top:1px solid #dce5e9;padding-top:16px}.composer textarea{width:100%;padding:10px;border:1px solid #b7c6cf;border-radius:7px;font:inherit;resize:vertical}.new-conversation{margin-top:12px}.new-conversation h2{margin-top:0}.new-conversation .checkbox{display:block;margin:8px 0;overflow-wrap:anywhere}.actions{flex-wrap:wrap}.actions .el-button{margin:0}
@media(max-width:760px){.chat-layout{grid-template-columns:minmax(0,1fr)}}
</style>
