import { afterEach, expect, it, vi } from 'vitest'
import { createApiClient } from './client'
import { ApiError } from './errors'

afterEach(()=>vi.unstubAllGlobals())

it('uploads FormData with CSRF, cookies and actual progress without setting JSON content type',async()=>{
  const headers:Record<string,string>={}
  let credentials=false
  class Request {
    upload={onprogress:null as ((event:ProgressEvent)=>void)|null}
    onload: (()=>void)|null=null
    status=202
    responseText='{"document_id":"doc","job_id":"job","status":"uploaded"}'
    withCredentials=false
    open(method:string,url:string){expect(method).toBe('POST');expect(url).toBe('/api/v1/knowledge-bases/kb/documents')}
    setRequestHeader(name:string,value:string){headers[name]=value}
    send(body:Document|XMLHttpRequestBodyInit|null){expect(body).toBeInstanceOf(FormData);credentials=this.withCredentials;this.upload.onprogress?.({lengthComputable:true,loaded:4,total:10} as ProgressEvent);this.onload?.()}
  }
  vi.stubGlobal('XMLHttpRequest',Request)
  const client=createApiClient(()=>{})
  client.setCsrfToken('csrf')
  const progress:number[]=[]
  const result=await client.upload('/knowledge-bases/kb/documents',new FormData(),value=>progress.push(value))
  expect(result).toEqual({document_id:'doc',job_id:'job',status:'uploaded'})
  expect(headers['X-CSRF-Token']).toBe('csrf')
  expect(headers['Content-Type']).toBeUndefined()
  expect(credentials).toBe(true)
  expect(progress).toEqual([40])
})

it('clears an expired session on an unauthorized upload',async()=>{
  class Request {
    upload={onprogress:null}
    onload: (()=>void)|null=null
    status=401
    responseText='{"error":{"code":"UNAUTHENTICATED","message":"未登录"}}'
    withCredentials=false
    open(){} setRequestHeader(){} send(){this.onload?.()}
  }
  vi.stubGlobal('XMLHttpRequest',Request)
  const unauthorized=vi.fn(),client=createApiClient(unauthorized)
  client.setCsrfToken('csrf')
  await expect(client.upload('/upload',new FormData(),()=>{})).rejects.toBeInstanceOf(ApiError)
  expect(unauthorized).toHaveBeenCalledOnce()
})

it('downloads file bytes through the authenticated client and reports denied access',async()=>{
  let unauthorized=0
  vi.stubGlobal('fetch',async()=>new Response('sample',{headers:{'Content-Type':'text/plain'}}))
  const client=createApiClient(()=>{unauthorized++})
  expect((await client.download('/documents/doc/download')).size).toBe(6)
  vi.stubGlobal('fetch',async()=>new Response(JSON.stringify({error:{code:'UNAUTHENTICATED',message:'会话过期'}}),{status:401,headers:{'Content-Type':'application/json'}}))
  await expect(client.download('/documents/doc/download')).rejects.toMatchObject({status:401,code:'UNAUTHENTICATED'})
  expect(unauthorized).toBe(1)
})

it('does not clear a new session when an old download error body arrives late',async()=>{
  let finishBody!:(value:unknown)=>void
  let bodyStarted!:()=>void
  const body=new Promise<unknown>(resolve=>{finishBody=resolve})
  const started=new Promise<void>(resolve=>{bodyStarted=resolve})
  vi.stubGlobal('fetch',async()=>({ok:false,status:401,json:()=>{bodyStarted();return body}}))
  const unauthorized=vi.fn(),client=createApiClient(unauthorized)
  client.setCsrfToken('old-session')
  const result=client.download('/documents/doc/download').catch(error=>error)
  await started
  client.setCsrfToken('new-session')
  finishBody({error:{code:'UNAUTHENTICATED',message:'会话过期'}})
  expect(await result).toMatchObject({code:'SESSION_CHANGED'})
  expect(unauthorized).not.toHaveBeenCalled()
})
