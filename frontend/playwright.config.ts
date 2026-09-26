import { resolve } from 'node:path'
import { defineConfig, devices } from '@playwright/test'
import dotenv from 'dotenv'

dotenv.config({ path: resolve(import.meta.dirname, '../.env'), quiet: true })

const apiPort = process.env.API_PORT ?? '8101'
const webPort = process.env.WEB_PORT ?? '5201'
const baseURL = `http://127.0.0.1:${webPort}`

export default defineConfig({
  testDir: './e2e',
  testIgnore: ['**/chat.spec.ts', '**/handoff.spec.ts', '**/feedback.spec.ts', '**/admin-stats.spec.ts'],
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: { baseURL, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `uv run --frozen --directory ../backend uvicorn app.main:create_app --factory --no-access-log --host 127.0.0.1 --port ${apiPort}`,
      url: `http://127.0.0.1:${apiPort}/health/ready`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`,
      url: baseURL,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
