import { test, expect } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

test('health: replay mode on Postgres (PGlite), no LLM', async ({ request }) => {
  const h = await (await request.get('/api/health')).json();
  expect(h).toMatchObject({ ok: true, db: 'pglite', mode: 'replay', llm: false });
});

test('dashboard shows the live situation, the agent trace and truck missions', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('asof')).toContainText('Relevé');
  await expect(page.getByTestId('step')).toHaveCount(7);
  for (const name of ['Observer', 'Vérifier', 'Apprendre', 'Prévoir', 'Planifier', 'Expliquer', 'Mémoriser']) {
    await expect(page.getByTestId('steps')).toContainText(name);
  }
  await expect(page.getByTestId('steps')).toContainText('1519 stations');
  const missions = page.getByTestId('mission');
  const kpi = Number(await page.getByTestId('kpi-missions').textContent());
  expect(kpi).toBeGreaterThan(0);
  await expect(missions).toHaveCount(kpi);
  await expect(missions.first()).toContainText('→');
  await expect(page.getByTestId('brief')).toContainText('missions proposées');
  await expect(page.locator('.leaflet-container')).toBeVisible();
  await expect(page.getByText('Flotte de camions simulée')).toBeVisible();
  await expect(page.getByText('Données Vélib réelles (replay)')).toBeVisible();
  await missions.first().click(); // zooms the map on that mission
});

test('the agent verifies its past predictions and learns from them', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.getByTestId('step')).toHaveCount(7);
  const firstRun = await page.getByTestId('run-id').textContent();
  // Advance the replayed real feed by 5 min + run, twice: forecasts made earlier come due
  for (let i = 0; i < 2; i++) {
    await page.getByTestId('tick').click();
    await expect(page.getByTestId('tick')).toBeEnabled();
  }
  await expect(page.getByTestId('run-id')).not.toHaveText(firstRun);
  // Each tick advances 5 min = the test horizon, so every run verifies the previous one
  await expect(page.getByTestId('steps')).toContainText('prévisions passées vérifiées');
  await expect(page.getByTestId('steps')).toContainText('Facteur d’amortissement appris');
  await expect(page.getByTestId('learning-last')).toContainText('prévisions vérifiées');

  const runs = await (await request.get('/api/runs')).json();
  expect(runs.length).toBeGreaterThanOrEqual(3);
  const verify = runs[0].steps.find((s) => s.name === 'verify');
  expect(verify.resolved).toBeGreaterThan(1000);
  expect(verify.maeAgent).toBeGreaterThanOrEqual(0);
  const learn = runs[0].steps.find((s) => s.name === 'learn');
  expect(learn.samples).toBeGreaterThan(2000); // learned from two verified runs
});

test('API: state is consistent and missions respect the fleet', async ({ request }) => {
  const s = await (await request.get('/api/state')).json();
  expect(s.stations.length).toBe(1519);
  const ids = new Set(s.stations.map((x) => x.id));
  expect(s.trucks.length).toBe(s.fleet.depots.length);
  for (const t of s.trucks) {
    expect(t.missions.length).toBeLessThanOrEqual(3);
    for (const m of t.missions) {
      expect(ids.has(m.pickup.id) && ids.has(m.dropoff.id)).toBe(true);
      expect(m.pickup.id).not.toBe(m.dropoff.id);
      expect(m.bikes).toBeGreaterThan(0);
      expect(m.bikes).toBeLessThanOrEqual(s.fleet.capacity);
      expect(m.etaDropoffMin).toBeLessThanOrEqual(60);
    }
  }
  const risks = new Set(s.stations.map((x) => x.risk));
  expect([...risks].every((r) => ['ok', 'empty', 'full', 'will_empty', 'will_fill'].includes(r))).toBe(true);
});

test('manual "Lancer l’agent" creates a new persisted run', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('step')).toHaveCount(7);
  const before = Number((await page.getByTestId('run-id').textContent()).slice(1));
  await page.getByTestId('run-agent').click();
  await expect(page.getByTestId('run-id')).toHaveText(`#${before + 1}`);
});
