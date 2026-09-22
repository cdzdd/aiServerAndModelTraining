<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { session } from './features/auth/session'
import { safeRedirect, homeFor } from './router/guards'
const route=useRoute(),router=useRouter()
const showPrivate=computed(()=>session.state.user && (!route.meta.roles || route.meta.roles.includes(session.state.user.role)))
watch(()=>[session.state.user?.id,session.state.user?.role],()=>{
  if(route.meta.public || !route.matched.length) return
  if(!session.state.user) void router.replace({path:'/login',query:{redirect:safeRedirect(route.fullPath)}})
  else if(!showPrivate.value) void router.replace(homeFor(session.state.user.role))
})
</script>
<template>
  <RouterView v-if="route.meta.public || showPrivate" />
  <main v-else class="state-page panel" role="status">正在确认登录状态…</main>
</template>

