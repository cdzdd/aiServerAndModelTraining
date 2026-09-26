import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { session } from '../auth/session'
import { ApiError } from '../../shared/api/errors'
import CitationPanel from './CitationPanel.vue'

enableAutoUnmount(afterEach)
afterEach(()=>vi.restoreAllMocks())
const item={index:1,chunk_id:'chunk',kb_id:'kb',source_type:'document' as const,source_id:'doc',title:'<img src=x onerror=alert(1)>',quote:'受控原文',revision_id:'rev',faq_version:null,page_number:2,paragraph_number:null,line_number:null}

it('shows source location as text and reports a revoked download permission',async()=>{
  const download=vi.spyOn(session.api,'download').mockRejectedValue(new ApiError(404,'NOT_FOUND','来源不可访问'))
  const wrapper=mount(CitationPanel,{props:{items:[item]}})
  expect(wrapper.text()).toContain('第 2 页')
  expect(wrapper.text()).toContain('受控原文')
  expect(wrapper.find('img').exists()).toBe(false)
  await wrapper.get('button[aria-label="下载来源文件"]').trigger('click')
  await flushPromises()
  expect(download).toHaveBeenCalledWith('/documents/doc/download')
  expect(wrapper.get('[role="alert"]').text()).toContain('来源不可访问')
})

it('does not show a file download action for an FAQ citation',()=>{
  const wrapper=mount(CitationPanel,{props:{items:[{...item,source_type:'faq',faq_version:3,revision_id:null}]}})
  expect(wrapper.find('button[aria-label="下载来源文件"]').exists()).toBe(false)
})
