<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElButton } from 'element-plus'
import { session } from './session'
import { safeRedirect } from '../../router/guards'
import { errorMessage, fieldErrors } from '../../shared/api/errors'
const route=useRoute(), router=useRouter()
const username=ref(''), password=ref(''), busy=ref(false), error=ref('')
const fields=ref<Record<string,string>>({})
async function submit() {
  if(busy.value) return
  busy.value=true;error.value='';fields.value={}
  try {
    await session.login({username:username.value,password:password.value})
    password.value=''
    await router.replace(safeRedirect(route.query.redirect))
  } catch(cause) {error.value=errorMessage(cause);fields.value=fieldErrors(cause)}
  finally {busy.value=false}
}
</script>
<template>
  <main class="auth-page">
    <RouterLink class="brand" to="/">知问 · 服务中心</RouterLink>
    <section class="panel auth-card">
      <p class="eyebrow">欢迎回来</p><h1>登录</h1><p class="muted">登录你的账号，进入服务中心。</p>
      <p v-if="route.query.registered === '1'" role="status" class="success">注册成功，请登录。</p>
      <p v-if="session.state.expired" role="alert" class="error">登录已失效，请重新登录。</p>
      <form @submit.prevent="submit">
        <fieldset :disabled="busy">
          <label for="username">用户名</label>
          <input id="username" v-model="username" name="username" autocomplete="username" required minlength="3" maxlength="50" :aria-invalid="Boolean(fields.username)" aria-describedby="username-error">
          <p v-if="fields.username" id="username-error" class="field-error">{{ fields.username }}</p>
          <label for="password">密码</label>
          <input id="password" v-model="password" name="password" type="password" autocomplete="current-password" required minlength="12" maxlength="128" :aria-invalid="Boolean(fields.password)" aria-describedby="password-error">
          <p v-if="fields.password" id="password-error" class="field-error">{{ fields.password }}</p>
          <p v-if="error" role="alert" class="error">{{ error }}</p>
          <ElButton class="full-width" type="primary" native-type="submit" :disabled="busy">{{ busy ? '登录中…' : '登录' }}</ElButton>
        </fieldset>
      </form>
      <p class="auth-switch">还没有账号？<RouterLink :to="{path:'/register',query:{redirect:safeRedirect(route.query.redirect)}}">注册账号</RouterLink></p>
    </section>
    <RouterLink class="quiet-link" to="/status">查看服务连接</RouterLink>
  </main>
</template>

