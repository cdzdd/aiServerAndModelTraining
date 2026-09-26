<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { session } from '../auth/session'
import { ApiError, errorMessage } from '../../shared/api/errors'
import { listFeedback, type FeedbackView } from './api'

const items=ref<FeedbackView[]>([]),total=ref(0),page=ref(1)
const status=ref(''),rating=ref(''),loading=ref(false),error=ref('')
let scope=0,alive=true
onUnmounted(()=>{alive=false;scope++})
async function load(target=page.value) {
  const current=++scope
  loading.value=true;error.value=''
  try {
    const result=await listFeedback(target,status.value,rating.value)
    if(!alive || current!==scope) return
    items.value=result.items;total.value=result.total;page.value=result.page
  } catch(cause) {if(alive && current===scope) {
    if(cause instanceof ApiError && [401,403,404].includes(cause.status)) {items.value=[];total.value=0}
    error.value=errorMessage(cause)
  }}
  finally {if(alive && current===scope) loading.value=false}
}
watch(()=>[status.value,rating.value,session.state.user?.id,session.state.user?.role],(value,oldValue)=>{
  if(oldValue && (oldValue[2]!==value[2] || oldValue[3]!==value[3]) && session.state.user?.role!=='admin') {scope++;items.value=[];total.value=0;loading.value=false;error.value='';return}
  load(1)
},{immediate:true})
</script>
<template>
  <header class="page-heading"><p class="eyebrow">服务反馈</p><h1>反馈处理</h1><p class="muted">查看用户评价并记录处理结果。</p></header>
  <section class="panel">
    <div class="feedback-filters">
      <label>处理状态 <select v-model="status" aria-label="处理状态筛选"><option value="">全部</option><option value="open">待处理</option><option value="resolved">已处理</option></select></label>
      <label>评价 <select v-model="rating" aria-label="评价筛选"><option value="">全部</option><option value="up">有帮助</option><option value="down">没帮助</option></select></label>
      <button type="button" :disabled="loading" @click="load()">刷新列表</button>
    </div>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="loading" role="status">正在加载反馈…</p>
    <p v-else-if="!items.length && !error">暂无反馈。</p>
    <div v-else-if="items.length" class="table-scroll"><table><caption class="sr-only">用户反馈列表</caption><thead><tr><th>评价</th><th>说明</th><th>处理状态</th><th>时间</th><th>操作</th></tr></thead><tbody>
      <tr v-for="item in items" :key="item.id"><td>{{ item.rating==='up'?'有帮助':'没帮助' }}</td><td class="comment">{{ item.comment || '未填写说明' }}</td><td>{{ item.status==='open'?'待处理':'已处理' }}</td><td>{{ new Date(item.created_at).toLocaleString() }}</td><td><RouterLink :to="'/admin/feedback/'+item.id">查看详情</RouterLink></td></tr>
    </tbody></table></div>
    <nav v-if="total>20" class="pagination" aria-label="反馈分页"><button :disabled="loading || page===1" @click="load(page-1)">上一页</button><span>第 {{ page }} 页 · 共 {{ total }} 条</span><button :disabled="loading || page*20>=total" @click="load(page+1)">下一页</button></nav>
  </section>
</template>
<style scoped>
.feedback-filters{display:flex;flex-wrap:wrap;gap:12px;align-items:end;margin-bottom:16px}.feedback-filters label{display:grid;gap:4px}.feedback-filters select,.feedback-filters button,.pagination button{font:inherit;border:1px solid #b7c6cf;border-radius:6px;padding:7px 10px;background:#fff}.comment{max-width:400px;white-space:pre-wrap;overflow-wrap:anywhere}td{overflow-wrap:anywhere}@media(max-width:680px){table,tbody,tr,td{display:block}thead{display:none}tr{padding:12px 0;border-bottom:1px solid #e7edf1}td{border:0;padding:5px 8px}}
</style>
