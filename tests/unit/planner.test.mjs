import { test } from 'node:test';
import assert from 'node:assert/strict';
import { planMissions, km, FLEET } from '../../src/planner.mjs';

const st = (id, lat, lon, bikes, docks, mE, mF) => ({ id, name: id, lat, lon, bikes, docks, cap: bikes + docks, rate: 0, minutesToEmpty: mE, minutesToFull: mF });

test('distance Châtelet -> Bastille is ~2-3 km with detour factor', () => {
  const d = km({ lat: 48.8584, lon: 2.3470 }, { lat: 48.8532, lon: 2.3691 });
  assert.ok(d > 1.5 && d < 3.5, `d=${d}`);
});

test('pairs a filling station with a nearby emptying station', () => {
  const stations = [
    st('full-soon', 48.857, 2.352, 25, 2, Infinity, 5),
    st('empty-soon', 48.860, 2.355, 2, 25, 6, Infinity),
    st('quiet', 48.85, 2.34, 10, 10, Infinity, Infinity),
  ];
  const p = planMissions(stations, FLEET);
  const ms = p.trucks.flatMap((t) => t.missions);
  assert.equal(ms.length, 1);
  assert.equal(ms[0].pickup.id, 'full-soon');
  assert.equal(ms[0].dropoff.id, 'empty-soon');
  assert.ok(ms[0].bikes >= 1 && ms[0].bikes <= FLEET.capacity);
  assert.ok(ms[0].avoidedMinutes > 0);
});

test('excluded stations are never used', () => {
  const stations = [st('a', 48.857, 2.352, 25, 2, Infinity, 5), st('b', 48.860, 2.355, 2, 25, 6, Infinity)];
  const p = planMissions(stations, FLEET, { exclude: ['b'] });
  assert.equal(p.trucks.flatMap((t) => t.missions).length, 0);
});

test('no mission when nothing is at risk', () => {
  const p = planMissions([st('q', 48.85, 2.34, 10, 10, Infinity, Infinity)], FLEET);
  assert.equal(p.totalAvoidedMinutes, 0);
});
