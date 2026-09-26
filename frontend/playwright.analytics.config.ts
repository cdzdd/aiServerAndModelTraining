import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { defineConfig, devices } from '@playwright/test'
import dotenv from 'dotenv'

dotenv.config({path:resolve(import.meta.dirname,'../.env'),quiet:true})
if(!process.env.ANALYTICS_E2E_SCHEMA) {
  const result=JSON.parse(execFileSync('uv',['run','--frozen','--directory','../backend','python','-m','tests.analytics.seed_browser'],{
    input:JSON.stringify({action:'seed'}),encoding:'utf8',
  })) as {schema:string;users:Record<string,{id:string;username:string;password:string}>}
  process.env.ANALYTICS_E2E_SCHEMA=result.schema
  process.env.ANALYTICS_E2E_USERS=JSON.stringify(result.users)
  const database=new URL(process.env.DATABASE_URL!)
  database.searchParams.set('options',`-csearch_path=${result.schema},public`)
  process.env.DATABASE_URL=database.toString()
}
const apiPort=process.env.API_PORT??'8101',webPort=process.env.WEB_PORT??'5201'
const baseURL=`http://127.0.0.1:${webPort}`

export default defineConfig({
  testDir:'./e2e',testMatch:'**/admin-stats.spec.ts',fullyParallel:false,workers:1,
  forbidOnly:Boolean(process.env.CI),retries:0,reporter:'list',
  globalTeardown:'./e2e/analytics.teardown.ts',
  use:{baseURL,trace:'retain-on-failure'},
  projects:[{name:'chromium',use:{...devices['Desktop Chrome']}}],
  webServer:[
    {command:`uv run --frozen --directory ../backend uvicorn app.main:create_app --factory --no-access-log --host 127.0.0.1 --port ${apiPort}`,url:`http://127.0.0.1:${apiPort}/health/ready`,reuseExistingServer:false,timeout:60_000},
    {command:`npm run dev -- --host 127.0.0.1 --port ${webPort}`,url:baseURL,reuseExistingServer:false,timeout:60_000},
  ],
})
