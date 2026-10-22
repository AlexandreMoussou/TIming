// The Rebalance agent. One run = observe -> verify -> learn -> forecast ->
// detect -> plan -> brief -> persist. Every step is logged to agent_runs.steps
// so the UI (and the jury) can see exactly what the agent did and why.
import { forecastStation, updateDamping, updateBias, shrunkBias, DEFAULTS } from './forecast.mjs';
import { planMissions, FLEET } from './planner.mjs';
import { dispatcherBrief } from './llm.mjs';

export async function runAgent(db, { horizonMin = DEFAULTS.horizonMin, windowMin = DEFAULTS.windowMin, useLlm = true } = {}) {
  const steps = [];
  const step = async (name, fn) => {
    const t0 = Date.now();
    const out = await fn();
    steps.push({ name, ms: Date.now() - t0, ...out.log });
    return out.value;
  };

  // 1. OBSERVE — latest data in the warehouse
  const dataTs = await step('observe', async () => {
    const [r] = await db.query(`SELECT extract(epoch FROM max(ts))::float8 AS t, count(DISTINCT ts)::int AS n FROM snapshots`);
    if (!r.t) throw new Error('no snapshots yet');
    const [c] = await db.query(`SELECT count(*)::int AS n FROM snapshots WHERE ts = to_timestamp($1)`, [r.t]);
    return { value: r.t, log: { summary: `Dernier relevé ${new Date(r.t * 1000).toISOString()} : ${c.n} stations, ${r.n} relevés en base.` } };
  });

  // 2. VERIFY — resolve past predictions whose target time has passed
  const resolved = await step('verify', async () => {
    const rows = await db.query(
      `WITH due AS (
         SELECT p.run_id, p.station_id, p.target_ts, p.bikes_now, p.rate_per_min, p.predicted_bikes
         FROM predictions p WHERE p.actual_bikes IS NULL AND p.target_ts <= to_timestamp($1)
       )
       SELECT d.*, s.bikes AS actual
       FROM due d
       JOIN LATERAL (
         SELECT bikes FROM snapshots s
         WHERE s.station_id = d.station_id AND s.ts BETWEEN d.target_ts - interval '3 minutes' AND d.target_ts + interval '3 minutes'
         ORDER BY abs(extract(epoch FROM s.ts - d.target_ts)) LIMIT 1
       ) s ON true`,
      [dataTs],
    );
    if (rows.length) {
      await db.query(
        `UPDATE predictions p SET actual_bikes = u.actual, resolved_at = to_timestamp($1)
         FROM unnest($2::bigint[], $3::text[], $4::int[]) AS u(run_id, station_id, actual)
         WHERE p.run_id = u.run_id AND p.station_id = u.station_id`,
        [dataTs, rows.map((r) => r.run_id), rows.map((r) => r.station_id), rows.map((r) => r.actual)],
      );
    }
    const mae = (f) => rows.length ? rows.reduce((a, r) => a + Math.abs(f(r) - r.actual), 0) / rows.length : null;
    const maeAgent = mae((r) => r.predicted_bikes), maeNaive = mae((r) => r.bikes_now);
    return {
      value: rows,
      log: {
        summary: rows.length
          ? `${rows.length} prévisions passées vérifiées. Erreur moyenne agent ${maeAgent.toFixed(2)} vélo vs ${maeNaive.toFixed(2)} pour « rien ne change ».`
          : 'Aucune prévision arrivée à échéance pour l’instant.',
        resolved: rows.length, maeAgent, maeNaive,
      },
    };
  });

  // 3. LEARN — update damping k and per-station bias from the errors
  const learned = await step('learn', async () => {
    const params = Object.fromEntries((await db.query(`SELECT name, value, n FROM model_params`)).map((r) => [r.name, r]));
    const biasRows = await db.query(`SELECT station_id, bias, n FROM station_bias`);
    const biases = new Map(biasRows.map((r) => [r.station_id, { bias: r.bias, n: r.n }]));
    const kBefore = params.k ? params.k.value : 1;
    if (resolved.length) {
      const d = updateDamping(
        { sxy: params.k_sxy?.value, sxx: params.k_sxx?.value, n: params.k?.n },
        resolved.map((r) => ({ rate: r.rate_per_min, horizonMin, actual: r.actual, now: r.bikes_now, bias: shrunkBias(biases.get(r.station_id)) })),
      );
      for (const r of resolved) {
        const residual = r.actual - (r.bikes_now + d.k * r.rate_per_min * horizonMin);
        biases.set(r.station_id, updateBias(biases.get(r.station_id), residual));
      }
      await db.query(
        `INSERT INTO model_params (name, value, n, updated_at) VALUES
           ('k', $1, $4, to_timestamp($5)), ('k_sxy', $2, $4, to_timestamp($5)), ('k_sxx', $3, $4, to_timestamp($5))
         ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value, n = EXCLUDED.n, updated_at = EXCLUDED.updated_at`,
        [d.k, d.sxy, d.sxx, d.n, dataTs],
      );
      const ids = resolved.map((r) => r.station_id);
      await db.query(
        `INSERT INTO station_bias (station_id, bias, n, updated_at)
         SELECT u.id, u.b, u.n, to_timestamp($4) FROM unnest($1::text[], $2::float8[], $3::int[]) AS u(id, b, n)
         ON CONFLICT (station_id) DO UPDATE SET bias = EXCLUDED.bias, n = EXCLUDED.n, updated_at = EXCLUDED.updated_at`,
        [ids, ids.map((id) => biases.get(id).bias), ids.map((id) => biases.get(id).n), dataTs],
      );
      return { value: { k: d.k, biases, n: d.n }, log: { summary: `Facteur d’amortissement appris : k = ${kBefore.toFixed(2)} → ${d.k.toFixed(2)} (sur ${d.n} prévisions vérifiées). ${ids.length} corrections par station mises à jour.`, kBefore, kAfter: d.k, samples: d.n } };
    }
    return { value: { k: kBefore, biases, n: params.k?.n || 0 }, log: { summary: `Rien de nouveau à apprendre. k = ${kBefore.toFixed(2)}.`, kBefore, kAfter: kBefore, samples: params.k?.n || 0 } };
  });

  // 4. FORECAST — every station, horizon H
  const stations = await step('forecast', async () => {
    const rows = await db.query(
      `SELECT s.station_id, extract(epoch FROM s.ts)::float8 AS t, s.bikes, s.docks
       FROM snapshots s WHERE s.ts > to_timestamp($1) - make_interval(mins => $2) AND s.ts <= to_timestamp($1)
       ORDER BY s.station_id, s.ts`,
      [dataTs, windowMin],
    );
    const info = new Map((await db.query(`SELECT id, name, lat, lon, capacity FROM stations`)).map((r) => [r.id, r]));
    const byStation = new Map();
    for (const r of rows) {
      if (!byStation.has(r.station_id)) byStation.set(r.station_id, []);
      byStation.get(r.station_id).push(r);
    }
    const out = [];
    for (const [id, hist] of byStation) {
      const last = hist[hist.length - 1];
      const meta = info.get(id);
      if (!meta || last.t !== dataTs) continue;
      const bias = shrunkBias(learned.biases.get(id));
      const f = forecastStation({ bikes: last.bikes, docks: last.docks, history: hist, k: learned.k, bias, horizonMin });
      out.push({ id, name: meta.name, lat: meta.lat, lon: meta.lon, bikes: last.bikes, docks: last.docks, bias, ...f });
    }
    const willEmpty = out.filter((s) => s.bikes > 0 && s.minutesToEmpty <= horizonMin).length;
    const willFill = out.filter((s) => s.docks > 0 && s.minutesToFull <= horizonMin).length;
    return { value: out, log: { summary: `${out.length} stations prévues à +${horizonMin} min. ${willEmpty} vont se vider, ${willFill} vont se remplir.`, stations: out.length, willEmpty, willFill } };
  });

  // 5+6. DETECT + PLAN — truck missions (fleet is simulated)
  const plan = await step('plan', async () => {
    const p = planMissions(stations, FLEET);
    const n = p.trucks.reduce((a, t) => a + t.missions.length, 0);
    return { value: p, log: { summary: `${p.deficits.length} stations en déficit, ${p.surpluses.length} en excédent. ${n} missions sur ${p.trucks.length} camions (simulés), ~${p.totalAvoidedMinutes} min de station vide/pleine évitées.`, missions: n, avoidedMinutes: p.totalAvoidedMinutes } };
  });

  // 7. BRIEF — Claude reviews the plan with tools if a key is configured, else template
  const brief = await step('brief', async () => {
    const res = await dispatcherBrief({ stations, plan, learned, horizonMin, dataTs, enabled: useLlm });
    return { value: res, log: { summary: res.mode === 'llm' ? `Claude a revu le plan en ${res.toolCalls.length} appels d’outils.` : 'Résumé généré sans LLM (pas de clé API).', mode: res.mode, toolCalls: res.toolCalls } };
  });
  const finalPlan = brief.plan || plan;

  // 8. PERSIST — memory for the next runs
  const runId = await step('persist', async () => {
    const stats = { horizonMin, k: learned.k, stations: stations.length, missions: finalPlan.trucks.reduce((a, t) => a + t.missions.length, 0), avoidedMinutes: finalPlan.totalAvoidedMinutes, resolved: resolved.length };
    const [run] = await db.query(
      `INSERT INTO agent_runs (data_ts, mode, steps, brief, stats) VALUES (to_timestamp($1), $2, $3, $4, $5) RETURNING id`,
      [dataTs, brief.mode, JSON.stringify(steps), brief.text, JSON.stringify(stats)],
    );
    await db.query(
      `INSERT INTO predictions (run_id, station_id, made_at, target_ts, bikes_now, rate_per_min, predicted_bikes)
       SELECT $1, u.id, to_timestamp($2), to_timestamp($2) + make_interval(mins => $3), u.b, u.r, u.p
       FROM unnest($4::text[], $5::int[], $6::float8[], $7::float8[]) AS u(id, b, r, p)`,
      [run.id, dataTs, horizonMin, stations.map((s) => s.id), stations.map((s) => s.bikes), stations.map((s) => s.rate), stations.map((s) => s.predicted)],
    );
    for (const t of finalPlan.trucks) {
      for (const m of t.missions) {
        await db.query(
          `INSERT INTO missions (run_id, truck, seq, pickup_station, dropoff_station, bikes, km, avoided_minutes, reason)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
          [run.id, t.id, m.seq, m.pickup.id, m.dropoff.id, m.bikes, m.km, m.avoidedMinutes, m.reason],
        );
      }
    }
    return { value: run.id, log: { summary: `Run #${run.id} enregistré : ${stations.length} prévisions et ${stats.missions} missions en mémoire.` } };
  });

  return { runId, dataTs, steps, brief: brief.text, mode: brief.mode, plan: finalPlan, stations, k: learned.k };
}
