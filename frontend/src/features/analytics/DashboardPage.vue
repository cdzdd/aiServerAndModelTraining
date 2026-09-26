<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from 'vue'
import { init, use, type ECharts } from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { session } from '../auth/session'
import { ApiError, errorMessage } from '../../shared/api/errors'
import { getStats, shanghaiRange, shanghaiTime, type Ratio, type StatsView, type TokenField } from './api'

use([LineChart,PieChart,GridComponent,LegendComponent,TooltipComponent,CanvasRenderer])
const stats=ref<StatsView|null>(null),loading=ref(false),error=ref(''),start=ref(''),end=ref('')
const applied=ref<{from?:string;to?:string}>({})
const trendElement=ref<HTMLElement|null>(null),statusElement=ref<HTMLElement|null>(null)
let trendChart:ECharts|null=null,statusChart:ECharts|null=null,observer:ResizeObserver|null=null
let scope=0,alive=true
const percent=(ratio:Ratio)=>ratio.value===null?'暂无数据':(Math.round(ratio.value*1000)/10)+'%'
const coverage=(field:TokenField)=>field.coverage===null?'暂无数据':(Math.round(field.coverage*1000)/10)+'%'
const number=(value:number)=>value.toLocaleString('zh-CN')
function tokenText(field:TokenField,terminal:number) {
  if(!terminal) return '暂无数据'
  return field.value===null?`已知部分 ${number(field.known_sum)}；缺失 ${field.missing_count} 条；覆盖 ${coverage(field)}`:`${number(field.value)}；覆盖 ${coverage(field)}`
}
function clearCharts() {observer?.disconnect();observer=null;trendChart?.dispose();statusChart?.dispose();trendChart=null;statusChart=null}
function resizeCharts() {trendChart?.resize();statusChart?.resize()}
async function draw(data:StatsView) {
  await nextTick()
  if(!alive || stats.value!==data || !trendElement.value || !statusElement.value) return
  if(!data.generations.accepted) return
  if(!trendChart) trendChart=init(trendElement.value)
  if(!statusChart) statusChart=init(statusElement.value)
  const metrics=[['受理','accepted'],['完成','complete'],['失败','failed'],['取消','cancelled'],['生成中','generating'],['无答案','no_answer']] as const
  trendChart.setOption({tooltip:{trigger:'axis',renderMode:'richText'},legend:{type:'scroll',top:0,left:10,right:10},grid:{left:40,right:18,bottom:36,top:52},xAxis:{type:'category',data:data.daily.map(day=>day.date)},yAxis:{type:'value',min:0,minInterval:1},series:metrics.map(([name,key])=>({name,type:'line',data:data.daily.map(day=>day[key]),smooth:false}))},true)
  statusChart.setOption({tooltip:{trigger:'item',renderMode:'richText'},legend:{bottom:0},series:[{type:'pie',radius:['42%','68%'],data:[{name:'完成',value:data.generations.complete},{name:'失败',value:data.generations.failed},{name:'取消',value:data.generations.cancelled},{name:'生成中',value:data.generations.generating}]}]},true)
  observer?.disconnect()
  if(typeof ResizeObserver!=='undefined') {observer=new ResizeObserver(resizeCharts);observer.observe(trendElement.value);observer.observe(statusElement.value)}
}
onUnmounted(()=>{alive=false;scope++;window.removeEventListener('resize',resizeCharts);clearCharts()})
window.addEventListener('resize',resizeCharts)
async function load(from?:string,to?:string) {
  const current=++scope
  applied.value={from,to}
  loading.value=true;stats.value=null;error.value='';clearCharts()
  try {
    const result=await getStats(from,to)
    if(!alive || current!==scope) return
    stats.value=result
  } catch(cause) {if(alive && current===scope) {
    if(cause instanceof ApiError && [401,403,404].includes(cause.status)) stats.value=null
    error.value=errorMessage(cause)
  }} finally {if(alive && current===scope) loading.value=false}
  if(alive && current===scope && stats.value) void draw(stats.value)
}
function apply() {
  const range=shanghaiRange(start.value,end.value)
  if(!range) {error.value='请选择有效的开始和结束日期。';return}
  void load(range.from,range.to)
}
function reset() {start.value='';end.value='';void load()}
watch(()=>[session.state.user?.id,session.state.user?.role],(value,oldValue)=>{
  if(oldValue && (value[0]!==oldValue[0] || value[1]!==oldValue[1]) && session.state.user?.role!=='admin') {scope++;stats.value=null;loading.value=false;error.value='';clearCharts();return}
  void load()
},{immediate:true})
</script>
<template>
  <header class="page-heading"><p class="eyebrow">服务观察</p><h1>管理统计</h1><p class="muted">业务日期按 Asia/Shanghai 计算；已受理问答请求不是模型调用次数。</p></header>
  <section class="panel"><div class="filters"><label>开始日期<input v-model="start" type="date" aria-label="开始日期" /></label><label>结束日期<input v-model="end" type="date" aria-label="结束日期" /></label><button type="button" aria-label="应用日期" :disabled="loading" @click="apply">应用日期</button><button type="button" :disabled="loading" @click="reset">最近30天</button></div><p class="muted">所选结束日期包含整天；查询范围右边界为次日零点（不含）。</p></section>
  <p v-if="error" role="alert" class="error">{{ error }}</p><button v-if="error" type="button" :disabled="loading" @click="load(applied.from,applied.to)">重试统计</button>
  <p v-if="loading" role="status">正在加载统计…</p>
  <template v-if="stats && !loading">
    <p class="muted">范围：{{ shanghaiTime(stats.range.from) }} 至 {{ shanghaiTime(stats.range.to) }}（右边界不含） · {{ stats.range.timezone }}</p>
    <h2>区间内记录的当前结果（截至 {{ shanghaiTime(stats.as_of) }}）</h2>
    <section class="metric-grid" aria-label="问答与登录指标">
      <div class="metric"><span>成功登录次数</span><strong>{{ number(stats.logins.successful) }}</strong></div>
      <div class="metric"><span>已受理问答请求</span><strong>{{ number(stats.generations.accepted) }}</strong></div>
      <div class="metric"><span>独立提问用户</span><strong>{{ number(stats.generations.distinct_users) }}</strong></div>
      <div class="metric"><span>已完成回复</span><strong>{{ number(stats.generations.complete) }}</strong></div>
      <div class="metric"><span>失败</span><strong>{{ number(stats.generations.failed) }}</strong></div>
      <div class="metric"><span>已取消</span><strong>{{ number(stats.generations.cancelled) }}</strong></div>
      <div class="metric"><span>生成中</span><strong>{{ number(stats.generations.generating) }}</strong></div>
    </section>
    <section class="panel"><h3>回答结果</h3><div class="metric-grid"><div class="metric"><span>已回答</span><strong>{{ stats.generations.answered }}</strong></div><div class="metric"><span>待澄清</span><strong>{{ stats.generations.clarify }}</strong></div><div class="metric"><span>无答案</span><strong>{{ stats.generations.no_answer }}</strong></div><div class="metric"><span>未分类完成</span><strong>{{ stats.generations.unclassified_complete }}</strong></div><div class="metric"><span>无答案比例</span><strong>{{ percent(stats.generations.no_answer_ratio) }}</strong><small>{{ stats.generations.no_answer_ratio.numerator }}/{{ stats.generations.no_answer_ratio.denominator }} 条已分类完成回复</small></div><div class="metric"><span>完成回复平均耗时</span><strong>{{ stats.latency.average_ms===null?'暂无数据':number(stats.latency.average_ms)+' ms' }}</strong><small>已知 {{ stats.latency.sample_count }} · 缺失 {{ stats.latency.missing_count }}</small></div></div><p class="muted">回答分类不含失败、取消和生成中。</p></section>
    <section class="charts"><div class="panel"><h3>每日问答趋势</h3><p v-if="!stats.generations.accepted">所选范围暂无问答。</p><div v-else ref="trendElement" class="chart" role="img" :aria-label="'每日趋势，共'+stats.daily.length+'天'" /><p class="muted">按上海日期统计已受理请求与当前结果。</p></div><div class="panel"><h3>回复状态分布</h3><p v-if="!stats.generations.accepted">所选范围暂无问答。</p><div v-else ref="statusElement" class="chart" role="img" aria-label="完成、失败、取消、生成中状态分布" /><p class="muted">完成 {{ stats.generations.complete }} · 失败 {{ stats.generations.failed }} · 取消 {{ stats.generations.cancelled }} · 生成中 {{ stats.generations.generating }}</p></div></section>
    <section class="panel"><h3>Token 与费用</h3><p class="muted">终态 {{ stats.tokens.terminal_count }} 条 · 待完成 {{ stats.tokens.pending_count }} 条</p><dl class="token-list"><div><dt>输入 Token</dt><dd>{{ tokenText(stats.tokens.prompt_tokens,stats.tokens.terminal_count) }}</dd></div><div><dt>输出 Token</dt><dd>{{ tokenText(stats.tokens.completion_tokens,stats.tokens.terminal_count) }}</dd></div><div><dt>合计 Token</dt><dd>{{ tokenText(stats.tokens.total_tokens,stats.tokens.terminal_count) }}</dd></div></dl><p><strong>费用未知</strong>：{{ stats.tokens.cost.reason }}</p></section>
    <section class="two-columns"><div class="panel"><h3>人工接管（区间事件）</h3><p>申请 {{ stats.handoffs.period.requested }} · 接单 {{ stats.handoffs.period.claimed }} · 关闭 {{ stats.handoffs.period.closed }}</p><p class="muted">分别按各动作发生时间统计，不代表同一批工单的漏斗。</p></div><div class="panel"><h3>回答反馈（区间内创建，当前状态）</h3><p>评价 {{ stats.feedback.total }} · 有帮助 {{ stats.feedback.up }} · 没帮助 {{ stats.feedback.down }}</p><p>待处理 {{ stats.feedback.open }} · 已处理 {{ stats.feedback.resolved }}</p><p>满意度 {{ percent(stats.feedback.satisfaction) }}（{{ stats.feedback.satisfaction.numerator }}/{{ stats.feedback.satisfaction.denominator }}）</p></div></section>
    <section class="panel"><h3>入库任务（区间内创建，当前状态）</h3><div class="table-scroll"><table><thead><tr><th>任务</th><th>排队</th><th>运行</th><th>成功</th><th>失败</th></tr></thead><tbody><tr><th>解析</th><td>{{ stats.ingestion.period_jobs.parse.queued }}</td><td>{{ stats.ingestion.period_jobs.parse.running }}</td><td>{{ stats.ingestion.period_jobs.parse.succeeded }}</td><td>{{ stats.ingestion.period_jobs.parse.failed }}</td></tr><tr><th>索引</th><td>{{ stats.ingestion.period_jobs.index.queued }}</td><td>{{ stats.ingestion.period_jobs.index.running }}</td><td>{{ stats.ingestion.period_jobs.index.succeeded }}</td><td>{{ stats.ingestion.period_jobs.index.failed }}</td></tr></tbody></table></div><p class="muted">同一任务重试不重复计数。</p></section>
    <section class="panel"><h3>当前状态（不受所选日期限制）</h3><p>待接 {{ stats.handoffs.current.queued }} · 人工处理中 {{ stats.handoffs.current.human }}</p><p>文档：已上传 {{ stats.ingestion.current_documents.uploaded }} · 处理中 {{ stats.ingestion.current_documents.processing }} · 解析完成 {{ stats.ingestion.current_documents.parsed }} · 可检索 {{ stats.ingestion.current_documents.ready }} · 失败 {{ stats.ingestion.current_documents.failed }} · 停用 {{ stats.ingestion.current_documents.disabled }} · 已删除 {{ stats.ingestion.current_documents.deleted }}</p></section>
    <section class="panel"><h3>热门问题</h3><p class="muted">展示有记录的原问题；已删除会话的问题文本不展示，数值统计仍保留。</p><p v-if="!stats.popular_questions.length">暂无问题</p><ol v-else class="questions"><li v-for="(item,index) in stats.popular_questions" :key="index"><span>{{ item.preview }}{{ item.truncated?'…':'' }}</span><strong>{{ item.count }} 次</strong></li></ol></section>
  </template>
</template>
<style scoped>
.filters{display:flex;flex-wrap:wrap;gap:12px;align-items:end}.filters label{display:grid;gap:4px}.filters input,.filters button{font:inherit;border:1px solid #b7c6cf;border-radius:6px;padding:8px;background:#fff}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}.metric{background:#fff;border:1px solid #dce5e9;border-radius:12px;padding:14px;display:grid;gap:6px;min-width:0}.metric span,.metric small,.muted{color:#647887}.metric strong{font-size:1.35rem;overflow-wrap:anywhere}.charts,.two-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.charts .panel,.two-columns .panel{min-width:0}.chart{height:290px;width:100%;min-width:0}.token-list{display:grid;gap:8px}.token-list div{display:flex;justify-content:space-between;gap:16px;border-bottom:1px solid #e7edf1;padding:6px 0}.token-list dd{margin:0;text-align:right;overflow-wrap:anywhere}.questions{padding-left:24px}.questions li{display:flex;justify-content:space-between;gap:12px;overflow-wrap:anywhere;border-bottom:1px solid #e7edf1;padding:8px 0}@media(max-width:760px){.charts,.two-columns{grid-template-columns:1fr}.token-list div{display:block}.token-list dd{text-align:left}.chart{height:250px}}
</style>
