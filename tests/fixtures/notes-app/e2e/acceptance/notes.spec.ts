import { test, expect } from '@playwright/test';

test('AC-001: Added note appears in the list and is still there after reload', async ({ page }) => {
  const title = `Milk ${Date.now()}`;
  await page.goto('/');
  await page.getByLabel('Title').fill(title);
  await page.getByRole('button', { name: 'Add note' }).click();
  await expect(page.getByRole('listitem').filter({ hasText: title })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('listitem').filter({ hasText: title })).toBeVisible();
});

test('AC-002: Empty title shows "Title is required"', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Add note' }).click();
  await expect(page.getByRole('alert')).toHaveText('Title is required');
});

test('AC-003: GET /api/notes returns the seeded note', async ({ request }) => {
  const res = await request.get('/api/notes');
  expect(res.status()).toBe(200);
  expect((await res.json()).map((n: { title: string }) => n.title)).toContain('Welcome');
});
