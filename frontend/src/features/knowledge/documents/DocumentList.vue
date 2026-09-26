<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElButton } from 'element-plus'
import { session } from '../../auth/session'
import { errorMessage } from '../../../shared/api/errors'
import { deleteDocument, downloadDocument, listDocuments, reindexDocument, setDocumentActive, statusLabel, type DocumentSummary } from './api'
import UploadDocument from './UploadDocument.vue'

const props=defineProps<{kbId:string}>()
const admin=computed(()=>session.state.user?.role==='admin')
const items=ref<DocumentSummary[]>([]),page=ref(1),total=ref(0),loading=ref(false),saving=ref(false)
const error=ref(''),message=ref(''),uploadFor=ref<string|null|undefined>(undefined)
const downloading=ref<string|null>(null)
let generation=0,timer:ReturnType<typeof setTimeout>|undefined
async function load(target=page.value) {
  const current=++generation
  clearTimeout(timer)
  loading.value=true;error.value='';items.value=[]
  try {
    const result=await listDocuments(props.kbId,target)
    if(current!==generation) return
    items.value=result.items;page.value=result.page;total.value=result.total
    if(items.value.some(item=>['uploaded','processing'].includes(item.status) && item.latest_job?.kind==='parse'))
      timer=setTimeout(()=>{void load(page.value)},5000)
  } catch(cause) {if(current===generation)error.value=errorMessage(cause)}
  finally {if(current===generation)loading.value=false}
}
async function change(item:DocumentSummary,action:'toggle'|'delete'|'reindex') {
  if(saving.value) return
  if(action==='delete' && !window.confirm('确定删除文档“'+item.filename+'”？')) return
  const current=generation
  saving.value=true;error.value='';message.value=''
  try {
    if(action==='toggle') await setDocumentActive(item.id,item.status==='disabled')
    else if(action==='delete') await deleteDocument(item.id)
    else await reindexDocument(item.id)
    if(current===generation) {message.value=action==='delete'?'文档已删除。':action==='reindex'?'已提交解析任务。':'文档状态已更新。';await load(page.value)}
  } catch(cause) {if(current===generation)error.value=errorMessage(cause)}
  finally {saving.value=false}
}
function uploaded() {uploadFor.value=undefined;message.value='上传完成，已提交解析任务。';void load(1)}
async function download(item:DocumentSummary) {
  if(downloading.value) return
  const current=generation
  downloading.value=item.id;error.value=''
  try {
    const blob=await downloadDocument(item.id)
    if(current!==generation) return
    const url=URL.createObjectURL(blob),link=window.document.createElement('a')
    link.href=url;link.download=item.active_revision?.filename ?? item.filename
    link.click()
    setTimeout(()=>URL.revokeObjectURL(url),0)
  } catch(cause) {if(current===generation)error.value=errorMessage(cause)}
  finally {downloading.value=null}
}
watch(()=>props.kbId,()=>{uploadFor.value=undefined;message.value='';page.value=1;void load(1)},{immediate:true})
onUnmounted(()=>{generation++;clearTimeout(timer)})
</script>
<template>
  <section class="document-list" aria-label="文档">
    <div class="actions"><h2>文档</h2><ElButton v-if="admin" :disabled="saving || loading" @click="uploadFor=null">上传文档</ElButton><ElButton :disabled="saving || loading" @click="load()">刷新文档</ElButton></div>
    <UploadDocument v-if="admin && uploadFor!==undefined" :key="uploadFor ?? 'new'" :kb-id="kbId" :document-id="uploadFor ?? undefined" @uploaded="uploaded" @cancel="uploadFor=undefined" />
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="message" role="status" class="success">{{ message }}</p>
    <p v-if="loading" role="status">正在加载文档…</p>
    <p v-else-if="!items.length && !error" class="panel">暂无文档。</p>
    <article v-for="item in items" :key="item.id" class="panel document-card">
      <div class="document-heading"><h3>{{ item.filename }}</h3><span class="status-tag">{{ statusLabel(item.status) }}</span></div>
      <p v-if="item.active_revision">当前有效版本：{{ item.active_revision.filename }} · {{ new Date(item.active_revision.created_at).toLocaleString() }}</p>
      <p v-if="item.active_revision && (item.candidate_revision_id || ['uploaded','processing','parsed','failed'].includes(item.status))">新版本处理：{{ statusLabel(item.status) }}<span v-if="item.candidate_revision"> · {{ item.candidate_revision.filename }}</span></p>
      <p v-if="item.latest_job?.state==='failed'" class="error">失败原因：{{ item.latest_job.error_message ?? item.latest_job.error_code ?? '解析失败，请重试。' }}</p>
      <p v-else-if="item.latest_job?.state==='queued' || item.latest_job?.state==='running'" class="muted">任务：{{ item.latest_job.kind==='parse'?'解析':'索引' }}{{ item.latest_job.state==='queued'?'排队中':'处理中' }}</p>
      <div class="actions">
        <ElButton v-if="item.status!=='disabled' && item.status!=='deleted'" aria-label="下载原文件" :disabled="Boolean(downloading)" @click="download(item)">下载原文件</ElButton>
        <template v-if="admin"><ElButton :disabled="saving" @click="uploadFor=item.id">上传新版本</ElButton><ElButton :disabled="saving" @click="change(item,'toggle')">{{ item.status==='disabled'?'启用文档':'停用文档' }}</ElButton><ElButton v-if="item.status==='failed'" :aria-label="'重试解析'" :disabled="saving" @click="change(item,'reindex')">重试解析</ElButton><ElButton :disabled="saving" @click="change(item,'delete')">删除文档</ElButton></template>
      </div>
    </article>
    <nav v-if="total>20" class="pagination" aria-label="文档分页"><ElButton :disabled="loading || saving || page===1" @click="load(page-1)">上一页文档</ElButton><span>第 {{ page }} 页 · 共 {{ total }} 个</span><ElButton :disabled="loading || saving || page*20>=total" @click="load(page+1)">下一页文档</ElButton></nav>
  </section>
</template>
<style scoped>
.document-list{margin-top:28px}.document-card{margin:16px 0;overflow-wrap:anywhere}.document-heading{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.document-heading h3{margin:0;min-width:0;overflow-wrap:anywhere}.status-tag{flex-shrink:0}.actions{flex-wrap:wrap}.actions .el-button{margin:0}
@media(max-width:500px){.document-heading{flex-direction:column}}
</style>
