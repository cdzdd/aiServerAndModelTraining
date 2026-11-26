<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { session } from '../features/auth/session'
import { homeFor } from '../router/guards'
import { errorMessage } from '../shared/api/errors'
const router=useRouter(),busy=ref(false),error=ref('')
const roleLabels={user:'普通用户',agent:'客服',admin:'管理员'}
async function logout() {
  if(busy.value) return
  busy.value=true;error.value=''
  try {await session.logout();await router.replace('/login')}
  catch(cause) {error.value=errorMessage(cause)}
  finally {busy.value=false}
}
const homeLabels={user:'我的服务',agent:'客服工作台',admin:'管理概览'}
const links=computed(()=>{
  const role=session.state.user?.role
  if(!role) return []
  const items=[
    {to:homeFor(role),label:homeLabels[role],icon:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z'},
    {to:'/chat',label:'问答会话',icon:'M4 4h16v12H9l-5 4z'},
    {to:'/knowledge',label:'知识库',icon:'M3 5q5-2 9 1 4-3 9-1v14q-5-2-9 1-4-3-9-1z M12 6v14'},
  ]
  if(role!=='user') items.push({to:'/handoffs',label:'人工客服队列',icon:'M3 13l3-8h12l3 8v6H3z M3 13h5l2 3h4l2-3h5'})
  if(role==='admin') items.push(
    {to:'/admin/users',label:'用户管理',icon:'M8 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M2 21v-3a6 6 0 0 1 12 0v3 M16 5q6 2 2 6m-1 3q5 1 5 7'},
    {to:'/admin/feedback',label:'回答反馈',icon:'M4 4h16v12H9l-5 4z M8 9h8'},
    {to:'/admin/stats',label:'管理统计',icon:'M3 3v18h18 M7 16v-5m5 5V6m5 10V9'},
    {to:'/admin/audit-events',label:'审计记录',icon:'M5 3h14v18H5z M8 8h8m-8 4h8m-8 4h5'},
  )
  items.push({to:'/status',label:'服务连接',icon:'M2 12h5l3-7 4 14 3-7h5'})
  return items
})
</script>
<template>
  <div v-if="session.state.user" class="desk">
    <aside class="rail">
      <RouterLink class="desk-brand" :to="homeFor(session.state.user.role)">
        <span class="brand-mark" aria-hidden="true">❯_</span>知识服务台
      </RouterLink>
      <nav aria-label="主导航">
        <p class="rail-label">工作区</p>
        <RouterLink v-for="link in links" :key="link.to" :to="link.to"
          :class="{current:$route.path===link.to || (link.to!==homeFor(session.state.user.role) && $route.path.startsWith(link.to+'/'))}">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="link.icon"/></svg>{{ link.label }}
        </RouterLink>
      </nav>
      <div class="rail-account">
        <span class="avatar" aria-hidden="true">{{ session.state.user.display_name.slice(0,1) }}</span>
        <div><strong>{{ session.state.user.display_name }}</strong><small>{{ roleLabels[session.state.user.role] }}</small></div>
        <button :disabled="busy" @click="logout">{{ busy ? '退出中…' : '退出登录' }}</button>
      </div>
    </aside>
    <main class="desk-content"><p v-if="error" role="alert" class="error">{{ error }}</p><RouterView /></main>
  </div>
</template>
<style scoped>
.desk {display:grid;grid-template-columns:clamp(195px,16vw,240px) minmax(0,1fr);min-height:100dvh}
.rail {position:sticky;top:0;height:100dvh;overflow:auto;background:#f6f6f5;border-right:1px solid #e5e5e3;padding:20px 14px 14px;display:flex;flex-direction:column}
.desk-brand {padding:0 5px}
.rail-label {font-size:12px;color:#70706e;margin:24px 10px 8px}
nav a {display:flex;align-items:center;gap:10px;color:#454542;text-decoration:none;border-radius:8px;padding:9px 11px;margin:2px 0;font-size:14px}
nav a:hover {background:#eeeeec} nav a.current {background:#e6e6e4;color:#252525;font-weight:550}
nav svg {width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}
.rail-account {display:flex;align-items:center;gap:8px;border-top:1px solid #dededb;margin-top:auto;padding:16px 2px 0;font-size:12px}
.rail-account div{min-width:0;overflow-wrap:anywhere}.rail-account small{margin:0}.rail-account button{background:none;border:none;color:#60605d;font-size:12px;white-space:nowrap;margin-left:auto;cursor:pointer}
.avatar {flex:none;display:grid;place-items:center;width:29px;height:29px;border-radius:50%;background:#e0e0dd}
.desk-content {min-width:0;padding:clamp(22px,3vw,44px);width:100%;max-width:1400px;margin-inline:auto}
.desk-content:has(.handoff-page){padding:0;max-width:none}
@media(max-width:680px){.desk{display:block}.rail{position:static;height:auto;padding:12px 14px;border-right:none;border-bottom:1px solid #ddd;display:grid;grid-template-columns:auto minmax(0,1fr);gap:8px}.rail nav{grid-row:2;grid-column:1/-1;display:flex;overflow:auto}.rail nav a{white-space:nowrap;font-size:13px}.rail-label{display:none}.rail-account{grid-row:1;grid-column:2;justify-self:end;margin:0;padding:0;border:0}.rail-account .avatar{display:none}}
</style>
