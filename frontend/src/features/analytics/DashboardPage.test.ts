import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { init } from 'echarts/core'
import { session, type User } from '../auth/session'
import { ApiError } from '../../shared/api/errors'
import DashboardPage from './DashboardPage.vue'
import { getStats, type StatsView } from './api'

vi.mock('./api',async()=>({...await vi.importActual<typeof import('./api')>('./api'),getStats:vi.fn()}))
vi.mock('echarts/core',()=>({init:vi.fn(()=>({setOption:vi.fn(),dispose:vi.fn(),resize:vi.fn()})),use:vi.fn()}))
enableAutoUnmount(afterEach)
afterEach(()=>vi.unstubAllGlobals())
beforeEach(()=>vi.clearAllMocks())
const ratio=(numerator:number,denominator:number,value:number|null)=>({numerator,denominator,value})
const token=(value:number|null,known_sum:number,known_count:number,missing_count:number,coverage:number|null)=>({value,known_sum,known_count,missing_count,coverage})
const stats:StatsView={
  range:{from:'2026-09-23T16:00:00Z',to:'2026-09-25T16:00:00Z',timezone:'Asia/Shanghai'},as_of:'2026-09-26T02:00:00Z',
  logins:{successful:2},
  generations:{accepted:14,distinct_users:3,complete:10,failed:2,cancelled:1,generating:1,answered:7,clarify:1,no_answer:2,unclassified_complete:0,no_answer_ratio:ratio(2,10,.2)},
  latency:{average_ms:800,sample_count:9,missing_count:1},
  tokens:{terminal_count:13,pending_count:1,prompt_tokens:token(null,1200,12,1,12/13),completion_tokens:token(260,260,13,0,1),total_tokens:token(null,1430,11,2,11/13),cost:{amount:null,status:'unknown',reason:'缺少逐请求模型价格归属及完整用量，无法计算费用'}},
  handoffs:{period:{requested:2,claimed:3,closed:1},current:{queued:1,human:2}},
  feedback:{total:4,up:3,down:1,open:1,resolved:3,satisfaction:ratio(3,4,.75)},
  ingestion:{period_jobs:{parse:{queued:1,running:1,succeeded:3,failed:1},index:{queued:0,running:1,succeeded:4,failed:2}},current_documents:{uploaded:1,processing:1,parsed:2,ready:3,failed:1,disabled:1,deleted:2}},
  daily:[{date:'2026-09-24',accepted:7,complete:5,failed:1,cancelled:1,generating:0,no_answer:1},{date:'2026-09-25',accepted:7,complete:5,failed:1,cancelled:0,generating:1,no_answer:1}],
  popular_questions:[{preview:'<script>私密问题</script>',count:1,truncated:false}],
}

it('shows the full fixed cohort with server ratios, current inventory, partial tokens and safe questions',async()=>{
  vi.mocked(getStats).mockResolvedValue(stats)
  const wrapper=mount(DashboardPage)
  await flushPromises()
  const text=wrapper.text()
  for(const label of ['成功登录次数','已受理问答请求','独立提问用户','无答案比例','完成回复平均耗时','费用未知','当前状态','区间内记录的当前结果','Asia/Shanghai']) expect(text).toContain(label)
  expect(text).toContain('20%')
  expect(text).toContain('75%')
  expect(text).toContain('已知部分')
  expect(text).toContain('<script>私密问题</script>')
  expect(wrapper.find('script').exists()).toBe(false)
  expect(text).not.toContain('NaN')
  expect(getStats).toHaveBeenCalledWith(undefined,undefined)
})

it('sends inclusive Shanghai business dates as half-open midnight instants',async()=>{
  vi.mocked(getStats).mockResolvedValue(stats)
  const wrapper=mount(DashboardPage)
  await flushPromises()
  await wrapper.get('input[aria-label="开始日期"]').setValue('2026-09-24')
  await wrapper.get('input[aria-label="结束日期"]').setValue('2026-09-25')
  await wrapper.get('button[aria-label="应用日期"]').trigger('click')
  await flushPromises()
  expect(getStats).toHaveBeenLastCalledWith('2026-09-24T00:00:00+08:00','2026-09-26T00:00:00+08:00')
})

it('renders empty ratios and missing usage as no data instead of zero or NaN',async()=>{
  vi.mocked(getStats).mockResolvedValue({...stats,generations:{...stats.generations,no_answer_ratio:ratio(0,0,null)},latency:{average_ms:null,sample_count:0,missing_count:0},tokens:{...stats.tokens,terminal_count:0,pending_count:0,prompt_tokens:token(null,0,0,0,null),completion_tokens:token(null,0,0,0,null),total_tokens:token(null,0,0,0,null)},feedback:{...stats.feedback,satisfaction:ratio(0,0,null)},daily:[],popular_questions:[]})
  const wrapper=mount(DashboardPage)
  await flushPromises()
  expect(wrapper.text()).toContain('暂无数据')
  expect(wrapper.text()).not.toContain('NaN')
  expect(wrapper.text()).toContain('费用未知')
})

it('disposes both charts and resizes them with the window',async()=>{
  vi.mocked(getStats).mockResolvedValue(stats)
  const wrapper=mount(DashboardPage)
  await flushPromises()
  expect(init).toHaveBeenCalledTimes(2)
  const charts=vi.mocked(init).mock.results.map(result=>result.value)
  expect(charts[0].setOption.mock.calls[0][0].legend.top).toBe(0)
  window.dispatchEvent(new Event('resize'))
  for(const chart of charts) expect(chart.resize).toHaveBeenCalled()
  wrapper.unmount()
  for(const chart of charts) expect(chart.dispose).toHaveBeenCalled()
})

it('clears privileged stats on same-ID role loss and ignores a late response',async()=>{
  const admin:User={id:'admin',username:'admin',display_name:'admin',role:'admin',is_active:true,created_at:''}
  vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({user:admin,csrf_token:'test'})))
  await session.login({username:'admin',password:'test'})
  vi.mocked(getStats).mockResolvedValueOnce(stats)
  const wrapper=mount(DashboardPage)
  await flushPromises()
  let finish!: (result:StatsView)=>void
  vi.mocked(getStats).mockReturnValueOnce(new Promise(done=>{finish=done}))
  await wrapper.get('input[aria-label="开始日期"]').setValue('2026-09-24')
  await wrapper.get('input[aria-label="结束日期"]').setValue('2026-09-25')
  await wrapper.get('button[aria-label="应用日期"]').trigger('click')
  session.acceptUserUpdate({...admin,role:'user'})
  finish(stats)
  await flushPromises()
  expect(wrapper.text()).not.toContain('成功登录次数')
})

it('retries the last applied Shanghai range after a network failure',async()=>{
  vi.mocked(getStats).mockResolvedValueOnce(stats).mockRejectedValueOnce(new ApiError(0,'NETWORK_ERROR','网络错误')).mockResolvedValueOnce(stats)
  const wrapper=mount(DashboardPage)
  await flushPromises()
  await wrapper.get('input[aria-label="开始日期"]').setValue('2026-09-24')
  await wrapper.get('input[aria-label="结束日期"]').setValue('2026-09-25')
  await wrapper.get('button[aria-label="应用日期"]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('网络错误')
  await wrapper.findAll('button').find(button=>button.text()==='重试统计')!.trigger('click')
  await flushPromises()
  expect(getStats).toHaveBeenLastCalledWith('2026-09-24T00:00:00+08:00','2026-09-26T00:00:00+08:00')
})

it('labels a zero-filled empty cohort and does not draw a proportional pie',async()=>{
  vi.mocked(getStats).mockResolvedValue({...stats,generations:{...stats.generations,accepted:0,distinct_users:0,complete:0,failed:0,cancelled:0,generating:0,answered:0,clarify:0,no_answer:0,no_answer_ratio:ratio(0,0,null)},daily:stats.daily.map(day=>({...day,accepted:0,complete:0,failed:0,cancelled:0,generating:0,no_answer:0}))})
  const wrapper=mount(DashboardPage)
  await flushPromises()
  expect(wrapper.text()).toContain('所选范围暂无问答')
  expect(init).not.toHaveBeenCalled()
})
