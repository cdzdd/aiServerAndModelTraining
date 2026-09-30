import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = fileURLToPath(new URL('../../', import.meta.url))

export async function verifyHostOrigin(origin) {
  for (const [route, status, kind] of [
    ['/health/ready', 200, 'ready'], ['/login', 200, 'html'],
    ['/chat/test-deep-link', 200, 'html'], ['/api/v1/runtime-missing', 404, 'json'],
  ]) {
    try {
      const response = await fetch(new URL(route, origin), { signal: AbortSignal.timeout(15000) })
      if (response.status !== status) throw new Error('status')
      const body = await response.text()
      const type = response.headers.get('content-type') ?? ''
      if (kind === 'html' && (!type.includes('text/html') || !body.includes('id="app"'))) throw new Error('html')
      if (kind !== 'html' && !type.includes('application/json')) throw new Error('json')
      if (kind === 'ready' && JSON.parse(body).status !== 'ready') throw new Error('readiness')
    } catch {
      throw new Error(`Local host smoke failed at ${route}; check this runtime's web port and logs. Volumes were preserved.`)
    }
  }
  console.log('PASS published host URL, readiness, deep links and API routing')
}

export function runAction(action, env, execute) {
  if (!env.COMPOSE_PROJECT_NAME || env.COMPOSE_PROJECT_NAME.includes('replace-me')) {
    throw new Error('Set a unique COMPOSE_PROJECT_NAME in this worktree .env.')
  }
  if (!/^\d+$/.test(env.WEB_PORT ?? '')) throw new Error('Set WEB_PORT in .env.')
  if (['build', 'start'].includes(action)) {
    if (!['mock', 'ollama'].includes(env.MODEL_PROVIDER ?? 'mock')) {
      throw new Error('Local runtime allows mock or ollama only; cloud calls are not authorized.')
    }
    if (!env.EMBEDDING_MODEL_PATH) throw new Error('Set the existing BGE EMBEDDING_MODEL_PATH.')
  }
  const compose = ['compose', '--env-file', path.join(root, '.env'), '-f', path.join(root, 'infra/compose.local.yaml'), '-p', `${env.COMPOSE_PROJECT_NAME}-runtime`]
  const actions = {
    build: [['build', 'api', 'web']],
    start: [['up', '-d', '--wait', 'db'], ['run', '--rm', '--no-deps', 'api', 'alembic', 'upgrade', 'head'], ['up', '-d', '--wait', 'api', 'web', 'parse-worker', 'index-worker']],
    stop: [['stop']],
    status: [['ps']],
    logs: [['logs', '--tail', '100']],
    admin: [['exec', 'api', 'python', '-m', 'app.modules.auth.bootstrap_admin']],
    smoke: [['exec', '-T', 'api', 'python', '/app/scripts/deploy/smoke.py', `http://web:8080`, '--origin', `http://127.0.0.1:${env.WEB_PORT}`]],
  }
  if (!actions[action]) throw new Error('Usage: node scripts/deploy/local-run.mjs <build|start|stop|status|logs|admin|smoke>')
  for (const args of actions[action]) {
    if (execute([...compose, ...args]) !== 0) throw new Error(`Local runtime ${action} failed; volumes were preserved.`)
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    if (existsSync(path.join(root, '.env'))) process.loadEnvFile(path.join(root, '.env'))
    const revision = spawnSync('git', ['rev-parse', '--short=12', 'HEAD'], { cwd: root, encoding: 'utf8' })
    if (revision.status !== 0) throw new Error('Cannot determine image version from Git.')
    process.env.RUNTIME_IMAGE_TAG = revision.stdout.trim()
    process.env.BGE_HOST_PATH = process.env.EMBEDDING_MODEL_PATH?.replaceAll('\\', '/') ?? ''
    runAction(process.argv[2], process.env, (args) => {
      const result = spawnSync('docker', args, { cwd: root, stdio: 'inherit' })
      if (result.error) console.error('Docker could not start. Check Docker Desktop and PATH.')
      return result.status ?? 1
    })
    if (['start', 'smoke'].includes(process.argv[2])) {
      await verifyHostOrigin(`http://127.0.0.1:${process.env.WEB_PORT}`)
    }
  } catch (error) {
    console.error(error.message)
    process.exitCode = 1
  }
}
