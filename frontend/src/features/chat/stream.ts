import { ApiError } from '../../shared/api/errors'

export interface Citation {
  index:number;chunk_id:string;kb_id:string;source_type:'document'|'faq';source_id:string;
  title:string;page_number?:number|null;paragraph_number?:number|null;line_number?:number|null;
  revision_id?:string|null;faq_version?:number|null;quote:string
}
export type ChatEvent =
  | {type:'meta';user_message_id:string;assistant_message_id:string}
  | {type:'delta';text:string}
  | {type:'citations';items:Citation[]}
  | {type:'done';answer_status:'answered'|'clarify'|'no_answer';evidence_level:'sufficient'|'limited'|'none';intent:'knowledge'|'complaint'|'handoff'|'other';usage?:{prompt_tokens?:number|null;completion_tokens?:number|null;total_tokens?:number|null}|null}
  | {type:'error';code:string;message:string}

const protocolError=()=>new ApiError(0,'STREAM_PROTOCOL','回答流中断，请刷新历史后重试。')
export async function* decodeChatEvents(chunks:AsyncIterable<Uint8Array>):AsyncGenerator<ChatEvent> {
  const decoder=new TextDecoder('utf-8',{fatal:true})
  let buffer='',name='',data:string[]=[],seenMeta=false,terminal=false
  function line(value:string):ChatEvent|undefined {
    if(value==='') {
      if(!name && !data.length) return
      const type=name
      name=''
      let payload:Record<string,unknown>
      try {payload=JSON.parse(data.join('\n')) as Record<string,unknown>}
      catch {throw protocolError()}
      data=[]
      if(terminal || !payload || typeof payload!=='object' || Array.isArray(payload)) throw protocolError()
      if(type==='meta') {
        if(seenMeta || typeof payload.user_message_id!=='string' || typeof payload.assistant_message_id!=='string') throw protocolError()
        seenMeta=true
        return {type,user_message_id:payload.user_message_id,assistant_message_id:payload.assistant_message_id}
      }
      if(!seenMeta) throw protocolError()
      if(type==='delta' && typeof payload.text==='string') return {type,text:payload.text}
      if(type==='citations' && Array.isArray(payload.items)) return {type,items:payload.items as Citation[]}
      if(type==='done' && typeof payload.answer_status==='string' && typeof payload.evidence_level==='string' && typeof payload.intent==='string') {
        terminal=true
        return {...payload,type} as Extract<ChatEvent,{type:'done'}>
      }
      if(type==='error' && typeof payload.code==='string' && typeof payload.message==='string') {
        terminal=true
        return {type,code:payload.code,message:payload.message}
      }
      throw protocolError()
    }
    if(value.startsWith(':')) return
    const colon=value.indexOf(':')
    const field=colon<0?value:value.slice(0,colon)
    const text=colon<0?'':value.slice(colon+1).replace(/^ /,'')
    if(field==='event') name=text
    else if(field==='data') data.push(text)
  }
  function* consume(text:string):Generator<ChatEvent> {
    buffer+=text
    let index=buffer.indexOf('\n')
    while(index>=0) {
      const raw=buffer.slice(0,index)
      buffer=buffer.slice(index+1)
      const event=line(raw.endsWith('\r')?raw.slice(0,-1):raw)
      if(event) yield event
      index=buffer.indexOf('\n')
    }
  }
  try {
    for await(const chunk of chunks) yield* consume(decoder.decode(chunk,{stream:true}))
    yield* consume(decoder.decode())
  } catch(error) {
    if(error instanceof ApiError) throw error
    throw protocolError()
  }
  if(buffer || name || data.length || !terminal) throw protocolError()
}
