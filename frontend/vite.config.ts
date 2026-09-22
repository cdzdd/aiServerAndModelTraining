import { resolve } from 'node:path'
import vue from '@vitejs/plugin-vue'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

export default defineConfig(({ mode }) => {
  const envDir = resolve(import.meta.dirname, '..')
  const env = loadEnv(mode, envDir, '')
  const apiPort = process.env.API_PORT ?? env.API_PORT ?? '8101'
  const webPort = process.env.WEB_PORT ?? env.WEB_PORT ?? '5201'

  return {
    plugins: [vue()],
    envDir,
    server: {
      host: '127.0.0.1',
      port: Number(webPort),
      strictPort: true,
      proxy: {
        '/api': { target: `http://127.0.0.1:${apiPort}`, changeOrigin: false },
        '/health': { target: `http://127.0.0.1:${apiPort}`, changeOrigin: false },
      },
    },
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.ts'],
      restoreMocks: true,
      unstubGlobals: true,
    },
  }
})
