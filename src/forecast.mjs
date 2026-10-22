// Short-horizon station forecast. Pure functions, shared by the live agent and
// the offline benchmark so both measure exactly the same model.
//
// pred(t+H) = bikes_now + k * rate * H + bias_station
//   rate  : least-squares slope of bikes over the last WINDOW minutes (bikes/min)
//   k     : global damping factor learned online from resolved predictions
//   bias  : per-station correction learned online (shrunk toward 0 when n is small)

export const DEFAULTS = {
  horizonMin: Number(process.env.HORIZON_MIN || 30),
  windowMin: Number(process.env.WINDOW_MIN || 20),
};

export function slopePerMin(points) {
  // points: [{ t: unix seconds, bikes }]
  const n = points.length;
  if (n < 3) return 0;
  const t0 = points[0].t;
  let sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (const p of points) {
    const x = (p.t - t0) / 60;
    sx += x; sy += p.bikes; sxx += x * x; sxy += x * p.bikes;
  }
  const den = n * sxx - sx * sx;
  return den === 0 ? 0 : (n * sxy - sx * sy) / den;
}

export function shrunkBias(b) {
  return b ? (b.bias * b.n) / (b.n + 5) : 0;
}

export function forecastStation({ bikes, docks, history, k = 1, bias = 0, horizonMin = DEFAULTS.horizonMin }) {
  const rate = slopePerMin(history);
  const cap = bikes + docks; // effective capacity (broken docks excluded)
  const drift = k * rate;
  const predicted = clamp(bikes + drift * horizonMin + bias, 0, cap);
  const minutesToEmpty = bikes === 0 ? 0 : drift < -1e-6 ? bikes / -drift : Infinity;
  const minutesToFull = docks === 0 ? 0 : drift > 1e-6 ? docks / drift : Infinity;
  return { rate, predicted, minutesToEmpty, minutesToFull, cap };
}

function clamp(x, lo, hi) {
  return Math.max(lo, Math.min(hi, x));
}

// Online learner. State is persisted in Postgres between agent runs.
export function updateDamping(params, samples) {
  // Least squares on (actual - now - bias) ≈ k * (rate * H), exponentially decayed.
  let { sxy = 0, sxx = 0, n = 0 } = params;
  const decay = 0.995;
  for (const s of samples) {
    const x = s.rate * s.horizonMin;
    const y = s.actual - s.now - (s.bias || 0);
    sxy = sxy * decay + x * y;
    sxx = sxx * decay + x * x;
    n += 1;
  }
  const k = sxx > 1e-9 ? clamp(sxy / sxx, 0, 1.5) : 1;
  return { sxy, sxx, n, k };
}

export function updateBias(prev, residual, alpha = 0.2) {
  if (!prev) return { bias: residual, n: 1 };
  return { bias: prev.bias + alpha * (residual - prev.bias), n: prev.n + 1 };
}
