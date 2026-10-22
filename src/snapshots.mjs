// Read snapshots written by scripts/collect.mjs (status_<unix>.json.gz).
import { readdirSync, readFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { join } from 'node:path';

export function listSnapshotFiles(dir) {
  return readdirSync(dir)
    .filter((f) => /^status_\d+\.json\.gz$/.test(f))
    .sort((a, b) => Number(a.match(/\d+/)[0]) - Number(b.match(/\d+/)[0]))
    .map((f) => join(dir, f));
}

export function readSnapshot(file) {
  return JSON.parse(gunzipSync(readFileSync(file)).toString('utf8'));
}

export function readInformation(dir) {
  return JSON.parse(readFileSync(join(dir, 'station_information.json'), 'utf8'));
}
