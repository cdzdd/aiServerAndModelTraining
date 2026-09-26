import { expect, it } from 'vitest'
import { decodeChatEvents } from './stream'

async function* bytes(...parts:Uint8Array[]) {for(const part of parts) yield part}
async function collect(parts:Uint8Array[]) {const events=[];for await(const event of decodeChatEvents(bytes(...parts)))events.push(event);return events}
const encoder=new TextEncoder()
const meta='event: meta\r\ndata: {"user_message_id":"u","assistant_message_id":"a"}\r\n\r\n'
const done='event: done\r\ndata: {"answer_status":"answered","evidence_level":"sufficient","intent":"knowledge"}\r\n\r\n'

it('decodes a Chinese UTF-8 character split across bytes and CRLF event boundaries',async()=>{
  const all=encoder.encode(meta+'event: delta\r\ndata: {"text":"你"}\r\n\r\n'+done)
  const split=all.indexOf(0xe4)+1
  const events=await collect([all.slice(0,split),all.slice(split,split+1),all.slice(split+1,all.length-1),all.slice(all.length-1)])
  expect(events).toEqual([
    {type:'meta',user_message_id:'u',assistant_message_id:'a'},
    {type:'delta',text:'你'},
    {type:'done',answer_status:'answered',evidence_level:'sufficient',intent:'knowledge'},
  ])
})

it('joins multiple data lines and parses citations without evaluating text',async()=>{
  const input=meta+'event: citations\ndata: {\ndata: "items":[{"index":1,"title":"<script>x</script>","quote":"原文"}]\ndata: }\n\n'+done
  const events=await collect([encoder.encode(input)])
  expect(events[1]).toEqual({type:'citations',items:[{index:1,title:'<script>x</script>',quote:'原文'}]})
})

it('accepts a terminal error event without a success done',async()=>{
  const events=await collect([encoder.encode(meta+'event: error\ndata: {"code":"MODEL_FAILED","message":"生成失败"}\n\n')])
  expect(events.at(-1)).toEqual({type:'error',code:'MODEL_FAILED',message:'生成失败'})
})

it('rejects missing meta, unknown event, duplicate done, and incomplete EOF',async()=>{
  await expect(collect([encoder.encode('event: delta\ndata: {"text":"x"}\n\n'+done)])).rejects.toThrow()
  await expect(collect([encoder.encode(meta+'event: surprise\ndata: {}\n\n'+done)])).rejects.toThrow()
  await expect(collect([encoder.encode(meta+done+done)])).rejects.toThrow()
  await expect(collect([encoder.encode(meta+'event: delta\ndata: {"text":"x"}\n\n')])).rejects.toThrow()
})
