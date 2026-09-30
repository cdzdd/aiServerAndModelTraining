import test from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { runAction, verifyHostOrigin } from './local-run.mjs'

const env = { COMPOSE_PROJECT_NAME: 'qa-todo-016-test', WEB_PORT: '5246', MODEL_PROVIDER: 'mock', EMBEDDING_MODEL_PATH: 'C:/models/bge' }

test('startup waits for database then migrates before exposing the application', () => {
  const calls = []
  runAction('start', env, (args) => { calls.push(args); return 0 })
  assert.deepEqual(calls.map((args) => args.slice(-1)[0]), ['db', 'head', 'index-worker'])
  assert.ok(calls[0].includes('--wait'))
  assert.ok(calls[2].includes('--wait'))
})

test('failed migration does not start API or workers', () => {
  const calls = []
  assert.throws(() => runAction('start', env, (args) => { calls.push(args); return calls.length === 2 ? 1 : 0 }), /failed/)
  assert.equal(calls.length, 2)
})

test('stop preserves containers and persistent volumes', () => {
  const calls = []
  runAction('stop', env, (args) => { calls.push(args); return 0 })
  assert.equal(calls.length, 1)
  assert.equal(calls[0].at(-1), 'stop')
  assert.ok(!calls[0].includes('-v'))
})

test('local start rejects paid cloud configuration before Docker is called', () => {
  assert.throws(() => runAction('start', { ...env, MODEL_PROVIDER: 'cloud' }, () => assert.fail('Docker called')), /mock or ollama/)
})

test('missing isolation or model directory fails before Docker is called', () => {
  for (const missing of ['COMPOSE_PROJECT_NAME', 'EMBEDDING_MODEL_PATH']) {
    assert.throws(() => runAction('start', { ...env, [missing]: '' }, () => assert.fail('Docker called')))
  }
})

async function withHostServer(handler, check) {
  const server = createServer(handler)
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  try { await check(`http://127.0.0.1:${server.address().port}`) }
  finally { await new Promise((resolve) => server.close(resolve)) }
}

test('host smoke requires the actual published URL to serve readiness and frontend', async () => {
  await withHostServer((req, res) => {
    if (req.url === '/health/ready') {
      res.setHeader('Content-Type', 'application/json'); res.end('{"status":"ready"}')
    } else if (req.url.startsWith('/api/')) {
      res.statusCode = 404; res.setHeader('Content-Type', 'application/json'); res.end('{}')
    } else { res.setHeader('Content-Type', 'text/html'); res.end('<div id="app"></div>') }
  }, (url) => verifyHostOrigin(url))
})

test('host smoke rejects an unready application even if the port responds', async () => {
  await withHostServer((_req, res) => { res.statusCode = 503; res.end('unavailable') }, async (url) => {
    await assert.rejects(verifyHostOrigin(url), /host smoke/)
  })
})

test('host smoke rejects a proxy swallowing API errors in SPA fallback', async () => {
  await withHostServer((req, res) => {
    if (req.url === '/health/ready') {
      res.setHeader('Content-Type', 'application/json'); res.end('{"status":"ready"}')
    } else { res.setHeader('Content-Type', 'text/html'); res.end('<div id="app"></div>') }
  }, async (url) => { await assert.rejects(verifyHostOrigin(url), /host smoke/) })
})
