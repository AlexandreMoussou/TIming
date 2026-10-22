// Greedy truck dispatch: pair "about to be full" stations (pickup) with
// "about to be empty" stations (drop-off) to maximise empty/full minutes avoided
// per minute of truck time. The truck fleet itself is SIMULATED (positions,
// capacity, speed are assumptions shown in the UI).

export const FLEET = {
  capacity: Number(process.env.TRUCK_CAPACITY || 20),
  speedKmh: 15,
  handlingMin: 8,
  maxMissionsPerTruck: 3,
  windowMin: 60,
  depots: [
    { name: 'Dépôt Nord (simulé)', lat: 48.8966, lon: 2.3622 },
    { name: 'Dépôt Centre (simulé)', lat: 48.8566, lon: 2.3522 },
    { name: 'Dépôt Sud (simulé)', lat: 48.8226, lon: 2.3366 },
  ],
};

export function km(a, b) {
  const R = 6371, toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat), dLon = toRad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h)) * 1.3; // 1.3 = street-network detour factor
}

// stations: [{ id, name, lat, lon, bikes, docks, cap, minutesToEmpty, minutesToFull }]
export function riskLists(stations) {
  const deficits = stations
    .filter((s) => s.minutesToEmpty <= 45 && s.cap >= 8)
    .map((s) => ({ ...s, need: Math.max(1, Math.round(s.cap * 0.4) - s.bikes) }))
    .sort((a, b) => a.minutesToEmpty - b.minutesToEmpty)
    .slice(0, 40);
  const surpluses = stations
    .filter((s) => s.minutesToFull <= 45 && s.cap >= 8)
    .map((s) => ({ ...s, give: Math.max(1, s.bikes - Math.round(s.cap * 0.6)) }))
    .sort((a, b) => a.minutesToFull - b.minutesToFull)
    .slice(0, 40);
  return { deficits, surpluses };
}

// Minutes of "empty" (or "full") avoided in the window if the truck arrives at `arrival`.
function avoided(minutesToEvent, arrival, w) {
  const start = Math.max(minutesToEvent, arrival);
  return Math.max(0, w - start);
}

export function planMissions(stations, fleet = FLEET, { exclude = [] } = {}) {
  const banned = new Set(exclude);
  const { deficits, surpluses } = riskLists(stations.filter((s) => !banned.has(s.id)));
  const trucks = fleet.depots.map((d, i) => ({ id: i + 1, pos: d, clock: 0, missions: [] }));
  const usedS = new Set(), usedD = new Set();
  const minPerKm = 60 / fleet.speedKmh;

  for (let round = 0; round < fleet.maxMissionsPerTruck * trucks.length; round++) {
    let best = null;
    for (const t of trucks) {
      if (t.missions.length >= fleet.maxMissionsPerTruck) continue;
      for (const s of surpluses) {
        if (usedS.has(s.id)) continue;
        const toS = km(t.pos, s);
        const atS = t.clock + toS * minPerKm + fleet.handlingMin / 2;
        for (const d of deficits) {
          if (usedD.has(d.id) || d.id === s.id) continue;
          const sd = km(s, d);
          const atD = atS + sd * minPerKm + fleet.handlingMin / 2;
          if (atD > fleet.windowMin) continue;
          const value = avoided(d.minutesToEmpty, atD, fleet.windowMin) + avoided(s.minutesToFull, atS, fleet.windowMin);
          if (value <= 0) continue;
          const score = value / (atD - t.clock);
          if (!best || score > best.score) best = { t, s, d, toS, sd, atS, atD, value, score };
        }
      }
    }
    if (!best) break;
    const { t, s, d } = best;
    const bikes = Math.min(fleet.capacity, s.give, d.need, d.docks);
    usedS.add(s.id); usedD.add(d.id);
    t.missions.push({
      seq: t.missions.length + 1,
      pickup: pick(s), dropoff: pick(d),
      bikes: Math.max(1, bikes),
      km: round1(best.toS + best.sd),
      etaPickupMin: Math.round(best.atS),
      etaDropoffMin: Math.round(best.atD),
      avoidedMinutes: Math.round(best.value),
      reason: reasonText(s, d, best),
    });
    t.pos = d; t.clock = best.atD;
  }
  return {
    trucks: trucks.map((t) => ({ id: t.id, depot: fleet.depots[t.id - 1].name, missions: t.missions })),
    deficits, surpluses,
    totalAvoidedMinutes: trucks.reduce((a, t) => a + t.missions.reduce((b, m) => b + m.avoidedMinutes, 0), 0),
  };
}

function pick(s) {
  return { id: s.id, name: s.name, lat: s.lat, lon: s.lon, bikes: s.bikes, docks: s.docks,
    minutesToEmpty: finite(s.minutesToEmpty), minutesToFull: finite(s.minutesToFull), rate: s.rate };
}
const finite = (x) => (Number.isFinite(x) ? Math.round(x) : null);
const round1 = (x) => Math.round(x * 10) / 10;

function reasonText(s, d, b) {
  const fmt = (x) => (x === 0 ? 'déjà' : `dans ${Math.round(x)} min`);
  return `${s.name} sera pleine ${fmt(s.minutesToFull)} (${s.docks} places libres) ; ` +
    `${d.name} sera vide ${fmt(d.minutesToEmpty)} (${d.bikes} vélos). ` +
    `Arrivée prévue à +${Math.round(b.atD)} min, ${Math.round(b.value)} min de station vide/pleine évitées.`;
}
