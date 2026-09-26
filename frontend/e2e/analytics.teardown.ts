import { execFileSync } from 'node:child_process'

export default async function teardown() {
  const schema=process.env.ANALYTICS_E2E_SCHEMA
  if(!schema) return
  execFileSync('uv',['run','--frozen','--directory','../backend','python','-m','tests.analytics.seed_browser'],{
    input:JSON.stringify({action:'cleanup',schema}),encoding:'utf8',
  })
}
