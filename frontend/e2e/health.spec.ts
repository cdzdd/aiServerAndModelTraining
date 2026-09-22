import { expect, test } from '@playwright/test'

test('the foundation page reaches the real backend through the Vite proxy', async ({ page, request }) => {
  const response = await request.get('/health/ready')
  expect(response.status()).toBe(200)
  expect(await response.json()).toEqual({ status: 'ready' })

  await page.goto('/')
  await expect(page.getByRole('main')).toBeVisible()
  await expect(page.getByRole('status')).toContainText('已连接')
  await page.getByRole('button', { name: '重新检查' }).click()
  await expect(page.getByRole('status')).toContainText('已连接')
})
