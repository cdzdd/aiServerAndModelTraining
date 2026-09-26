import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../', import.meta.url))
if (existsSync(path.join(root, '.env'))) process.loadEnvFile(path.join(root, '.env'))

function run(command, args, directory = root) {
  const result = spawnSync(command, args, {
    cwd: directory,
    stdio: 'inherit',
    // Windows npm is a .cmd file; all shell arguments here are fixed literals.
    shell: process.platform === 'win32' && command === 'npm',
  })
  if (result.error) console.error(result.error.message)
  if (result.status !== 0) process.exit(result.status ?? 1)
}

const backend = path.join(root, 'backend')
const frontend = path.join(root, 'frontend')
const compose = ['compose', '--env-file', path.join(root, '.env'), '-f', path.join(root, 'infra/compose.dev.yaml')]
switch (process.argv[2]) {
  case 'db-up':
  case 'db-stop':
    if (!process.env.COMPOSE_PROJECT_NAME || process.env.COMPOSE_PROJECT_NAME.includes('replace-me')) {
      throw new Error('Set a unique COMPOSE_PROJECT_NAME in this worktree .env first.')
    }
    run('docker', [...compose, '-p', process.env.COMPOSE_PROJECT_NAME,
      ...(process.argv[2] === 'db-up' ? ['up', '-d', '--wait', 'db'] : ['stop', 'db'])])
    break
  case 'api': {
    const port = process.env.API_PORT
    if (!port || !/^\d+$/.test(port)) throw new Error('Set API_PORT in .env.')
    run('uv', ['run', '--frozen', 'uvicorn', 'app.main:create_app', '--factory', '--no-proxy-headers', '--no-access-log', '--host', '127.0.0.1', '--port', port], backend)
    break
  }
  case 'worker':
    run('uv', ['run', '--frozen', 'python', '-m', 'app.modules.ingestion.worker'], backend)
    break
  case 'web':
    run('npm', ['run', 'dev'], frontend)
    break
  case 'check':
    if (!process.env.TEST_DATABASE_URL) throw new Error('Set a dedicated TEST_DATABASE_URL before running checks.')
    run('uv', ['run', '--frozen', 'ruff', 'check', '.'], backend)
    run('uv', ['run', '--frozen', 'pytest', '-q'], backend)
    // A second upgrade must be a safe no-op on an already migrated database.
    run('uv', ['run', '--frozen', 'alembic', 'upgrade', 'head'], backend)
    run('uv', ['run', '--frozen', 'alembic', 'upgrade', 'head'], backend)
    for (const script of ['lint', 'typecheck', 'test', 'build', 'test:e2e']) {
      run('npm', ['run', script, ...(script === 'test' ? ['--', '--run'] : [])], frontend)
    }
    break
  default:
    console.error('Usage: node scripts/dev.mjs <db-up|db-stop|api|web|worker|check>')
    process.exit(1)
}
