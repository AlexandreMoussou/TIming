// HTTP server + schedulers. Live mode polls the Vélib feed every minute and runs
// the agent every AGENT_EVERY_MIN minutes. Replay mode (REPLAY_DIR) feeds recorded
// snapshots one by one, used by the end-to-end tests and offline demos.
import { createServer } from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import { extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { openDb, insertSnapshot, upsertStations } from './db.mjs';
import { fetchStatus, fetchInformation } from './gbfs.mjs';
import { listSnapshotFiles, readSnapshot, readInformation } from './snapshots.mjs';
import { runAgent } from './agent.mjs';
import { FLEET } from './planner.mjs';
import { DEFAULTS } from './forecast.mjs';

const PORT = Number(process.env.PORT || 8080);
const REPLAY_DIR = process.env.REPLAY_DIR;
const SNAPSHOT_DIR = process.env.SNAPSHOT_DIR || 'data/snapshots';
const AUTO = process.env.AUTO !== '0';
const AGENT_EVERY_MIN = Number(process.env.AGENT_EVERY_MIN || 5);
const PUBLIC = fileURLToPath(new URL('../public/', import.meta.url));
const ROOT = fileURLToPath(new URL('../', import.meta.url));

const db = await openDb();
let last = null; // last agent result (in memory, for the map)
let busy = null;
let replayQueue = [];

async function agentOnce() {
  if (busy) return busy;
  busy = runAgent(db).then((r) => { last = r; return r; }).finally(() => { busy = null; });
  return busy;
}

async function boot() {
  if (REPLAY_DIR) {
    await upsertStations(db, readInformation(REPLAY_DIR));
    const files = listSnapshotFiles(REPLAY_DIR);
    const preload = Number(process.env.REPLAY_PRELOAD || Math.min(files.length, DEFAULTS.windowMin + 1));
    for (const f of files.slice(0, preload)) await insertSnapshot(db, readSnapshot(f));
    replayQueue = files.slice(preload);
    console.log(`replay: ${preload} snapshots preloaded, ${replayQueue.length} queued`);
  } else {
    await upsertStations(db, await fetchInformation());
    // Backfill from the local recorder if present (local dev only).
    const files = existsSync(SNAPSHOT_DIR) ? listSnapshotFiles(SNAPSHOT_DIR) : [];
    for (const f of files) await insertSnapshot(db, readSnapshot(f));
    if (files.length) console.log(`backfilled ${files.length} recorded snapshots`);
    await ingestLive();
  }
  if (AUTO) {
    if (!REPLAY_DIR) setInterval(() => ingestLive().catch((e) => console.error('ingest', e.message)), 60_000);
    setInterval(() => agentOnce().catch((e) => console.error('agent', e.message)), AGENT_EVERY_MIN * 60_000);
  }
  await agentOnce().catch((e) => console.error('agent', e.message));
}

async function ingestLive() {
  const snap = await fetchStatus();
  await insertSnapshot(db, snap);
}

async function tick(n = 1) {
  let done = 0;
  while (done < n && replayQueue.length) { await insertSnapshot(db, readSnapshot(replayQueue.shift())); done++; }
  return { advanced: done, remaining: replayQueue.length };
}

function stationView(s) {
  const risk = s.bikes === 0 ? 'empty' : s.docks === 0 ? 'full'
    : s.minutesToEmpty <= DEFAULTS.horizonMin ? 'will_empty' : s.minutesToFull <= DEFAULTS.horizonMin ? 'will_fill' : 'ok';
  return { id: s.id, name: s.name, lat: s.lat, lon: s.lon, bikes: s.bikes, docks: s.docks,
    predicted: Math.round(s.predicted * 10) / 10, rate: Math.round(s.rate * 100) / 100,
    minutesToEmpty: Number.isFinite(s.minutesToEmpty) ? Math.round(s.minutesToEmpty) : null,
    minutesToFull: Number.isFinite(s.minutesToFull) ? Math.round(s.minutesToFull) : null, risk };
}

const routes = {
  'GET /api/health': async () => ({ ok: true, db: db.kind, mode: REPLAY_DIR ? 'replay' : 'live', llm: Boolean(process.env.ANTHROPIC_API_KEY) }),
  'GET /api/state': async () => {
    if (!last) await agentOnce();
    return {
      runId: last.runId, dataTs: last.dataTs, mode: last.mode, k: last.k, horizonMin: DEFAULTS.horizonMin,
      brief: last.brief, steps: last.steps, trucks: last.plan.trucks, fleet: FLEET,
      stations: last.stations.map(stationView),
    };
  },
  'POST /api/run': async () => {
    const r = await agentOnce();
    return { runId: r.runId, steps: r.steps, brief: r.brief };
  },
  'POST /api/tick': async (body) => {
    if (!REPLAY_DIR) throw Object.assign(new Error('tick only in replay mode'), { status: 400 });
    return tick(Number(body?.n || 1));
  },
  'GET /api/runs': async () => db.query(
    `SELECT id, extract(epoch FROM data_ts)::float8 AS data_ts, mode, stats, steps FROM agent_runs ORDER BY id DESC LIMIT 50`),
  'GET /api/benchmark': async () => {
    const f = join(ROOT, 'benchmarks', 'results.json');
    return existsSync(f) ? JSON.parse(readFileSync(f, 'utf8')) : { available: false };
  },
};

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' };

const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  const key = `${req.method} ${url.pathname}`;
  try {
    if (routes[key]) {
      let body = null;
      if (req.method === 'POST') {
        const chunks = [];
        for await (const c of req) chunks.push(c);
        body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString() || '{}') : {};
      }
      const out = await routes[key](body);
      res.writeHead(200, { 'content-type': 'application/json' });
      return res.end(JSON.stringify(out));
    }
    const file = join(PUBLIC, url.pathname === '/' ? 'index.html' : url.pathname.replace(/^\/+/, ''));
    if (file.startsWith(PUBLIC) && existsSync(file)) {
      res.writeHead(200, { 'content-type': MIME[extname(file)] || 'application/octet-stream' });
      return res.end(readFileSync(file));
    }
    res.writeHead(404).end('not found');
  } catch (err) {
    console.error(key, err);
    res.writeHead(err.status || 500, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: err.message }));
  }
});

server.listen(PORT, () => console.log(`Rebalance listening on :${PORT} (db=${db.kind}, ${REPLAY_DIR ? 'replay' : 'live'})`));
boot().catch((e) => console.error('boot failed', e));
