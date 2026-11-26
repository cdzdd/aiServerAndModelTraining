<script setup lang="ts">
import { computed } from 'vue'
import { session } from '../features/auth/session'

const drawings = {
  book: 'M3 5q5-2 9 1 4-3 9-1v14q-5-2-9 1-4-3-9-1z M12 6v14',
  chat: 'M4 4h16v13H9l-5 4z M8 9h8m-8 4h5',
  source: 'M5 3h10l4 4v14H5z M14 3v5h5 M8 12h8m-8 4h5',
  inbox: 'M3 13l3-8h12l3 8v6H3z M3 13h5l2 3h4l2-3h5',
  headset: 'M4 14v-3a8 8 0 0 1 16 0v5q0 5-6 5h-2 M3 11h4v7H3z M17 11h4v7h-4z',
  check: 'M3 4h18v16H3z M7 12l3 3 7-7',
  users: 'M10 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M3 21v-2a7 7 0 0 1 14 0v2 M17 4q5 3 1 7m1 4q3 1 3 6',
} as const
type Step = { icon:keyof typeof drawings; title:string; detail:string; to:string }
type Guide = {
  home:string; role:string; intro:string; workflow:string; steps:Step[]
  example:string; question:string; response:string; outcome:string
  primary:[string,string]; more:[string,string][]
}
const guides: Record<'user'|'agent'|'admin',Guide> = {
  user: {
    home:'我的服务', role:'普通用户', intro:'从有权访问的资料中找答案，核对出处，或在原会话继续找人工帮助。',
    workflow:'从一个问题找到依据',
    steps:[
      {icon:'book',title:'选择知识库',detail:'先确认主题和资料范围，再从对应知识库开始提问。',to:'/knowledge'},
      {icon:'chat',title:'提问与追问',detail:'说清问题、现象和已尝试的步骤，历史会话可以继续打开。',to:'/chat'},
      {icon:'source',title:'核对回答',detail:'展开回答引用查看原文，也可以评价回答或申请转人工。',to:'/chat'},
    ],
    example:'图书已经归还，账户却仍显示在借',
    question:'我一次还了两本书，凭条只列了一本，接下来怎么办？',
    response:'先按条码逐本核对，保留还书日期、设备位置和凭条，再联系借阅服务台核实另一册的记录。',
    outcome:'参考资料 · 校园图书馆 / 自助还书后，账户里还显示在借怎么办？',
    primary:['开始提问 →','/chat'],more:[['浏览知识库与常见问题','/knowledge']],
  },
  agent: {
    home:'客服工作台',role:'客服',intro:'从队列领取人工请求，结合已授权资料答疑，在原会话跟进处理结果。',
    workflow:'跟进一次人工服务',
    steps:[
      {icon:'inbox',title:'查看排队',detail:'队列显示申请时间。选择待处理请求后接单。',to:'/handoffs'},
      {icon:'headset',title:'接手回复',detail:'接单后查看对话上下文，向用户确认已经尝试的步骤。',to:'/handoffs'},
      {icon:'check',title:'跟进与结单',detail:'从会话列表找回自己接的工单，确认问题解决后关闭。',to:'/chat'},
    ],
    example:'远端参会者听到回声',
    question:'同一会议室有三台电脑入会，我们都关了麦克风，怎么还有回声？',
    response:'请保留一台主设备负责收音和外放，另外两台退出会议音频。请远端说一句话，确认回声是否消失。',
    outcome:'处理依据 · 会议室支持 / 同一会议室多人入会时有回声，怎么处理？',
    primary:['查看待接单请求 →','/handoffs'],more:[['查看已接会话','/chat'],['查找答复依据','/knowledge']],
  },
  admin: {
    home:'管理概览',role:'管理员',intro:'维护账号与资料的访问范围，发布可检索的内容，通过反馈和运营记录复核服务质量。',
    workflow:'让一项新规则可查、可验',
    steps:[
      {icon:'users',title:'确认权限',detail:'在用户管理检查角色与启用状态，在知识库详情维护受限库成员。',to:'/admin/users'},
      {icon:'book',title:'发布资料',detail:'新增 FAQ 或上传文档，查看解析、索引状态，处理失败项。',to:'/knowledge'},
      {icon:'check',title:'复核质量',detail:'查看评价与原回答，记录处理说明，再用实际问题复测。',to:'/admin/feedback'},
    ],
    example:'新办事指南上传后，回答仍引用旧条件',
    question:'文件已经替换，怎样确认用户查到的是新规则？',
    response:'先核对新版本的索引状态，再选一个确实发生变化的条件开新会话提问，展开引用，对照新版原文。',
    outcome:'验收依据 · 知识运营 / 上传替换版本后，怎样验证用户实际查到的是新规则？',
    primary:['管理知识库 →','/knowledge'],more:[['管理用户','/admin/users'],['查看评价处理','/admin/feedback'],['查看运营数据','/admin/stats'],['查询审计记录','/admin/audit-events'],['审阅人工队列','/handoffs']],
  },
}
const guide=computed(()=>guides[session.state.user?.role ?? 'user'])
</script>
<template>
  <header class="page-heading"><p class="eyebrow">服务中心 / {{ guide.role }}</p><h1>{{ guide.home }}</h1><p class="muted">{{ guide.intro }}</p></header>
  <section class="flow" aria-labelledby="workflow-title">
    <h2 id="workflow-title">{{ guide.workflow }}</h2>
    <ol class="steps">
      <li v-for="(step,index) in guide.steps" :key="step.title">
        <RouterLink :to="step.to">
          <div class="diagram" aria-hidden="true">
            <span class="glyph"><svg viewBox="0 0 24 24"><path :d="drawings[step.icon]"/></svg></span>
            <span v-if="index<guide.steps.length-1" class="connector">→</span>
          </div>
          <h3>{{ step.title }}</h3><p>{{ step.detail }}</p>
        </RouterLink>
      </li>
    </ol>
  </section>
  <section class="example" aria-labelledby="example-title">
    <div class="brief"><p class="eyebrow">使用示例</p><h2 id="example-title">{{ guide.example }}</h2>
      <RouterLink class="launch" :to="guide.primary[1]">{{ guide.primary[0] }}</RouterLink>
    </div>
    <div class="exchange"><p class="bubble">{{ guide.question }}</p><p class="response">{{ guide.response }}</p><small>{{ guide.outcome }}</small></div>
  </section>
  <nav class="shortcuts" aria-label="常用入口"><RouterLink v-for="[label,to] in guide.more" :key="to" :to="to">{{ label }} <span aria-hidden="true">↗</span></RouterLink></nav>
</template>
<style scoped>
.flow,.example,.shortcuts { max-width: 1080px; }
.flow { padding-block: 6px 24px; }
.steps { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:20px; padding:0; margin:18px 0 0; list-style:none; }
.steps a { display:block; padding:8px 4px; text-decoration:none; border-radius:8px; }
.steps a:hover h3 { text-decoration:underline; text-underline-offset:4px; }
.diagram { display:flex; align-items:center; gap:18px; margin-bottom:12px; }
.glyph { display:grid; place-items:center; width:44px; height:44px; border-radius:12px; color:var(--ink); background:var(--wash); border:1px solid var(--line); }
.glyph svg { width:22px; height:22px; stroke:currentColor; fill:none; stroke-width:1.45; stroke-linejoin:round; stroke-linecap:round; }
.connector { flex:1; display:flex; align-items:center; color:#93938d; }
.connector::before { content:''; flex:1; border-top:1px dashed var(--edge); }
.steps p { margin:4px 0 0; font-size:13px; color:var(--muted); }
.example { display:grid; grid-template-columns:minmax(180px,1fr) minmax(0,1.7fr); gap:clamp(18px,3vw,42px); padding:clamp(18px,2.4vw,32px); border:1px solid var(--line); border-radius:14px; }
.brief h2 { max-width:20em; }.launch { display:inline-block; margin-top:10px; background:var(--ink); color:white; border-radius:8px; padding:7px 13px; text-decoration:none; font-size:13px; }
.exchange { display:grid; gap:12px; }.exchange p { margin:0; }.bubble { justify-self:end; padding:9px 14px; background:var(--wash); border-radius:12px 3px 12px 12px; }
.exchange small { margin:0; padding-left:10px; border-left:2px solid var(--edge); }
.shortcuts { display:flex; flex-wrap:wrap; gap:12px 22px; margin-top:20px; }.shortcuts a { font-size:13px; }
@media(max-width:760px){.steps{grid-template-columns:1fr;gap:3px}.steps a{display:grid;grid-template-columns:44px 1fr;column-gap:12px}.steps h3{margin:0}.diagram{grid-row:span 2;margin:0}.connector{display:none}.steps p{margin:0}.example{grid-template-columns:1fr}}
</style>
