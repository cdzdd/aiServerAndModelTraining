<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElButton } from 'element-plus'
import { session } from '../features/auth/session'
import { safeRedirect } from '../router/guards'
import { errorMessage } from '../shared/api/errors'
defineProps<{kind:'session-error'|'forbidden'|'not-found'}>()
const route=useRoute(),router=useRouter(),busy=ref(false),error=ref('')
async function retry() {
  busy.value=true;error.value=''
  try {await session.restore(true);await router.replace(safeRedirect(route.query.redirect))}
  catch(cause) {error.value=errorMessage(cause)}
  finally {busy.value=false}
}
</script>
<template>
  <main class="state-page panel">
    <p class="eyebrow">知问 · 服务中心</p>
    <h1>{{ kind==='session-error' ? '暂时无法确认登录状态' : kind==='forbidden' ? '没有访问权限' : '页面不存在' }}</h1>
    <p class="muted">{{ kind==='session-error' ? '请检查网络连接，稍后再试。' : kind==='forbidden' ? '当前账号无法访问此页面，请返回你的工作空间。' : '这个地址暂时没有可用的页面。' }}</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <ElButton v-if="kind==='session-error'" type="primary" :disabled="busy" @click="retry">{{ busy ? '正在重试…' : '重试' }}</ElButton>
    <RouterLink v-else class="text-action" to="/">返回首页</RouterLink>
    <RouterLink class="quiet-link" to="/status">查看服务连接</RouterLink>
  </main>
</template>

