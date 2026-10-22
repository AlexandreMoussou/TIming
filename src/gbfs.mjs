// Client for the official Vélib' Métropole GBFS open-data feed (no key needed).
const BASE = process.env.GBFS_BASE ||
  'https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole';

async function getJson(path) {
  const res = await fetch(`${BASE}/${path}`, { signal: AbortSignal.timeout(20_000) });
  if (!res.ok) throw new Error(`GBFS ${path} HTTP ${res.status}`);
  return res.json();
}

function typeCount(types, key) {
  const t = (types || []).find((x) => key in x);
  return t ? t[key] : 0;
}

// Returns { fetchedAt (unix s), feedUpdatedAt, stations: [compact rows] }
export async function fetchStatus() {
  const json = await getJson('station_status.json');
  return normalizeStatus(json, Math.floor(Date.now() / 1000));
}

export function normalizeStatus(json, fetchedAt) {
  return {
    fetchedAt,
    feedUpdatedAt: json.lastUpdatedOther ?? json.last_updated ?? fetchedAt,
    stations: json.data.stations.map((s) => ({
      id: String(s.station_id),
      bikes: s.num_bikes_available,
      mechanical: typeCount(s.num_bikes_available_types, 'mechanical'),
      ebike: typeCount(s.num_bikes_available_types, 'ebike'),
      docks: s.num_docks_available,
      renting: s.is_renting === 1,
      returning: s.is_returning === 1,
      lastReported: s.last_reported,
    })),
  };
}

export async function fetchInformation() {
  const json = await getJson('station_information.json');
  return json.data.stations.map((s) => ({
    id: String(s.station_id),
    code: s.stationCode,
    name: s.name,
    lat: s.lat,
    lon: s.lon,
    capacity: s.capacity,
  }));
}
