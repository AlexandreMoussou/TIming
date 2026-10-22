import { test, expect } from '@playwright/test';

const uniq = () => `e2e-${Date.now()}-${Math.floor(Math.random() * 1e4)}`;

test('les trois bases Aiven répondent', async ({ page, request }) => {
  const h = await (await request.get('/api/health')).json();
  expect(h).toMatchObject({ ok: true, clickhouse: 'up', postgres: 'up', valkey: 'up' });
  await page.goto('/');
  await expect(page.getByTestId('status')).toContainText('ClickHouse up');
  await expect(page.locator('footer')).toContainText('lignes DVF');
});

test('location studio : fenêtre, graphique, classement, événements, trace', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/2027/);
  await expect(page.getByTestId('advice')).toContainText(/studio/i);
  // chaque chiffre de la réponse doit être retrouvé dans les sorties d'outils
  const g = await page.getByTestId('grounding').textContent();
  const [ok, total] = g.match(/(\d+)\/(\d+)/).slice(1).map(Number);
  expect(total).toBeGreaterThan(0);
  expect(ok).toBe(total);
  await expect(page.getByTestId('chart')).toBeVisible();
  await expect(page.getByTestId('ranking').locator('tbody tr')).toHaveCount(10);
  await expect(page.getByTestId('ranking')).toContainText('dans le budget');
  await expect(page.getByTestId('events')).toContainText('Rush de la rentrée');
  await page.getByTestId('trace').locator('summary').click();
  const steps = page.getByTestId('trace-step');
  expect(await steps.count()).toBeGreaterThanOrEqual(8);
  for (const agent of ['intake', 'analyst', 'events', 'advisor']) await expect(page.getByTestId('trace')).toContainText(agent);
});

test('mémoire : la 2e recherche se souvient de la 1re', async ({ page }) => {
  const handle = uniq();
  await page.goto('/');
  await page.getByTestId('handle').fill(handle);
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/2027/);
  await page.getByTestId('ask').fill('et pour un T2 ?');
  await page.getByTestId('go').click();
  await expect(page.locator('#memory')).toContainText('recherche(s) précédente(s)');
  await expect(page.getByTestId('advice')).toContainText('T2');
});

test('alerte enregistrée dans Postgres pour le pseudo', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('handle').fill(uniq());
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/2027/);
  await page.getByTestId('alert').click();
  await expect(page.getByTestId('alert-msg')).toContainText('alerte enregistrée');
});

test('achat T2 dans le 11e : classement en prix de vente', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Acheter' }).click();
  await page.getByTestId('ask').fill('Acheter un T2 pour septembre 2027');
  await page.getByTestId('zone').selectOption('75111');
  await page.getByTestId('typology').selectOption('t2');
  await page.locator('#budget').fill('450000');
  await page.getByTestId('go').click();
  await expect(page.getByTestId('advice')).toContainText('compromis');
  await expect(page.locator('#th-cost')).toHaveText('Prix estimé');
});

test('la trace du run est persistée et relisible via l\'API', async ({ request }) => {
  const r = await (await request.post('/api/recommend', { data: { text: 'studio à Paris pour septembre 2027, 800 €', today: '2026-10-22' } })).json();
  expect(r.window.best.label).toMatch(/2027/);
  const run = await (await request.get(`/api/runs/${r.run_id}`)).json();
  expect(run.steps.length).toBe(r.trace.length);
  expect(run.steps.map((s) => s.tool)).toEqual(expect.arrayContaining(['compute_window', 'rank_neighbourhoods', 'get_upcoming_events']));
});

test('mobile : pas de défilement horizontal', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/2027/);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
