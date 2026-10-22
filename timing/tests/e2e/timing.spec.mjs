import { test, expect } from '@playwright/test';

const uniq = () => `e2e-${Date.now()}-${Math.floor(Math.random() * 1e4)}`;

test('les trois bases Aiven répondent', async ({ page, request }) => {
  const h = await (await request.get('/api/health')).json();
  expect(h).toMatchObject({ ok: true, clickhouse: 'up', postgres: 'up', valkey: 'up' });
  await page.goto('/');
  await expect(page.getByTestId('status')).toContainText('données en ligne');
  await expect(page.locator('footer')).toContainText('lignes DVF');
});

test('le formulaire est fait de cases, sans champ de texte libre', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('textarea')).toHaveCount(0);
  await expect(page.locator('form input[type="text"], form input:not([type])')).toHaveCount(1); // le pseudo seulement
  await page.getByTestId('typo-t2').click();
  await expect(page.getByTestId('typo-t2')).toHaveClass(/on/);
  await page.getByTestId('intent-acheter').click();
  await expect(page.getByTestId('budget-value')).toContainText('400');
});

test('location studio : fenêtre, calendrier, arrondissements, événements, trace', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/Cherche en .* 20\d\d/);
  await expect(page.getByTestId('advice')).toContainText(/studio/i);
  // chaque chiffre de la réponse doit être retrouvé dans les sorties d'outils
  const g = await page.getByTestId('grounding').textContent();
  const [ok, total] = g.match(/(\d+)\/(\d+)/).slice(1).map(Number);
  expect(total).toBeGreaterThan(0);
  expect(ok).toBe(total);
  await expect(page.getByTestId('chart')).toBeVisible();
  await expect(page.getByTestId('rank-card')).toHaveCount(12);
  await expect(page.getByTestId('ranking')).toContainText('dans le budget');
  await expect(page.getByTestId('events')).toContainText('Rush de la rentrée');
  await page.getByTestId('trace').locator('summary').click();
  expect(await page.getByTestId('trace-step').count()).toBeGreaterThanOrEqual(8);
  for (const agent of ['intake', 'analyst', 'events', 'advisor']) await expect(page.getByTestId('trace')).toContainText(agent);
});

test('mémoire : la 2e recherche se souvient de la 1re', async ({ page }) => {
  const handle = uniq();
  await page.goto('/');
  await page.getByTestId('handle').fill(handle);
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/20\d\d/);
  await page.getByTestId('typo-t2').click();
  await page.getByTestId('go').click();
  await expect(page.getByTestId('memory')).toContainText('Je me souviens');
  await expect(page.getByTestId('advice')).toContainText('T2');
});

test('alerte enregistrée dans Postgres pour le pseudo', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('handle').fill(uniq());
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/20\d\d/);
  await page.getByTestId('alert').click();
  await expect(page.getByTestId('alert-msg')).toContainText('alerte enregistrée');
});

test('achat T2 dans le 11e : classement en prix de vente', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('intent-acheter').click();
  await page.getByTestId('typo-t2').click();
  await page.getByTestId('zone').selectOption('75111');
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/compromis .* 20\d\d/);
  await expect(page.locator('#rank-sub')).toContainText('Prix estimé');
  await expect(page.getByTestId('rank-card').first()).toContainText('€/m²');
});

test('la trace du run est persistée et relisible via l\'API', async ({ request }) => {
  const r = await (await request.post('/api/recommend', { data: {
    intent: 'louer', typology: 'studio_t1', zone: '75', move_in: '2027-09-01', budget: 800, today: '2026-10-22' } })).json();
  expect(r.window.best.label).toMatch(/2027/);
  const run = await (await request.get(`/api/runs/${r.run_id}`)).json();
  expect(run.steps.length).toBe(r.trace.length);
  expect(run.steps.map((s) => s.tool)).toEqual(expect.arrayContaining(['compute_window', 'rank_neighbourhoods', 'get_upcoming_events']));
});

test('mobile : pas de défilement horizontal', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByTestId('go').click();
  await expect(page.getByTestId('window')).toContainText(/20\d\d/);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
