<script setup lang="ts">
import { ref } from 'vue'
import { ElButton } from 'element-plus'
import type { User } from '../auth/session'
import { updateUser, type UserChanges } from './api'
import { errorMessage, fieldErrors } from '../../shared/api/errors'
const props=defineProps<{user:User}>()
const emit=defineEmits<{saved:[user:User];cancel:[];saving:[value:boolean]}>()
const form=ref<UserChanges>({display_name:props.user.display_name,role:props.user.role,is_active:props.user.is_active})
const saving=ref(false)
const error=ref('')
const fields=ref<Record<string,string>>({})
async function save() {
  if(saving.value) return
  saving.value=true;emit('saving',true);error.value='';fields.value={}
  try {emit('saved',await updateUser(props.user.id,form.value))}
  catch(cause) {error.value=errorMessage(cause);fields.value=fieldErrors(cause)}
  finally {saving.value=false;emit('saving',false)}
}
</script>
<template>
  <section class="panel editor" aria-labelledby="editor-title">
    <h2 id="editor-title">编辑用户 · {{ user.username }}</h2>
    <form @submit.prevent="save">
      <fieldset :disabled="saving">
        <label for="edit-name">显示名称</label>
        <input id="edit-name" v-model="form.display_name" name="display_name" required maxlength="100" :aria-invalid="Boolean(fields.display_name)" aria-describedby="edit-name-error">
        <p v-if="fields.display_name" id="edit-name-error" class="field-error">{{ fields.display_name }}</p>
        <label for="edit-role">角色</label>
        <select id="edit-role" v-model="form.role"><option value="user">普通用户</option><option value="agent">客服</option><option value="admin">管理员</option></select>
        <label class="checkbox"><input v-model="form.is_active" type="checkbox">启用账号</label>
        <p class="muted">停用后，该用户将无法继续访问系统。最后一个有效管理员受到保护。</p>
        <p v-if="error" role="alert" class="error">{{ error }}</p>
        <div class="actions"><ElButton type="primary" native-type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存修改' }}</ElButton><ElButton :disabled="saving" @click="emit('cancel')">取消</ElButton></div>
      </fieldset>
    </form>
  </section>
</template>

