import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import UploadDocument from './UploadDocument.vue'
import * as api from './api'

enableAutoUnmount(afterEach)
afterEach(()=>vi.restoreAllMocks())
it('reports byte upload progress and refreshes the list after a successful replacement',async()=>{
  let finish!: (value:api.UploadResult)=>void
  const upload=vi.spyOn(api,'replaceDocument').mockImplementation(async(_id,_file,onProgress)=>{
    onProgress(42)
    return new Promise(resolve=>{finish=resolve})
  })
  const wrapper=mount(UploadDocument,{props:{kbId:'kb',documentId:'doc'}})
  const file=new File(['hello'],'新版本.txt',{type:'text/plain'})
  Object.defineProperty(wrapper.get('input[type="file"]').element,'files',{value:[file]})
  await wrapper.get('input[type="file"]').trigger('change')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(upload).toHaveBeenCalledWith('doc',file,expect.any(Function))
  expect(wrapper.text()).toContain('42%')
  finish({document_id:'doc',job_id:'job',status:'uploaded'})
  await flushPromises()
  expect(wrapper.emitted('uploaded')).toHaveLength(1)
})

it('keeps the chosen file and shows a rejected upload error',async()=>{
  vi.spyOn(api,'uploadDocument').mockRejectedValue(new Error('network'))
  const wrapper=mount(UploadDocument,{props:{kbId:'kb'}})
  const file=new File(['hello'],'sample.txt',{type:'text/plain'})
  Object.defineProperty(wrapper.get('input[type="file"]').element,'files',{value:[file]})
  await wrapper.get('input[type="file"]').trigger('change')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('请求失败')
  expect(wrapper.text()).toContain('sample.txt')
})

it('rejects unsupported files before sending an upload',async()=>{
  const upload=vi.spyOn(api,'uploadDocument')
  const wrapper=mount(UploadDocument,{props:{kbId:'kb'}})
  const file=new File(['hello'],'sample.exe',{type:'application/octet-stream'})
  Object.defineProperty(wrapper.get('input[type="file"]').element,'files',{value:[file]})
  await wrapper.get('input[type="file"]').trigger('change')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('PDF、DOCX、TXT 或 MD')
  expect(upload).not.toHaveBeenCalled()
})
