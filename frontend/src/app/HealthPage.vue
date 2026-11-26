<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElButton } from 'element-plus'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-button.css'

type ServiceState = 'checking' | 'ready' | 'unavailable'
const state = ref<ServiceState>('checking')
const statusLabel = computed(() => ({
  checking: '服务检查中',
  ready: '服务已连接',
  unavailable: '服务暂不可用',
})[state.value])
const statusDescription = computed(() => ({
  checking: '正在确认服务与数据库是否就绪。',
  ready: '服务与数据库已就绪，可以继续开发与验证。',
  unavailable: '暂时无法确认服务已就绪。请确认后端与数据库已启动，然后重新检查。',
})[state.value])

async function checkReadiness() {
  state.value = 'checking'
  try {
    const response = await fetch('/health/ready', {
      headers: { Accept: 'application/json' },
    })
    const payload: unknown = await response.json()
    state.value = response.ok && typeof payload === 'object' && payload !== null
      && 'status' in payload && payload.status === 'ready' ? 'ready' : 'unavailable'
  } catch {
    state.value = 'unavailable'
  }
}

onMounted(checkReadiness)
</script>

<template>
  <main class="foundation">
    <header>
      <p class="eyebrow">知识服务台</p>
      <h1>智能客服与知识问答系统</h1>
      <p class="intro">基础应用已启动，先确认服务连接。</p>
    </header>

    <section class="service-card" aria-labelledby="service-title">
      <p class="section-label" id="service-title">服务连接</p>
      <div role="status" aria-live="polite" aria-atomic="true" :class="['service-status', state]">
        <h2><span class="status-dot" aria-hidden="true" />{{ statusLabel }}</h2>
        <p>{{ statusDescription }}</p>
      </div>
      <ElButton type="primary" :disabled="state === 'checking'" @click="checkReadiness">
        重新检查
      </ElButton>
    </section>

    <a href="/">返回服务中心</a><p class="scope-note">此页面检查服务连接。</p>
  </main>
</template>

<style scoped>
.foundation { width: min(calc(100% - 32px), 660px); margin: 10vh auto 40px; }
.intro, .service-status p, .scope-note { color: var(--muted); }
.service-card { padding: 24px; margin: 24px 0; border: 1px solid var(--line); border-radius: 12px; }
.section-label { font-size: 12px; color: var(--muted); margin: 0 0 12px; }
.service-status h2 { display: flex; align-items: center; gap: 10px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--edge); }
.ready .status-dot { background: var(--green); }
.unavailable .status-dot { background: var(--danger); }
.scope-note { font-size: 12px; }
</style>
