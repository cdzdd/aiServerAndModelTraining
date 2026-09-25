<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElButton } from 'element-plus'
import { session } from '../auth/session'
import { errorMessage } from '../../shared/api/errors'
import { disableFaq, getKnowledge, indexLabel, listFaqs, saveFaq, type Faq, type KnowledgeBase, type Members } from './api'
import FaqEditor from './FaqEditor.vue'
import MemberEditor from './MemberEditor.vue'
const route=useRoute(),admin=computed(()=>session.state.user?.role==='admin')
const kb=ref<KnowledgeBase|null>(null),faqs=ref<Faq[]>([]),page=ref(1),total=ref(0),loading=ref(false),saving=ref(false)
const error=ref(''),message=ref(''),editing=ref(false),selected=ref<Faq|undefined>(),membersOpen=ref(false)
let generation=0
async function load(target=1) {
  const current=++generation,id=String(route.params.id)
  loading.value=true;error.value='';kb.value=null;faqs.value=[];editing.value=false;membersOpen.value=false
  try {
    const [base,items]=await Promise.all([getKnowledge(id),listFaqs(id,target)])
    if(current!==generation) return
    kb.value=base;faqs.value=items.items;page.value=items.page;total.value=items.total
  } catch(cause){if(current===generation) error.value=errorMessage(cause)}
  finally {if(current===generation) loading.value=false}
}
function edit(faq?:Faq) {selected.value=faq;editing.value=true;membersOpen.value=false;message.value=''}
async function saved() {saving.value=false;message.value='FAQ 已保存，索引状态以当前版本为准。';await load(page.value)}
function membersSaved(result:Members) {if(kb.value)kb.value.version=result.version;saving.value=false;membersOpen.value=false;message.value='成员已更新。'}
async function toggle(faq:Faq) {
  if(saving.value) return
  const current=generation
  saving.value=true;error.value=''
  try {
    if(faq.is_active) await disableFaq(faq.id)
    else await saveFaq(faq.kb_id,{question:faq.question,answer:faq.answer,is_active:true},faq)
    if(current===generation) await load(page.value)
  } catch(cause){if(current===generation)error.value=errorMessage(cause)}
  finally {saving.value=false}
}
watch(()=>route.params.id,()=>{message.value='';saving.value=false;void load()},{immediate:true})
</script>
<template>
  <RouterLink to="/knowledge">← 知识库列表</RouterLink>
  <p v-if="loading" role="status">正在加载知识库…</p>
  <p v-if="error" role="alert" class="error">{{ error }}</p>
  <ElButton v-if="error" :disabled="saving || loading" @click="load(page)">重新加载</ElButton>
  <p v-if="message" role="status" class="success">{{ message }}</p>
  <template v-if="kb">
    <header class="page-heading"><p class="eyebrow">{{ kb.visibility==='public'?'所有登录用户可读':'仅授权成员可读' }}</p><h1>{{ kb.name }}</h1><p class="muted">{{ kb.description }}</p></header>
    <div v-if="admin" class="actions"><ElButton type="primary" :disabled="saving" @click="edit()">新增 FAQ</ElButton><ElButton :disabled="saving" @click="membersOpen=true;editing=false">管理成员</ElButton><ElButton :disabled="saving" @click="load(page)">刷新内容</ElButton></div>
    <FaqEditor v-if="admin && editing" :key="selected?.id ?? 'new'" :kb-id="kb.id" :faq="selected" @saving="saving=$event" @saved="saved" @cancel="editing=false" />
    <MemberEditor v-if="admin && membersOpen" :key="kb.id" :kb-id="kb.id" @saving="saving=$event" @saved="membersSaved" @cancel="membersOpen=false" />
    <section class="faq-list" aria-label="常见问题">
      <p v-if="!faqs.length" class="panel">暂无常见问题。</p>
      <article v-for="faq in faqs" :key="faq.id" class="panel faq-card">
        <div class="faq-heading"><h2>{{ faq.question }}</h2><span class="status-tag">{{ indexLabel(faq) }}</span></div>
        <p class="answer">{{ faq.answer }}</p><small>版本 {{ faq.version }} · {{ new Date(faq.updated_at).toLocaleString() }}</small>
        <div v-if="admin" class="actions"><ElButton :disabled="saving" @click="edit(faq)">编辑 FAQ</ElButton><ElButton :disabled="saving || editing" @click="toggle(faq)">{{ faq.is_active?'停用 FAQ':'启用 FAQ' }}</ElButton></div>
      </article>
    </section>
    <nav v-if="total>20" class="pagination" aria-label="FAQ 分页"><ElButton :disabled="saving || page===1" @click="load(page-1)">上一页 FAQ</ElButton><span>第 {{ page }} 页 · 共 {{ total }} 条</span><ElButton :disabled="saving || page*20>=total" @click="load(page+1)">下一页 FAQ</ElButton></nav>
  </template>
</template>
<style scoped>
.page-heading{margin-top:26px;overflow-wrap:anywhere}.faq-list{margin-top:24px}.faq-card{margin:16px 0}.faq-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.faq-heading h2{overflow-wrap:anywhere;min-width:0}.status-tag{flex-shrink:0}.answer{white-space:pre-wrap;overflow-wrap:anywhere}
@media(max-width:500px){.faq-heading{flex-direction:column}}
</style>
