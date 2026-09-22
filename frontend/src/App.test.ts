import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import App from './App.vue'

enableAutoUnmount(afterEach)

function healthResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function useHealthResponse(response: Response) {
  vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
    if (input !== '/health/ready') throw new Error('Unexpected endpoint')
    return response
  })
}

describe('service readiness', () => {
  it('shows an accessible pending state before the health response arrives', async () => {
    let resolveHealth!: (response: Response) => void
    vi.stubGlobal('fetch', () => new Promise<Response>((resolve) => {
      resolveHealth = resolve
    }))
    const page = mount(App)

    expect(page.find('main').exists()).toBe(true)
    expect(page.get('[role="status"]').text()).toContain('检查中')
    expect(page.get('button').attributes('disabled')).toBeDefined()

    resolveHealth(healthResponse(200, { status: 'ready' }))
    await flushPromises()
    expect(page.get('button').attributes('disabled')).toBeUndefined()
  })

  it('shows connected only after the readiness endpoint confirms ready', async () => {
    useHealthResponse(healthResponse(200, { status: 'ready' }))
    const page = mount(App)
    await flushPromises()

    expect(page.get('[role="status"]').text()).toContain('已连接')
    expect(page.get('button').attributes('disabled')).toBeUndefined()
  })

  it('shows unavailable for a failed HTTP response even if its body says ready', async () => {
    useHealthResponse(healthResponse(503, { status: 'ready' }))
    const page = mount(App)
    await flushPromises()

    expect(page.get('[role="status"]').text()).toContain('暂不可用')
    expect(page.get('button').attributes('disabled')).toBeUndefined()
  })

  it('shows unavailable when the server cannot be reached', async () => {
    vi.stubGlobal('fetch', async () => { throw new TypeError('Network failure') })
    const page = mount(App)
    await flushPromises()

    expect(page.get('[role="status"]').text()).toContain('暂不可用')
  })

  it('does not label an unexpected success payload as ready', async () => {
    useHealthResponse(healthResponse(200, { status: 'ok' }))
    const page = mount(App)
    await flushPromises()

    expect(page.get('[role="status"]').text()).toContain('暂不可用')
  })

  it('rechecks the service on request and replaces the previous failure state', async () => {
    useHealthResponse(healthResponse(503, { status: 'unavailable' }))
    const page = mount(App)
    await flushPromises()
    expect(page.get('[role="status"]').text()).toContain('暂不可用')

    useHealthResponse(healthResponse(200, { status: 'ready' }))
    await page.get('button').trigger('click')
    await flushPromises()

    expect(page.get('[role="status"]').text()).toContain('已连接')
  })
})
