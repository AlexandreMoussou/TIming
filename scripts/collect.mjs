// Standalone recorder: polls the live Vélib GBFS feed every 60 s and stores
// compact snapshots on disk. These files are the raw ground truth used to
// backfill Postgres and to replay the benchmark.
import { mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { join } from 'node:path';
import { fetchStatus, fetchInformation } from '../src/gbfs.mjs';

const dir = process.env.SNAPSHOT_DIR || 'data/snapshots';
const intervalMs = Number(process.env.COLLECT_INTERVAL_MS || 60_000);
mkdirSync(dir, { recursive: true });

async function tick() {
  try {
    const snap = await fetchStatus();
    const file = join(dir, `status_${snap.fetchedAt}.json.gz`);
    writeFileSync(file, gzipSync(JSON.stringify(snap)));
    const infoFile = join(dir, 'station_information.json');
    if (!existsSync(infoFile) || new Date().getMinutes() === 0) {
      writeFileSync(infoFile, JSON.stringify(await fetchInformation()));
    }
    console.log(new Date().toISOString(), 'snapshot', snap.stations.length, 'stations');
  } catch (err) {
    console.error(new Date().toISOString(), 'collect failed:', err.message);
  }
}

await tick();
setInterval(tick, intervalMs);
