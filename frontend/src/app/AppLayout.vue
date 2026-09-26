<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElButton } from 'element-plus'
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
</script>
<template>
  <div v-if="session.state.user" class="app-shell">
    <header class="app-header">
      <RouterLink class="brand" :to="homeFor(session.state.user.role)">知问 · 服务中心</RouterLink>
      <div class="account"><span>{{ session.state.user.display_name }}</span><span class="role-tag">{{ roleLabels[session.state.user.role] }}</span><ElButton :disabled="busy" @click="logout">{{ busy ? '退出中…' : '退出登录' }}</ElButton></div>
    </header>
    <div class="shell-body">
      <nav class="sidebar" aria-label="主导航">
        <p class="eyebrow">工作空间</p>
        <RouterLink :to="homeFor(session.state.user.role)">{{ session.state.user.role==='user' ? '我的服务' : session.state.user.role==='agent' ? '客服工作台' : '管理概览' }}</RouterLink>
        <RouterLink v-if="session.state.user.role==='admin'" to="/admin/users">用户管理</RouterLink>
        <RouterLink to="/status">服务连接</RouterLink>
        <RouterLink to="/knowledge">知识库</RouterLink>
        <RouterLink to="/chat">问答会话</RouterLink>
        <RouterLink v-if="session.state.user.role==='admin'" to="/admin/feedback">回答反馈</RouterLink>
      </nav>
      <main class="workspace"><p v-if="error" role="alert" class="error">{{ error }}</p><RouterView /></main>
    </div>
  </div>
</template>
