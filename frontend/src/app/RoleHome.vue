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
    <template v-else-if="role==='agent'"><h2>人工客服</h2><p class="muted">查看排队请求，接单后回复用户并结束服务。</p><RouterLink class="text-action" to="/handoffs">查看待接单请求 →</RouterLink></template>
    <template v-else><h2>知识问答</h2><p class="muted">选择有权访问的知识库提问，查看回答来源与会话记录。</p><RouterLink class="text-action" to="/chat">开始提问 →</RouterLink></template>
  </section>
  <section class="upcoming"><h2>知识与服务</h2><RouterLink to="/knowledge">浏览知识库与常见问题 →</RouterLink><p>在问答会话中评价回答或申请转人工。</p><template v-if="role==='admin'"><RouterLink to="/admin/feedback">查看评价处理 →</RouterLink><p><RouterLink to="/admin/stats">查看运营数据 →</RouterLink></p></template></section>
</template>
