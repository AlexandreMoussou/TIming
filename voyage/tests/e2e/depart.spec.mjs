import { test, expect } from '@playwright/test';

const uniq = () => `e2e-${Date.now()}-${Math.floor(Math.random() * 1e4)}`;

test('les bases Aiven répondent et la page se charge sans erreur', async ({ page, request }) => {
  const h = await (await request.get('/api/health')).json();
  expect(h).toMatchObject({ ok: true, clickhouse: 'up', postgres: 'up', valkey: 'up' });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/');
  await expect(page.locator('h1')).toHaveText('Pars au bon moment.');
  await expect(page.getByTestId('destination').locator('option')).not.toHaveCount(0);
  expect(errors).toEqual([]);
});

test("les chiffres d'accueil viennent des données", async ({ page, request }) => {
  const d = await (await request.get('/api/insights')).json();
  await page.goto('/');
  await page.locator('#numbers').scrollIntoViewIfNeeded();
  const expected = `+${Math.round(d.avion.max.price_vs_year_pct)} %`;
  await expect(page.locator('[data-count="air-max"]')).toHaveText(expected, { timeout: 5000 });
  await expect(page.locator('#air-max-m')).toHaveText(d.avion.max.name);
});

test('train vers Lyon en juillet : meilleur mois, trajet, frise, trace', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/Pars en .* 20\d\d\./);
  const g = await page.getByTestId('grounding').textContent();
  const [ok, total] = g.match(/(\d+)\/(\d+)/).slice(1).map(Number);
  expect(total).toBeGreaterThan(0);
  expect(ok).toBe(total);
  await expect(page.getByTestId('tl-month')).toHaveCount(5);
  await expect(page.locator('.mc.best')).toHaveCount(1);
  await expect(page.locator('.mc.target')).toHaveCount(1);
  await expect(page.getByTestId('route')).toContainText('€');
  await expect(page.getByTestId('calendar').locator('li').first()).toBeVisible();
  await page.getByTestId('trace').locator('summary').click();
  for (const agent of ['intake', 'analyst', 'calendar', 'advisor']) await expect(page.getByTestId('trace')).toContainText(agent);
});

test("avion flexible vers l'étranger : 12 mois, pas de carte trajet", async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('mode-avion').click();
  await page.getByTestId('air-international').click();
  await page.getByTestId('when-flex').click();
  await expect(page.getByTestId('months')).toBeHidden();
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/Pars en/);
  await expect(page.getByTestId('tl-month')).toHaveCount(12);
  await expect(page.getByTestId('route')).toBeHidden();
});

test('mémoire : la 2e recherche se souvient de la 1re', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('handle').fill(uniq());
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/Pars en/);
  await page.getByTestId('mode-avion').click();
  await page.getByTestId('go').click();
  await expect(page.getByTestId('memory')).toContainText('Je me souviens');
});

test("la trace est persistée et relisible via l'API", async ({ request }) => {
  const r = await (await request.post('/api/recommend', { data: { mode: 'train', destination: 'BORDEAUX ST JEAN', travel_month: '2027-07-01', today: '2026-10-22' } })).json();
  expect(r.window.best.label).toMatch(/2027/);
  const run = await (await request.get(`/api/runs/${r.run_id}`)).json();
  expect(run.steps.length).toBe(r.trace.length);
  expect(run.steps.map((s) => s.tool)).toEqual(expect.arrayContaining(['compute_travel_window', 'get_route', 'get_calendar']));
});

test('mobile : pas de défilement horizontal', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/Pars en/);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
