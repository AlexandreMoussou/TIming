import { defineConfig } from '@playwright/test';

// E2E contre le vrai serveur FastAPI et les vraies bases Aiven (ClickHouse, Postgres, Valkey).
// ANTHROPIC_API_KEY vidée : mode sans LLM, déterministe.
const PORT = 8094;
export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 60_000,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: `http://localhost:${PORT}`, viewport: { width: 1400, height: 900 } },
  webServer: {
    command: `python -m uvicorn app.main:app --port ${PORT}`,
    url: `http://localhost:${PORT}/api/health`,
    timeout: 60_000,
    reuseExistingServer: false,
    env: { ANTHROPIC_API_KEY: '' },
  },
});
