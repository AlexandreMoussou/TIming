// Data layer. Production: Aiven for PostgreSQL via DATABASE_URL.
// Local dev / tests without DATABASE_URL: PGlite (real Postgres compiled to WASM),
// so the exact same SQL runs in both cases.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const schemaSql = readFileSync(fileURLToPath(new URL('./schema.sql', import.meta.url)), 'utf8');

export async function openDb({ url = process.env.DATABASE_URL, pgliteDir = process.env.PGLITE_DIR } = {}) {
  let db;
  if (url) {
    const { default: pg } = await import('pg');
    const pool = new pg.Pool({
      connectionString: url.replace(/[?&]sslmode=[^&]*/, ''),
      ssl: process.env.DATABASE_CA ? { ca: process.env.DATABASE_CA } : { rejectUnauthorized: false },
      max: 5,
    });
    db = {
      kind: 'postgres',
      query: async (sql, params = []) => (await pool.query(sql, params)).rows,
      exec: async (sql) => { await pool.query(sql); },
      close: () => pool.end(),
    };
  } else {
    const { PGlite } = await import('@electric-sql/pglite');
    const lite = new PGlite(pgliteDir || undefined);
    db = {
      kind: 'pglite',
      query: async (sql, params = []) => (await lite.query(sql, params)).rows,
      exec: async (sql) => { await lite.exec(sql); },
      close: () => lite.close(),
    };
  }
  await db.exec(schemaSql);
  return db;
}

// Bulk insert of one snapshot (one row per station) using unnest for speed.
export async function insertSnapshot(db, snap) {
  const s = snap.stations;
  await db.query(
    `INSERT INTO snapshots (ts, station_id, bikes, mechanical, ebike, docks, is_renting, is_returning)
     SELECT to_timestamp($1), * FROM unnest($2::text[], $3::int[], $4::int[], $5::int[], $6::int[], $7::bool[], $8::bool[])
     ON CONFLICT DO NOTHING`,
    [snap.fetchedAt, s.map((x) => x.id), s.map((x) => x.bikes), s.map((x) => x.mechanical),
      s.map((x) => x.ebike), s.map((x) => x.docks), s.map((x) => x.renting), s.map((x) => x.returning)],
  );
}

export async function upsertStations(db, info) {
  await db.query(
    `INSERT INTO stations (id, code, name, lat, lon, capacity)
     SELECT * FROM unnest($1::text[], $2::text[], $3::text[], $4::float8[], $5::float8[], $6::int[])
     ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, lat = EXCLUDED.lat, lon = EXCLUDED.lon, capacity = EXCLUDED.capacity`,
    [info.map((x) => x.id), info.map((x) => x.code), info.map((x) => x.name),
      info.map((x) => x.lat), info.map((x) => x.lon), info.map((x) => x.capacity)],
  );
}
