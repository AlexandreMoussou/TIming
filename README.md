# 🚲 Rebalance

**The agent that warns a Vélib station will run empty 30 minutes before it does, and sends the right truck.**

Accel AI Innovate Paris (Future Founders), October 22, 2026.

## The problem

Vélib' runs about 1,500 stations. Every morning, residential neighbourhoods empty out and business districts fill up; in the evening it flips. An empty station means a lost trip. A full station means a user who can't drop off their bike. A handful of trucks moves bikes around, but today the dispatcher **reacts** to a live map: by the time a station shows red, it is already too late.

**User**: the dispatcher at the operations centre of a bike-share or scooter-share operator (Vélib', and any operator that publishes the GBFS standard, which is hundreds of cities worldwide).

## What the agent does (every 5 minutes, on real data)

| Step | What happens | Data |
|---|---|---|
| 1. Observe | Reads the latest Vélib reading (ingested every minute) | `snapshots` |
| 2. Verify | Compares its forecasts from 30 minutes ago with reality | `predictions` ⋈ `snapshots` |
| 3. Learn | Updates its damping factor k and its correction for each station | `model_params`, `station_bias` |
| 4. Forecast | Trend over the last 20 min × k + bias, giving each station's state at +30 min and its time to empty or full | `snapshots` |
| 5. Plan | Pairs stations about to be full with stations about to be empty, to maximize the minutes avoided per minute of truck time | — |
| 6. Explain | With `ANTHROPIC_API_KEY`, Claude reviews the plan through tools (`get_at_risk_stations`, `get_plan`, `replan_excluding`, `submit_brief`) and writes the brief. Without a key, a template brief is written | — |
| 7. Memorize | Run, step-by-step trace, ~1,500 forecasts and the missions | `agent_runs`, `predictions`, `missions` |

Details of the data layer: [`data_layer.txt`](data_layer.txt).

## What is real and what is simulated

- **Real**: the official Vélib' Métropole GBFS feed (open data, no key, no personal data), the forecasts, their verification and the learning.
- **Simulated**: the truck fleet (3 fictitious depots, 20 bikes per truck, 15 km/h). The interface says so.
- The forecasts are estimates, not guarantees. The "minutes avoided" figure is a planning estimate.

## Measured result

`npm run benchmark` replays the real recording (`data/snapshots`) and compares three methods at +30 min: the live map ("nothing changes"), raw trend, and the agent that learns online without any look-ahead. Results: [`benchmarks/results.md`](benchmarks/results.md) (also CSV and JSON).

## Running it

```bash
npm install
npm run collect          # recorder: one real snapshot per minute in data/snapshots (keep it running)
npm start                # http://localhost:8080 (PGlite if DATABASE_URL is missing)
npm run benchmark        # writes benchmarks/results.{md,csv,json}
npm test                 # unit tests
npx playwright install chromium && npm run test:e2e   # end-to-end on recorded real data
```

Environment variables: see [`.env.example`](.env.example). `DATABASE_URL` points to an Aiven for PostgreSQL service.

## Deploying on Aiven Runtime

1. Create an Aiven for PostgreSQL service in the Aiven project and copy its Service URI.
2. Create the Runtime app in the same project from this Git repo (`Containerfile` at the root, port 8080).
3. Set the environment variables: `DATABASE_URL` (and optionally `ANTHROPIC_API_KEY`).
4. On boot, the app creates its schema, ingests the feed every minute and runs the agent every 5 minutes.

## Tests

- `tests/unit`: forecast (slope, time to empty or full), learning (k, bias), planner.
- `tests/e2e` (Playwright): the real server in replay mode on recorded real Vélib snapshots (`tests/fixtures/replay`). It covers the agent trace and its 7 steps, the missions, the verification of past forecasts, the learning, the consistency of the API and runs persisted in Postgres (PGlite).

## Stack

Node.js 22+, Postgres (Aiven, or PGlite for local tests), Leaflet + CARTO/OpenStreetMap tiles, Anthropic SDK (optional), Playwright. No front-end framework.

## Component origins

Libraries: `pg` (MIT), `@electric-sql/pglite` (Apache-2.0 / PostgreSQL License), `@anthropic-ai/sdk` (MIT), `@playwright/test` (Apache-2.0), Leaflet (BSD-2-Clause). Data: Vélib' Métropole open data. Map: © OpenStreetMap contributors, © CARTO. Built with help from Claude Code.
