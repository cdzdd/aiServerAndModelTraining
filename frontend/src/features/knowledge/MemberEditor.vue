<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElButton } from 'element-plus'
import type { User } from '../auth/session'
import { listUsers } from '../users/api'
import { errorMessage } from '../../shared/api/errors'
import { getMembers, setMembers, type Members } from './api'
const props=defineProps<{kbId:string}>()
const emit=defineEmits<{saved:[members:Members];cancel:[];saving:[value:boolean]}>()
const selected=ref<string[]>([]),version=ref(0),users=ref<User[]>([]),page=ref(1),total=ref(0)
const loading=ref(true),saving=ref(false),ready=ref(false),error=ref('')
async function candidates(target:number) {
  loading.value=true;error.value=''
  try {const result=await listUsers(target);users.value=result.items;total.value=result.total;page.value=result.page}
  catch(cause){error.value=errorMessage(cause)}
  finally {loading.value=false}
}
async function initialize() {
  ready.value=false;loading.value=true;error.value=''
  try {
    const members=await getMembers(props.kbId)
    selected.value=members.user_ids;version.value=members.version;ready.value=true
    await candidates(1)
  } catch(cause){error.value=errorMessage(cause)}
  finally {loading.value=false}
}
async function save() {
  if(saving.value || !ready.value || loading.value) return
  saving.value=true;emit('saving',true);error.value=''
  try {emit('saved',await setMembers(props.kbId,selected.value,version.value))}
  catch(cause){error.value=errorMessage(cause)}
  finally {saving.value=false;emit('saving',false)}
}
onMounted(initialize)
</script>
<template>
  <section class="panel editor" aria-label="知识库成员管理"><h2>管理成员</h2>
    <p class="muted">共选择 {{ selected.length }} 位成员。分页不会清除其他页的选择；管理员始终具有管理权限。公开库仍允许所有登录用户读取。</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="loading" role="status">正在加载账号…</p>
    <form @submit.prevent="save"><fieldset :disabled="saving || loading || !ready">
      <label v-for="person in users" :key="person.id" class="checkbox"><input v-model="selected" type="checkbox" :value="person.id" :aria-label="person.username"><span>{{ person.display_name }}<small>{{ person.username }}{{ person.is_active?'':' · 账号已停用' }}</small></span></label>
      <nav v-if="total>20" class="pagination" aria-label="成员候选账号分页"><ElButton :disabled="saving || loading || page===1" @click="candidates(page-1)">上一页账号</ElButton><span>第 {{ page }} 页</span><ElButton :disabled="saving || loading || page*20>=total" @click="candidates(page+1)">下一页账号</ElButton></nav>
      <div class="actions"><ElButton type="primary" native-type="submit" :disabled="saving || loading || !ready">保存成员</ElButton></div>
    </fieldset></form>
    <div class="actions"><ElButton :disabled="saving || loading" @click="initialize">重新加载成员</ElButton><ElButton :disabled="saving" @click="emit('cancel')">取消</ElButton></div>
  </section>
</template>
