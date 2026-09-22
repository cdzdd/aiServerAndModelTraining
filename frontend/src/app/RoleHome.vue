<script setup lang="ts">
import { computed } from 'vue'
import { session } from '../features/auth/session'
const role=computed(()=>session.state.user?.role ?? 'user')
const titles={user:'我的服务',agent:'客服工作台',admin:'管理概览'}
</script>
<template>
  <header class="page-heading"><p class="eyebrow">服务中心</p><h1>{{ titles[role] }}</h1><p class="muted">你好，{{ session.state.user?.display_name }}。</p></header>
  <section class="panel">
    <template v-if="role==='admin'"><h2>账号与访问</h2><p class="muted">查看用户账号，管理角色与启用状态。</p><RouterLink class="text-action" to="/admin/users">管理用户 →</RouterLink></template>
    <template v-else><h2>{{ role==='agent' ? '等待服务接入' : '欢迎来到服务中心' }}</h2><p class="muted">{{ role==='agent' ? '人工接单功能尚未开放。' : '知识问答与会话记录尚未开放。' }}</p></template>
  </section>
  <section class="upcoming"><h2>后续服务</h2><p>知识库、会话、反馈和统计将在对应功能完成后开放。</p></section>
</template>

