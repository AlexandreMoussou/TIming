import { defineConfig } from '@playwright/test';

// E2E runs the real server against recorded real Vélib snapshots (replay mode),
// with an in-process Postgres (PGlite) and no LLM key, so it is deterministic.
// Short horizon (5 min) so that predictions get verified within the fixture.
const PORT = 8092;
export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 90_000,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: `http://localhost:${PORT}`, viewport: { width: 1400, height: 900 } },
  webServer: {
    command: 'node src/server.mjs',
    url: `http://localhost:${PORT}/api/health`,
    timeout: 120_000,
    reuseExistingServer: false,
    env: {
      PORT: String(PORT), REPLAY_DIR: 'tests/fixtures/replay', REPLAY_PRELOAD: '6', AUTO: '0',
      HORIZON_MIN: '5', WINDOW_MIN: '5', ANTHROPIC_API_KEY: '', DATABASE_URL: '',
    },
  },
});
