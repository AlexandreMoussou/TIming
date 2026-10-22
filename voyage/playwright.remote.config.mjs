import { defineConfig } from '@playwright/test';
// Mêmes tests E2E contre l'app déployée sur Aiven Runtime (agents Claude actifs, réponses plus lentes)
export default defineConfig({
  testDir: 'tests/e2e', timeout: 120_000, workers: 1, reporter: [['list']],
  expect: { timeout: 60_000 },
  use: { baseURL: process.env.TIMING_URL || 'https://01a16375-1a1b-73cb-9a26-fb1059c94d09-8080.eur-1.aiven.app', viewport: { width: 1400, height: 900 } },
});
