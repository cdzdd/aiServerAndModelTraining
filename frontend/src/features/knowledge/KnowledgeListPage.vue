<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElButton } from 'element-plus'
import { session } from '../auth/session'
import { errorMessage } from '../../shared/api/errors'
import { createKnowledge, listKnowledge, updateKnowledge, type KnowledgeBase, type KnowledgeInput } from './api'
const admin=computed(()=>session.state.user?.role==='admin')
const items=ref<KnowledgeBase[]>([]),page=ref(1),total=ref(0),loading=ref(false),saving=ref(false),error=ref(''),message=ref('')
const editing=ref(false),selected=ref<KnowledgeBase|null>(null)
const form=ref<KnowledgeInput>({name:'',description:'',visibility:'restricted'})
async function load(target=page.value) {
  if(loading.value) return
  loading.value=true;error.value='';items.value=[]
  try {const result=await listKnowledge(target);items.value=result.items;page.value=result.page;total.value=result.total}
  catch(cause) {error.value=errorMessage(cause)}
  finally {loading.value=false}
}
function edit(kb:KnowledgeBase|null) {
  selected.value=kb;editing.value=true;error.value='';message.value=''
  form.value=kb?{name:kb.name,description:kb.description,visibility:kb.visibility}:{name:'',description:'',visibility:'restricted'}
}
async function save() {
  if(saving.value) return
  if(!form.value.name.trim()) {error.value='知识库名称不能为空。';return}
  saving.value=true;error.value=''
  try {
    if(selected.value) await updateKnowledge(selected.value,form.value)
    else await createKnowledge(form.value)
    editing.value=false;message.value='知识库已保存。';await load(1)
  } catch(cause) {error.value=errorMessage(cause)}
  finally {saving.value=false}
}
async function toggle(kb:KnowledgeBase) {
  if(saving.value) return
  saving.value=true;error.value=''
  try {await updateKnowledge(kb,{is_active:!kb.is_active});await load()}
  catch(cause) {error.value=errorMessage(cause)}
  finally {saving.value=false}
}
onMounted(()=>load())
</script>
<template>
  <header class="page-heading"><p class="eyebrow">知识与服务</p><h1>知识库</h1><p class="muted">查看获授权的知识与常见问题。{{ admin?'管理员可维护内容和成员。':'' }}</p></header>
  <p v-if="error" role="alert" class="error">{{ error }}</p>
  <p v-if="message" role="status" class="success">{{ message }}</p>
  <section class="panel">
    <div class="actions"><ElButton v-if="admin" type="primary" :disabled="saving || loading" @click="edit(null)">新建知识库</ElButton><ElButton :disabled="saving || loading" @click="editing=false;load()">刷新列表</ElButton></div>
    <p v-if="loading" role="status">正在加载知识库…</p>
    <p v-else-if="!items.length && !error">暂无可访问的知识库。</p>
    <div v-else-if="items.length" class="table-scroll">
      <table><caption class="sr-only">知识库列表</caption><thead><tr><th>知识库</th><th>访问范围</th><th>状态</th><th v-if="admin">操作</th></tr></thead>
        <tbody><tr v-for="kb in items" :key="kb.id">
          <td><RouterLink v-if="kb.is_active" :to="'/knowledge/'+kb.id">{{ kb.name }}</RouterLink><strong v-else>{{ kb.name }}</strong><small>{{ kb.description }}</small></td>
          <td>{{ kb.visibility==='public'?'所有登录用户':'仅授权成员' }}</td><td>{{ kb.is_active?'已启用':'已停用' }}</td>
          <td v-if="admin"><div class="row-actions"><ElButton :disabled="saving || editing" @click="edit(kb)">编辑知识库</ElButton><ElButton :disabled="saving || editing" @click="toggle(kb)">{{ kb.is_active?'停用知识库':'启用知识库' }}</ElButton></div></td>
        </tr></tbody>
      </table>
    </div>
    <nav v-if="total>20" class="pagination" aria-label="知识库分页"><ElButton :disabled="loading || saving || page===1" @click="editing=false;load(page-1)">上一页</ElButton><span>第 {{ page }} 页 · 共 {{ total }} 个</span><ElButton :disabled="loading || saving || page*20>=total" @click="editing=false;load(page+1)">下一页</ElButton></nav>
  </section>
  <section v-if="admin && editing" class="panel editor">
    <h2>{{ selected?'编辑知识库':'新建知识库' }}</h2>
    <form @submit.prevent="save"><fieldset :disabled="saving">
      <label for="kb-name">知识库名称</label><input id="kb-name" v-model="form.name" required maxlength="100">
      <label for="kb-description">知识库说明</label><textarea id="kb-description" v-model="form.description" rows="3" maxlength="2000" />
      <label for="kb-visibility">访问范围</label><select id="kb-visibility" v-model="form.visibility"><option value="restricted">仅授权成员</option><option value="public">所有登录用户</option></select>
      <p class="muted">“所有登录用户”包含普通用户与客服，匿名访问仍被拒绝。停用后所有角色均无法读取内容。</p>
      <div class="actions"><ElButton type="primary" native-type="submit" :disabled="saving">{{ selected?'保存知识库':'创建知识库' }}</ElButton><ElButton :disabled="saving" @click="editing=false">取消</ElButton></div>
    </fieldset></form>
  </section>
</template>
<style scoped>
textarea{width:100%;padding:10px;border:1px solid #b7c6cf;border-radius:7px;font:inherit;resize:vertical}
td{max-width:320px;overflow-wrap:anywhere}.row-actions{display:flex;flex-wrap:wrap;gap:8px}.row-actions .el-button{margin:0}
.actions{margin-top:0;margin-bottom:18px}
@media(max-width:680px){table,tbody,tr,td{display:block}thead{display:none}tr{padding:14px 0;border-bottom:1px solid #e7edf1}td{border:0;max-width:none;padding:6px 8px}td:first-child{font-weight:600}.row-actions{margin-top:6px}}
</style>
