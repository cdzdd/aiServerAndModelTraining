<script setup lang="ts">
import { ref } from 'vue'
import { ElButton } from 'element-plus'
import { errorMessage } from '../../../shared/api/errors'
import { replaceDocument, uploadDocument } from './api'

const props=defineProps<{kbId:string;documentId?:string}>()
const emit=defineEmits<{uploaded:[];cancel:[]}>()
const file=ref<File|null>(null),progress=ref<number|null>(null),saving=ref(false),error=ref('')
function chosen(event:Event) {file.value=(event.target as HTMLInputElement).files?.[0] ?? null;error.value='';progress.value=null}
async function submit() {
  if(saving.value) return
  if(!file.value) {error.value='请选择文件。';return}
  if(!/\.(pdf|docx|txt|md)$/i.test(file.value.name)) {error.value='请选择 PDF、DOCX、TXT 或 MD 文件。';return}
  if(file.value.size>20*1024*1024) {error.value='文件不能超过 20 MiB。';return}
  saving.value=true;error.value='';progress.value=0
  try {
    const onProgress=(value:number)=>{progress.value=value}
    if(props.documentId) await replaceDocument(props.documentId,file.value,onProgress)
    else await uploadDocument(props.kbId,file.value,onProgress)
    emit('uploaded')
  } catch(cause) {error.value=errorMessage(cause)}
  finally {saving.value=false}
}
</script>
<template>
  <section class="panel editor" :aria-label="documentId?'上传新版本':'上传文档'">
    <h3>{{ documentId?'上传新版本':'上传文档' }}</h3>
    <p class="muted">支持文本 PDF、DOCX、TXT、MD；每个文件最多 20 MiB。上传后将后台解析。</p>
    <form @submit.prevent="submit"><fieldset :disabled="saving">
      <label for="document-file">选择文件</label><input id="document-file" type="file" accept=".pdf,.docx,.txt,.md" @change="chosen">
      <p v-if="file">已选：{{ file.name }}</p>
      <p v-if="progress!==null" role="status">上传进度 {{ progress }}%</p>
      <p v-if="error" role="alert" class="error">{{ error }}</p>
      <div class="actions"><ElButton type="primary" native-type="submit" :disabled="saving">{{ saving?'上传中…':documentId?'上传新版本':'上传文档' }}</ElButton><ElButton :disabled="saving" @click="emit('cancel')">取消</ElButton></div>
    </fieldset></form>
  </section>
</template>
