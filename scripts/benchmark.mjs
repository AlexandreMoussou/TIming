// Before/after benchmark on REAL recorded Vélib data (data/snapshots).
// Replays the recording in time order and compares, at each evaluation time t:
//   1. "Rien ne change"  : naive persistence (what a dispatcher sees on a live map)
//   2. Tendance brute    : trend extrapolation, no learning (k = 1, no bias)
//   3. Agent Rebalance   : trend + damping k + per-station bias learned ONLINE,
//                          only from predictions already resolved at time t (no look-ahead)
// Ground truth = the feed itself H minutes later.
import { writeFileSync, mkdirSync } from 'node:fs';
import { listSnapshotFiles, readSnapshot } from '../src/snapshots.mjs';
import { forecastStation, updateDamping, updateBias, shrunkBias } from '../src/forecast.mjs';

const dir = process.argv[2] || 'data/snapshots';
const outDir = process.argv[3] || 'benchmarks';
const H = Number(process.env.HORIZON_MIN || 30);
const W = Number(process.env.WINDOW_MIN || 20);
const STEP = Number(process.env.EVAL_EVERY_MIN || 5);

const files = listSnapshotFiles(dir);
const snaps = files.map((f) => {
  const s = readSnapshot(f);
  return { t: s.fetchedAt, by: new Map(s.stations.map((x) => [x.id, x])) };
});
if (snaps.length < 3) throw new Error(`need more snapshots in ${dir}`);
if ((snaps[snaps.length - 1].t - snaps[0].t) / 60 < W + H) throw new Error(`need at least ${W + H} min of recording (window + horizon)`);
const t0 = snaps[0].t, tEnd = snaps[snaps.length - 1].t;
console.log(`${snaps.length} snapshots, ${((tEnd - t0) / 60).toFixed(0)} min of real data, H=${H} W=${W}`);

const nearest = (t, tol = 180) => {
  let best = null;
  for (const s of snaps) if (Math.abs(s.t - t) <= tol && (!best || Math.abs(s.t - t) < Math.abs(best.t - t))) best = s;
  return best;
};

const methods = {
  naive: { label: 'Rien ne change (carte live)', stats: newStats() },
  trend: { label: 'Tendance brute (sans apprentissage)', stats: newStats() },
  agent: { label: 'Agent Rebalance (apprend en ligne)', stats: newStats() },
};
function newStats() { return { absErr: 0, n: 0, tp: 0, fp: 0, fn: 0, leads: [] }; }

// Online learner state (agent only)
let damp = { sxy: 0, sxx: 0, n: 0, k: 1 };
const biases = new Map();
const pending = []; // predictions waiting for their target time
const kTrace = [];

for (let t = t0 + W * 60; t + H * 60 <= tEnd + 60; t += STEP * 60) {
  const now = nearest(t, 90);
  const target = nearest(t + H * 60);
  if (!now || !target) continue;

  // Learn from every agent prediction whose target time has passed (causal).
  const due = pending.filter((p) => p.target <= now.t);
  if (due.length) {
    damp = updateDamping(damp, due.map((p) => ({ rate: p.rate, horizonMin: H, actual: p.actual, now: p.bikes, bias: shrunkBias(biases.get(p.id)) })));
    for (const p of due) biases.set(p.id, updateBias(biases.get(p.id), p.actual - (p.bikes + damp.k * p.rate * H)));
    pending.splice(0, pending.length, ...pending.filter((p) => p.target > now.t));
  }
  kTrace.push({ t: now.t, k: damp.k, learnedFrom: damp.n });

  const window = snaps.filter((s) => s.t > now.t - W * 60 && s.t <= now.t);
  const future = snaps.filter((s) => s.t > now.t && s.t <= target.t);

  for (const [id, cur] of now.by) {
    const tgt = target.by.get(id);
    if (!tgt || !cur.renting) continue;
    const hist = window.map((s) => s.by.get(id)).filter(Boolean).map((x, i) => ({ t: window[i].t, bikes: x.bikes }));
    // Ground truth: did the station hit 0 bikes within the horizon, and when?
    let emptyAt = null;
    for (const s of future) { const x = s.by.get(id); if (x && x.bikes === 0) { emptyAt = s.t; break; } }
    const becameEmpty = cur.bikes > 0 && emptyAt !== null;

    const preds = {
      naive: { predicted: cur.bikes, minutesToEmpty: cur.bikes === 0 ? 0 : Infinity },
      trend: forecastStation({ bikes: cur.bikes, docks: cur.docks, history: hist, k: 1, bias: 0, horizonMin: H }),
      agent: forecastStation({ bikes: cur.bikes, docks: cur.docks, history: hist, k: damp.k, bias: shrunkBias(biases.get(id)), horizonMin: H }),
    };
    for (const [name, p] of Object.entries(preds)) {
      const st = methods[name].stats;
      st.absErr += Math.abs(p.predicted - tgt.bikes); st.n++;
      if (cur.bikes === 0) continue; // event metrics only for stations not already empty
      const alarm = p.minutesToEmpty <= H;
      if (alarm && becameEmpty) { st.tp++; st.leads.push((emptyAt - now.t) / 60); }
      else if (alarm) st.fp++;
      else if (becameEmpty) st.fn++;
    }
    pending.push({ id, target: target.t, bikes: cur.bikes, rate: preds.agent.rate, actual: tgt.bikes });
  }
}

const median = (a) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y); return Math.round(s[Math.floor(s.length / 2)]); };
const results = Object.entries(methods).map(([key, m]) => {
  const s = m.stats;
  return {
    key, label: m.label, mae: s.absErr / s.n, samples: s.n,
    emptyRecall: s.tp / Math.max(1, s.tp + s.fn), emptyPrecision: s.tp / Math.max(1, s.tp + s.fp),
    truePositives: s.tp, falsePositives: s.fp, missed: s.fn, medianLeadMin: median(s.leads),
  };
});
const [naive, , agent] = results;
const summary = `Sur ${((tEnd - t0) / 60).toFixed(0)} min de données Vélib réelles (${new Date(t0 * 1000).toISOString().slice(0, 16)}Z → ${new Date(tEnd * 1000).toISOString().slice(11, 16)}Z), horizon ${H} min : ` +
  `l'agent détecte à l'avance ${(agent.emptyRecall * 100).toFixed(0)} % des stations qui vont se vider (la carte live : ${(naive.emptyRecall * 100).toFixed(0)} %), ` +
  `avec ${agent.medianLeadMin ?? '–'} min d'avance médiane et une précision de ${(agent.emptyPrecision * 100).toFixed(0)} %. ` +
  `Erreur moyenne sur le nombre de vélos : ${agent.mae.toFixed(2)} vs ${naive.mae.toFixed(2)} (${((1 - agent.mae / naive.mae) * 100).toFixed(1)} %). k appris = ${damp.k.toFixed(2)}.`;

mkdirSync(outDir, { recursive: true });
const payload = { generatedAt: new Date().toISOString(), horizonMin: H, windowMin: W, snapshots: snaps.length, from: t0, to: tEnd, methods: results, kTrace, summary };
writeFileSync(`${outDir}/results.json`, JSON.stringify(payload, null, 2));
writeFileSync(`${outDir}/results.csv`, ['method,mae_bikes,samples,empty_recall,empty_precision,true_pos,false_pos,missed,median_lead_min',
  ...results.map((r) => [r.key, r.mae.toFixed(4), r.samples, r.emptyRecall.toFixed(4), r.emptyPrecision.toFixed(4), r.truePositives, r.falsePositives, r.missed, r.medianLeadMin ?? ''].join(','))].join('\n') + '\n');
writeFileSync(`${outDir}/results.md`, `# Benchmark Rebalance (données réelles rejouées)\n\n${summary}\n\n` +
  '| Méthode | Erreur moy. (vélos) | Rappel « va se vider » | Précision | Avance médiane (min) | Échantillons |\n|---|---:|---:|---:|---:|---:|\n' +
  results.map((r) => `| ${r.label} | ${r.mae.toFixed(2)} | ${(r.emptyRecall * 100).toFixed(1)} % | ${(r.emptyPrecision * 100).toFixed(1)} % | ${r.medianLeadMin ?? '–'} | ${r.samples} |`).join('\n') +
  `\n\nProtocole : à chaque instant t (toutes les ${STEP} min), chaque méthode prévoit l'état de chaque station à t+${H} min à partir des ${W} dernières minutes seulement. ` +
  `La vérité terrain est le flux GBFS officiel enregistré. L'agent n'apprend que des prévisions déjà vérifiées à l'instant t (pas de fuite du futur). ` +
  `« Va se vider » = station avec au moins 1 vélo à t qui atteint 0 vélo avant t+${H} min.\n`);
console.log(summary);
