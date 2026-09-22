<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElButton } from 'element-plus'
import { session } from './session'
import { safeRedirect } from '../../router/guards'
import { errorMessage, fieldErrors } from '../../shared/api/errors'
const route=useRoute(), router=useRouter()
const username=ref(''),password=ref(''),displayName=ref(''),busy=ref(false),error=ref('')
const fields=ref<Record<string,string>>({})
async function submit() {
  if(busy.value) return
  busy.value=true;error.value='';fields.value={}
  try {
    await session.register({username:username.value,password:password.value,display_name:displayName.value})
    password.value=''
    await router.replace({path:'/login',query:{registered:'1',redirect:safeRedirect(route.query.redirect)}})
  } catch(cause) {error.value=errorMessage(cause);fields.value=fieldErrors(cause)}
  finally {busy.value=false}
}
</script>
<template>
  <main class="auth-page">
    <RouterLink class="brand" to="/">知问 · 服务中心</RouterLink>
    <section class="panel auth-card">
      <p class="eyebrow">开始使用</p><h1>注册账号</h1><p class="muted">注册后获得普通用户账号。</p>
      <form @submit.prevent="submit">
        <fieldset :disabled="busy">
          <label for="username">用户名</label>
          <input id="username" v-model="username" name="username" autocomplete="username" required minlength="3" maxlength="50" :aria-invalid="Boolean(fields.username)" aria-describedby="username-help username-error">
          <small id="username-help">3–50 个字符</small><p v-if="fields.username" id="username-error" class="field-error">{{ fields.username }}</p>
          <label for="display-name">显示名称</label>
          <input id="display-name" v-model="displayName" name="display_name" autocomplete="nickname" required maxlength="100" :aria-invalid="Boolean(fields.display_name)" aria-describedby="display-name-error">
          <p v-if="fields.display_name" id="display-name-error" class="field-error">{{ fields.display_name }}</p>
          <label for="password">密码</label>
          <input id="password" v-model="password" name="password" type="password" autocomplete="new-password" required minlength="12" maxlength="128" :aria-invalid="Boolean(fields.password)" aria-describedby="password-help password-error">
          <small id="password-help">12–128 个字符</small><p v-if="fields.password" id="password-error" class="field-error">{{ fields.password }}</p>
          <p v-if="error" role="alert" class="error">{{ error }}</p>
          <ElButton class="full-width" type="primary" native-type="submit" :disabled="busy">{{ busy ? '注册中…' : '注册' }}</ElButton>
        </fieldset>
      </form>
      <p class="auth-switch">已有账号？<RouterLink :to="{path:'/login',query:{redirect:safeRedirect(route.query.redirect)}}">返回登录</RouterLink></p>
    </section>
  </main>
</template>

