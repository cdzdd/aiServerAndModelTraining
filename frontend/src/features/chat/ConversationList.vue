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
      <button type="button" aria-label="打开会话" :aria-current="item.id===selectedId?'page':undefined" class="select" @click="emit('select',item.id)"><span>{{ item.title }}</span><small>{{ modeLabels[item.mode] }}</small></button>
      <button class="remove" title="删除会话" v-if="item.user_id===userId || role==='admin'" aria-label="删除会话" @click="emit('delete',item.id)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5m4-5v5"/></svg></button>
    </div>
    <nav v-if="total>50" class="pagination" aria-label="会话分页"><ElButton :disabled="loading || page===1" @click="emit('page',page-1)">上一页</ElButton><span>第 {{ page }} 页</span><ElButton :disabled="loading || page*50>=total" @click="emit('page',page+1)">下一页</ElButton></nav>
  </aside>
</template>
<style scoped>
.conversation-list { min-width: 0; padding: 12px; background: var(--wash); }
.heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 2px 2px 12px; }
.heading h2 { margin: 0; font-size: 15px; }
.conversation { display: flex; align-items: center; gap: 4px; border-radius: 8px; padding: 2px 5px; }
.conversation:hover { background: #eeeeec; }
.conversation.selected { background: var(--selected); }
.select { flex: 1; display: grid; gap: 1px; min-width: 0; text-align: left; padding: 6px; border: 0; background: transparent; }
.select span { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.select small { margin: 0; font-size: 11px; }
.remove { display: grid; place-items: center; padding: 6px; border: 0; background: transparent; color: var(--muted); }
.remove svg { width: 15px; height: 15px; stroke: currentColor; stroke-width: 1.5; fill: none; stroke-linecap: round; }
.remove:hover { color: var(--danger); }
@media (max-width: 760px) { .conversation-list { max-height: 245px; overflow: auto; } }
</style>
