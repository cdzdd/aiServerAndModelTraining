<script setup lang="ts">
import { ElButton } from 'element-plus'
import type { Role } from '../auth/session'
import type { ConversationView } from './api'

defineProps<{items:ConversationView[];selectedId:string|null;userId:string;role:Role;page:number;total:number;loading:boolean}>()
const emit=defineEmits<{select:[id:string];create:[];delete:[id:string];page:[value:number]}>()
const modeLabels={bot:'智能问答',queued:'等待客服',human:'人工处理中',closed:'已关闭'}
</script>
<template>
  <aside class="conversation-list panel" aria-label="会话列表">
    <div class="heading"><h2>会话</h2><ElButton type="primary" @click="emit('create')">新建会话</ElButton></div>
    <p v-if="loading" role="status">正在加载会话…</p>
    <p v-else-if="!items.length" class="muted">暂无会话。</p>
    <div v-for="item in items" :key="item.id" class="conversation" :class="{selected:item.id===selectedId}">
      <ElButton aria-label="打开会话" class="select" @click="emit('select',item.id)"><span>{{ item.title }}</span><small>{{ modeLabels[item.mode] }}</small></ElButton>
      <ElButton v-if="item.user_id===userId || role==='admin'" aria-label="删除会话" @click="emit('delete',item.id)">删除</ElButton>
    </div>
    <nav v-if="total>50" class="pagination" aria-label="会话分页"><ElButton :disabled="loading || page===1" @click="emit('page',page-1)">上一页</ElButton><span>第 {{ page }} 页</span><ElButton :disabled="loading || page*50>=total" @click="emit('page',page+1)">下一页</ElButton></nav>
  </aside>
</template>
<style scoped>
.conversation-list{min-width:0}.heading{display:flex;justify-content:space-between;align-items:center;gap:8px}.heading h2{margin:0}.conversation{display:flex;align-items:center;gap:4px;padding:8px 0;border-bottom:1px solid #e3ebee}.conversation.selected{background:#ecf6f6}.conversation .select{display:flex;flex:1;min-width:0;flex-direction:column;align-items:flex-start;height:auto;white-space:normal;overflow-wrap:anywhere}.conversation .select span{max-width:100%;text-align:left}.conversation small{color:#5b707e}.conversation .el-button{margin:0}
</style>
