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
      <p class="eyebrow">开发环境 · 工程骨架</p>
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

<style>
:root {
  font-family: Inter, "Microsoft YaHei", "PingFang SC", sans-serif;
  color: #182c3b;
  background: #f3f6f8;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
  --el-color-primary: #176b70;
  --el-color-primary-light-3: #43868a;
  --el-color-primary-dark-2: #0f5357;
}
* { box-sizing: border-box; }
body { margin: 0; }
.foundation { width: min(100% - 40px, 760px); margin: 12vh auto 48px; }
.eyebrow, .section-label { font-size: 13px; font-weight: 600; letter-spacing: 0.08em; }
.eyebrow { color: #176b70; margin-bottom: 16px; }
h1 { margin: 0; font-size: clamp(26px, 5vw, 38px); letter-spacing: -0.03em; line-height: 1.4; }
.intro { color: #526573; margin: 14px 0 32px; line-height: 1.7; }
.service-card { padding: 30px; border: 1px solid #dce4e8; border-radius: 18px; background: #fff; }
.section-label { color: #526573; margin: 0 0 22px; }
.service-status h2 { display: flex; align-items: center; gap: 10px; font-size: 21px; margin: 0; }
.service-status p { color: #526573; line-height: 1.8; margin: 12px 0 24px; }
.status-dot { width: 10px; height: 10px; flex: 0 0 10px; border-radius: 50%; background: #758796; }
.ready .status-dot { background: #178062; }
.unavailable .status-dot { background: #a56819; }
.service-card .el-button { min-height: 42px; padding: 0 20px; font: inherit; }
.service-card .el-button:focus-visible { outline: 3px solid #83bec2; outline-offset: 3px; }
.scope-note { color: #526573; font-size: 13px; line-height: 1.9; margin-top: 24px; }
@media (max-width: 480px) {
  .foundation { margin-top: 48px; }
  .service-card { padding: 24px; }
}
</style>

