<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElButton } from 'element-plus'
import { session, type User } from '../auth/session'
import { homeFor } from '../../router/guards'
import { errorMessage } from '../../shared/api/errors'
import { listUsers } from './api'
import UserEditor from './UserEditor.vue'
const router=useRouter()
const users=ref<User[]>([]),page=ref(1),total=ref(0),loading=ref(false),error=ref(''),message=ref(''),selected=ref<User|null>(null)
const roles={user:'普通用户',agent:'客服',admin:'管理员'}
async function load(target=page.value) {
  if(loading.value) return
  loading.value=true;error.value='';selected.value=null;users.value=[]
  try {const result=await listUsers(target);users.value=result.items;total.value=result.total;page.value=result.page}
  catch(cause) {error.value=errorMessage(cause)}
  finally {loading.value=false}
}
async function saved(user:User) {
  selected.value=null;message.value='用户已更新。'
  users.value=users.value.map(item=>item.id===user.id?user:item)
  if(user.id===session.state.user?.id) {
    try {
      await session.restore(true)
      if(session.state.user?.role!=='admin') await router.replace(session.state.user?homeFor(session.state.user.role):'/login')
    } catch {
      await router.replace({path:'/session-error',query:{redirect:'/admin/users'}})
    }
  }
}
onMounted(()=>load())
</script>
<template>
  <header class="page-heading"><p class="eyebrow">账号与访问</p><h1>用户管理</h1><p class="muted">管理用户角色与账号状态。</p></header>
  <p v-if="message" role="status" class="success">{{ message }}</p>
  <section class="panel">
    <p v-if="loading" role="status">正在加载用户…</p>
    <div v-else-if="error"><p role="alert" class="error">{{ error }}</p><ElButton @click="load()">重试</ElButton></div>
    <p v-else-if="users.length===0">暂无用户。</p>
    <div v-else class="table-scroll">
      <table><caption class="sr-only">用户账号列表</caption><thead><tr><th scope="col">用户</th><th scope="col">角色</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead>
        <tbody><tr v-for="user in users" :key="user.id"><td><strong>{{ user.display_name }}</strong><small>{{ user.username }}</small></td><td>{{ roles[user.role] }}</td><td><span :class="['status-tag',user.is_active?'active':'']">{{ user.is_active?'已启用':'已停用' }}</span></td><td><ElButton :aria-label="'编辑 '+user.username" @click="selected=user;message=''">编辑</ElButton></td></tr></tbody>
      </table>
    </div>
    <nav v-if="!error && total>20" class="pagination" aria-label="用户分页"><ElButton :disabled="loading || page===1" @click="load(page-1)">上一页</ElButton><span>第 {{ page }} 页 · 共 {{ total }} 人</span><ElButton :disabled="loading || page*20>=total" @click="load(page+1)">下一页</ElButton></nav>
  </section>
  <UserEditor v-if="selected" :key="selected.id" :user="selected" @saved="saved" @cancel="selected=null" />
</template>

