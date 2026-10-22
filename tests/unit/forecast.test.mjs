import { test } from 'node:test';
import assert from 'node:assert/strict';
import { slopePerMin, forecastStation, updateDamping, updateBias, shrunkBias } from '../../src/forecast.mjs';

const series = (bikes) => bikes.map((b, i) => ({ t: 1_000_000 + i * 60, bikes: b }));

test('slope of a station losing 1 bike every 2 minutes', () => {
  assert.equal(Math.round(slopePerMin(series([10, 9.5, 9, 8.5, 8])) * 100) / 100, -0.5);
});

test('slope needs at least 3 points', () => {
  assert.equal(slopePerMin(series([5, 4])), 0);
});

test('forecast predicts time to empty and clamps at 0', () => {
  const f = forecastStation({ bikes: 4, docks: 20, history: series([8, 7, 6, 5, 4]), horizonMin: 30 });
  assert.equal(Math.round(f.minutesToEmpty), 4);
  assert.equal(f.predicted, 0);
  assert.equal(f.minutesToFull, Infinity);
});

test('forecast predicts time to full', () => {
  const f = forecastStation({ bikes: 18, docks: 2, history: series([14, 15, 16, 17, 18]), horizonMin: 30 });
  assert.equal(Math.round(f.minutesToFull), 2);
  assert.equal(f.predicted, 20);
});

test('damping learns k < 1 when trends over-shoot', () => {
  // Trend says -1/min for 30 min (=-30) but reality only moved -15
  const samples = Array.from({ length: 50 }, () => ({ rate: -1, horizonMin: 30, now: 40, actual: 25 }));
  const d = updateDamping({}, samples);
  assert.ok(Math.abs(d.k - 0.5) < 1e-9, `k=${d.k}`);
});

test('per-station bias is learned and shrunk when few samples', () => {
  let b;
  for (let i = 0; i < 20; i++) b = updateBias(b, 3);
  assert.ok(Math.abs(b.bias - 3) < 1e-9);
  assert.ok(shrunkBias(b) > 2 && shrunkBias(b) < 3);
  assert.equal(shrunkBias(undefined), 0);
});
