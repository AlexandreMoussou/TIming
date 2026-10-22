// Copies the first N recorded real snapshots into tests/fixtures/replay so the
// end-to-end tests run offline and deterministically on real Vélib data.
import { mkdirSync, copyFileSync, rmSync } from 'node:fs';
import { basename, join } from 'node:path';
import { listSnapshotFiles } from '../src/snapshots.mjs';

const src = process.argv[2] || 'data/snapshots';
const n = Number(process.argv[3] || 25);
const out = 'tests/fixtures/replay';
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
const files = listSnapshotFiles(src).slice(0, n);
for (const f of files) copyFileSync(f, join(out, basename(f)));
copyFileSync(join(src, 'station_information.json'), join(out, 'station_information.json'));
console.log(`fixture: ${files.length} snapshots -> ${out}`);
