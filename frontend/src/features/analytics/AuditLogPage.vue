<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { session } from '../auth/session'
import { ApiError, errorMessage } from '../../shared/api/errors'
import { getAuditEvent, listAuditEvents, shanghaiRange, shanghaiTime, type AuditEventView, type AuditFilters } from './api'

const items=ref<AuditEventView[]>([]),total=ref(0),page=ref(1),loading=ref(false),detailLoading=ref(false)
const retryPage=ref(1)
const error=ref(''),detailError=ref(''),detail=ref<AuditEventView|null>(null)
const start=ref(''),end=ref(''),action=ref(''),outcome=ref(''),actorId=ref(''),targetType=ref(''),targetId=ref('')
const applied=ref<Omit<AuditFilters,'page'>>({})
let scope=0,detailScope=0,alive=true
onUnmounted(()=>{alive=false;scope++;detailScope++})
function clear() {items.value=[];total.value=0;detail.value=null;detailScope++;detailLoading.value=false}
async function load(target=page.value) {
  const current=++scope
  retryPage.value=target
  loading.value=true;error.value='';clear()
  try {
    const result=await listAuditEvents({page:target,...applied.value})
    if(!alive || current!==scope) return
    items.value=result.items;total.value=result.total;page.value=result.page
  } catch(cause) {if(alive && current===scope) {
    if(cause instanceof ApiError && [401,403,404].includes(cause.status)) clear()
    error.value=errorMessage(cause)
  }} finally {if(alive && current===scope) loading.value=false}
}
function query() {
  let range:ReturnType<typeof shanghaiRange>|null=null
  if(start.value || end.value) {
    range=shanghaiRange(start.value,end.value)
    if(!range) {error.value='请选择有效的开始和结束日期。';return}
  }
  applied.value={...(range??{}),action:action.value||undefined,outcome:outcome.value||undefined,actor_id:actorId.value||undefined,target_type:targetType.value||undefined,target_id:targetId.value||undefined}
  void load(1)
}
async function open(item:AuditEventView) {
  const current=++detailScope
  detailLoading.value=true;detail.value=null;detailError.value=''
  try {
    const result=await getAuditEvent(item.id)
    if(!alive || current!==detailScope) return
    detail.value=result
  } catch(cause) {if(alive && current===detailScope) {
    if(cause instanceof ApiError && [401,403,404].includes(cause.status)) {clear();scope++}
    detailError.value=errorMessage(cause)
  }} finally {if(alive && current===detailScope) detailLoading.value=false}
}
function metadataText(value:unknown) {return Array.isArray(value)?value.join('、'):typeof value==='object'&&value!==null?JSON.stringify(value):String(value)}
watch(()=>[session.state.user?.id,session.state.user?.role],(value,oldValue)=>{
  if(oldValue && (value[0]!==oldValue[0] || value[1]!==oldValue[1]) && session.state.user?.role!=='admin') {scope++;clear();loading.value=false;error.value='';detailError.value='';return}
  void load(1)
},{immediate:true})
</script>
<template>
  <header class="page-heading"><p class="eyebrow">管理与追溯</p><h1>审计记录</h1><p class="muted">仅展示允许的事件摘要与元数据。日期按 Asia/Shanghai 计算，结束日期含整天。</p></header>
  <section class="panel filters"><div class="filter-grid">
    <label>开始日期<input v-model="start" type="date" aria-label="审计开始日期" /></label><label>结束日期<input v-model="end" type="date" aria-label="审计结束日期" /></label>
    <label>动作<input v-model.trim="action" aria-label="动作筛选" maxlength="100" placeholder="例如 feedback.resolve" /></label><label>结果<input v-model.trim="outcome" aria-label="结果筛选" maxlength="30" placeholder="success" /></label>
    <label>操作者 ID<input v-model.trim="actorId" aria-label="操作者筛选" placeholder="UUID" /></label><label>资源类型<input v-model.trim="targetType" aria-label="资源类型筛选" maxlength="50" /></label><label>资源 ID<input v-model.trim="targetId" aria-label="资源ID筛选" placeholder="UUID" /></label>
  </div><button type="button" aria-label="查询审计" :disabled="loading" @click="query">查询审计</button></section>
  <p v-if="error" role="alert" class="error">{{ error }}</p><button v-if="error" type="button" aria-label="重试审计" :disabled="loading" @click="load(retryPage)">重试审计</button>
  <p v-if="loading" role="status">正在加载审计记录…</p>
  <section v-else class="panel"><p v-if="!items.length && !error">暂无审计记录。</p><div v-else-if="items.length" class="table-scroll"><table><caption class="sr-only">审计记录列表</caption><thead><tr><th>时间</th><th>事件</th><th>结果</th><th>操作者</th><th>资源</th><th>详情</th></tr></thead><tbody><tr v-for="item in items" :key="item.id"><td>{{ shanghaiTime(item.created_at) }}</td><td><strong>{{ item.summary }}</strong><small>{{ item.action }}</small></td><td>{{ item.outcome }}</td><td>{{ item.actor_id ?? '系统' }}</td><td>{{ item.target_type }} {{ item.target_id ?? '' }}</td><td><button type="button" aria-label="查看审计详情" @click="open(item)">查看详情</button></td></tr></tbody></table></div><nav v-if="total>20" class="pagination" aria-label="审计分页"><button :disabled="loading || page===1" @click="load(page-1)">上一页</button><span>第 {{ page }} 页 · 共 {{ total }} 条</span><button :disabled="loading || page*20>=total" @click="load(page+1)">下一页</button></nav></section>
  <p v-if="detailError" role="alert" class="error">{{ detailError }}</p><p v-if="detailLoading">正在加载详情…</p>
  <section v-if="detail" class="panel detail" aria-label="审计详情"><div class="detail-heading"><h2>{{ detail.summary }}</h2><button @click="detail=null">关闭详情</button></div><dl><div><dt>动作</dt><dd>{{ detail.action }}</dd></div><div><dt>时间</dt><dd>{{ shanghaiTime(detail.created_at) }}</dd></div><div><dt>结果</dt><dd>{{ detail.outcome }}</dd></div><div><dt>操作者</dt><dd>{{ detail.actor_id ?? '系统' }}</dd></div><div><dt>资源</dt><dd>{{ detail.target_type }} {{ detail.target_id ?? '' }}</dd></div><div><dt>请求 ID</dt><dd>{{ detail.request_id ?? '无' }}</dd></div><div v-for="(value,key) in detail.metadata" :key="key"><dt>{{ key }}</dt><dd>{{ metadataText(value) }}</dd></div></dl></section>
</template>
<style scoped>
.filters{display:grid;gap:14px}.filter-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.filter-grid label{display:grid;gap:5px;min-width:0}.filter-grid input,.filters button,.detail button,td button{font:inherit;border:1px solid #b7c6cf;border-radius:6px;padding:8px;background:#fff;min-width:0}.filters button{justify-self:start}td{overflow-wrap:anywhere;max-width:250px}td small{display:block;color:#647887}.detail{min-width:0;overflow-wrap:anywhere}.detail-heading{display:flex;justify-content:space-between;gap:12px}.detail dl>div{display:flex;gap:14px;border-bottom:1px solid #e7edf1;padding:8px 0}.detail dt{font-weight:600;min-width:90px}.detail dd{margin:0;overflow-wrap:anywhere}@media(max-width:680px){table,tbody,tr,td{display:block}thead{display:none}tr{padding:12px 0;border-bottom:1px solid #e7edf1}td{border:0;padding:5px 8px}.detail dl>div{display:block}}
</style>
