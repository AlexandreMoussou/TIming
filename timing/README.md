# Timing

**The AI that tells students and young workers *when* and *where* to look for a flat in Paris, from 1.4 M real sales, rents and the city's calendar.**

Live app (Aiven Runtime): https://01a16333-5ca2-7cae-9130-3d31a4ac634f-8080.eur-1.aiven.app

Accel AI Innovate Paris, 22 October 2026.

## The problem

A student in Clermont-Ferrand who must move to Paris in September does not know when the market offers the most
choice and the least competition, nor which arrondissements fit a 900 € budget. Timing answers in one sentence,
with every number taken from the data.

## How it works

```
question ─► intake agent ─► ┌ market analyst agent ─ ClickHouse (DVF, rents, rent caps) + Valkey cache ┐ ─► advisor agent ─► answer
            (Postgres memory)└ events agent ────────── Postgres events (195 events, 2021-2027) ──────────┘     + grounding check
```

- 4 Claude agents (`claude-sonnet-5-5`, tool use), analyst and events in parallel; every LLM call and tool call is
  logged in `agent_runs` and shown under "Voir le raisonnement".
- Grounding check: every number in the advice is looked up in the tool outputs; the UI shows "N/N".
- Memory: profile and past searches per handle (Postgres); alerts and thumbs up/down feedback are stored.
- Without `ANTHROPIC_API_KEY` the same pipeline runs with rules and a template (shown as "Mode sans LLM").

Data layer details: [`submission/data_layer.txt`](submission/data_layer.txt).

## Evidence

[`benchmarks/RESULTS.md`](benchmarks/RESULTS.md)

- Out-of-sample backtest (2021-2025, 299 cases): for renting, the recommended month beats a random month of the
  realistic search window in 92.3 % of cases (+25.3 % volume). Against "search in September" it is a draw
  (50.5 %), on purpose: the rule avoids the student rush. For buying, the month gives no reliable price advantage,
  and we do not claim one.
- Same model with and without Timing's data, 20 questions: answers with every number found in the data:
  17/20 vs 0/20.

## What is real, what is assumed

- Real: DVF sales 2021–H1 2026 (Paris and inner suburbs), ad-based rent indicators 2022-2025, Paris rent caps,
  event calendar (dates not yet official are flagged "à confirmer").
- Proxy: monthly sale volume stands for housing turnover; it is not a count of rental listings.
- Assumption shown on screen: monthly rent = rent per m² × a typical surface (22 / 40 / 62 m²).

## Run it

```bash
pip install -r requirements.txt
# .env (repo root or timing/): AIVEN_PG_URI, AIVEN_CH_URI (https endpoint), AIVEN_VALKEY_URI, ANTHROPIC_API_KEY
python -m data.seed_events
python -m data.ingest --reset          # needs data/raw/ (DVF, carte des loyers, encadrement), ~1 min
python -m uvicorn app.main:app --port 8080
npx playwright test                    # 7 E2E tests against the local server and real Aiven databases
python -m benchmarks.backtest
python -m benchmarks.agent_vs_llm
```

Deploy: `python timing/deploy_aiven.py <repo url> <branch>` creates or updates the Aiven Runtime service.

## Components

FastAPI, clickhouse-connect, psycopg, redis-py, Anthropic SDK, Chart.js (MIT), Playwright (Apache-2.0).
Data under Licence Ouverte / Etalab. Built with the help of Claude Code.
