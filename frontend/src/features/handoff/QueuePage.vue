<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElButton } from 'element-plus'
import { session } from '../auth/session'
import { ApiError, errorMessage } from '../../shared/api/errors'
import { claimHandoff, listQueue, type QueueItem } from './api'

const router=useRouter(),items=ref<QueueItem[]>([]),page=ref(1),total=ref(0),loading=ref(false),claiming=ref<string|null>(null),error=ref('')
let version=0,scope=0,alive=true
async function load(target=1) {
  const current=++version
  loading.value=true
  try {const result=await listQueue(target);if(alive && current===version) {items.value=result.items;page.value=result.page;total.value=result.total}}
  catch(cause){if(alive && current===version)error.value=errorMessage(cause)}
  finally {if(alive && current===version)loading.value=false}
}
async function claim(id:string) {
  if(claiming.value) return
  const current=scope,actor=session.state.user?.id,role=session.state.user?.role
  const valid=()=>alive && current===scope && session.state.user?.id===actor && session.state.user?.role===role
  claiming.value=id;error.value=''
  try {await claimHandoff(id);if(valid()) await router.push('/handoffs/'+id)}
  catch(cause) {
    if(!valid()) return
    if(cause instanceof ApiError && cause.status===409) {await load(page.value);if(valid()) error.value='该会话已被领取，队列已刷新。'}
    else error.value=errorMessage(cause)
  } finally {if(valid()) claiming.value=null}
}
watch(()=>[session.state.user?.id,session.state.user?.role],()=>{version++;scope++;items.value=[];claiming.value=null})
onMounted(()=>{void load()})
onUnmounted(()=>{alive=false;version++;scope++})
</script>
<template>
  <header class="page-heading"><p class="eyebrow">客户服务</p><h1>待接单队列</h1><p class="muted">仅显示排队时间。接单后才能查看会话内容。</p></header>
  <p v-if="error" role="alert" class="error">{{ error }}</p>
  <section class="panel" aria-label="待接单队列">
    <div class="actions"><ElButton :disabled="loading" @click="load(page)">刷新队列</ElButton></div>
    <p v-if="loading" role="status">正在加载队列…</p>
    <p v-else-if="!items.length" class="muted">暂无待接单会话。</p>
    <ol v-else class="queue-list"><li v-for="item in items" :key="item.id"><span>申请时间：{{ new Date(item.requested_at).toLocaleString() }}</span><span>待接单</span><ElButton v-if="session.state.user?.role==='agent'" :disabled="claiming!==null" @click="claim(item.id)">接单</ElButton></li></ol>
    <nav v-if="total>20" class="pagination" aria-label="队列分页"><ElButton :disabled="loading || page===1" @click="load(page-1)">上一页</ElButton><span>第 {{ page }} 页</span><ElButton :disabled="loading || page*20>=total" @click="load(page+1)">下一页</ElButton></nav>
  </section>
</template>
<style scoped>
.queue-list{list-style:none;margin:16px 0;padding:0}.queue-list li{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:12px 0;border-bottom:1px solid #dce5e9}.queue-list li span:first-child{margin-right:auto}
</style>
