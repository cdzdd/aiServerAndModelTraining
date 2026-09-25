<script setup lang="ts">
import { ref } from 'vue'
import { ElButton } from 'element-plus'
import { errorMessage } from '../../shared/api/errors'
import { indexLabel, saveFaq, type Faq } from './api'
const props=defineProps<{kbId:string;faq?:Faq}>()
const emit=defineEmits<{saved:[faq:Faq];cancel:[];saving:[value:boolean]}>()
const form=ref({question:props.faq?.question ?? '',answer:props.faq?.answer ?? '',is_active:props.faq?.is_active ?? true})
const saving=ref(false),error=ref('')
async function save() {
  if(saving.value) return
  if(!form.value.question.trim() || !form.value.answer.trim()) {error.value='问题和答案不能为空。';return}
  saving.value=true;emit('saving',true);error.value=''
  try {emit('saved',await saveFaq(props.kbId,form.value,props.faq))}
  catch(cause){error.value=errorMessage(cause)}
  finally {saving.value=false;emit('saving',false)}
}
</script>
<template>
  <section class="panel editor" aria-label="FAQ 编辑">
    <h2>{{ faq?'编辑 FAQ':'新增 FAQ' }}</h2>
    <p class="muted">{{ faq?indexLabel(faq):'待索引' }} · 保存后需完成对应版本的索引才能参与检索。</p>
    <form @submit.prevent="save"><fieldset :disabled="saving">
      <label for="faq-question">问题</label><input id="faq-question" v-model="form.question" name="question" required maxlength="500">
      <label for="faq-answer">答案</label><textarea id="faq-answer" v-model="form.answer" name="answer" required rows="6" maxlength="10000" />
      <label class="checkbox"><input v-model="form.is_active" type="checkbox">启用 FAQ</label>
      <p v-if="error" role="alert" class="error">{{ error }}</p>
      <div class="actions"><ElButton type="primary" native-type="submit" :disabled="saving">{{ saving?'保存中…':'保存 FAQ' }}</ElButton><ElButton :disabled="saving" @click="emit('cancel')">取消</ElButton></div>
    </fieldset></form>
  </section>
</template>
<style scoped>
textarea{width:100%;padding:10px;border:1px solid #b7c6cf;border-radius:7px;font:inherit;resize:vertical}
</style>
