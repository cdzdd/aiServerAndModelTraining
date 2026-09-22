import { randomUUID } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('browser session and CSRF work through the real same-origin proxy', async ({ page, context }) => {
  // A same-origin document without UI scripts keeps this protocol test independent of todo-003.
  await page.goto('/health/live')
  const username = 'browser-' + randomUUID().slice(0, 12)
  const result = await page.evaluate(async (username) => {
    const password = 'local-browser-test-password'
    const csrf = await fetch('/api/v1/auth/csrf').then(r => r.json())
    const write = (url: string, body: unknown, token: string) => fetch('/api/v1' + url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
      body: JSON.stringify(body),
    })
    const registered = await write('/auth/register',
      { username, password, display_name: '浏览器验收' }, csrf.csrf_token)
    const logged = await write('/auth/login', { username, password }, csrf.csrf_token)
    const data = await logged.json()
    const me = await fetch('/api/v1/auth/me')
    const missingCsrf = await fetch('/api/v1/auth/logout', { method: 'POST' })
    return {
      registered: registered.status, logged: logged.status, me: me.status,
      missingCsrf: missingCsrf.status, token: data.csrf_token, jsCookies: document.cookie,
    }
  }, username)
  expect([result.registered, result.logged, result.me, result.missingCsrf]).toEqual([201, 200, 200, 403])
  expect(result.jsCookies).not.toContain('qa_session')
  const cookie = (await context.cookies()).find(c => c.name === 'qa_session')
  expect(cookie?.httpOnly).toBe(true)
  expect(cookie?.sameSite).toBe('Lax')
  const loggedOut = await page.evaluate(async token => {
    const response = await fetch('/api/v1/auth/logout',
      { method: 'POST', headers: { 'X-CSRF-Token': token } })
    return [response.status, (await fetch('/api/v1/auth/me')).status]
  }, result.token)
  expect(loggedOut).toEqual([204, 401])
  await context.addCookies([cookie!])
  expect(await page.evaluate(async () => (await fetch('/api/v1/auth/me')).status)).toBe(401)
})
