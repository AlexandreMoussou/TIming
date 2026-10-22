// Dispatcher-review step. With ANTHROPIC_API_KEY set, Claude inspects the
// forecast and the draft plan through tools, can drop suspicious stations and
// re-plan, then writes the dispatcher brief. Without a key, a deterministic
// template brief is produced so the product still works end to end.
import Anthropic from '@anthropic-ai/sdk';
import { planMissions, FLEET } from './planner.mjs';

const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-5-5';
const MAX_TURNS = 8;

const TOOLS = [
  {
    name: 'get_at_risk_stations',
    description: 'Stations predicted to become empty or full soon, with current bikes/docks, trend (bikes/min) and learned bias.',
    input_schema: { type: 'object', properties: { kind: { type: 'string', enum: ['empty', 'full'] }, limit: { type: 'integer' } }, required: ['kind'], additionalProperties: false },
  },
  {
    name: 'get_plan',
    description: 'Current draft truck plan (simulated fleet): missions per truck with pickup, drop-off, bikes, ETA and avoided minutes.',
    input_schema: { type: 'object', properties: {}, additionalProperties: false },
  },
  {
    name: 'replan_excluding',
    description: 'Recompute the truck plan excluding the given station ids (e.g. stations whose data look anomalous). Returns the new plan.',
    input_schema: { type: 'object', properties: { station_ids: { type: 'array', items: { type: 'string' } }, why: { type: 'string' } }, required: ['station_ids', 'why'], additionalProperties: false },
  },
  {
    name: 'submit_brief',
    description: 'Finish: submit the brief for the human dispatcher (French, max 120 words, concrete stations and times).',
    input_schema: { type: 'object', properties: { brief: { type: 'string' } }, required: ['brief'], additionalProperties: false },
  },
];

const SYSTEM = `Tu es l'assistant du régulateur Vélib' (Paris). Un modèle statistique a prévu l'état de chaque station et un planificateur a proposé des missions de camions (la flotte de camions est simulée).
Ton travail : vérifier le plan avec les outils, écarter les stations dont les données semblent anormales (ex. station qui ne loue pas, capacité effective très faible, tendance aberrante), re-planifier si nécessaire, puis appeler submit_brief.
Le brief est en français, 120 mots maximum, cite les stations et les horaires, et rappelle que les prévisions sont des estimations. Termine toujours par submit_brief.`;

export async function dispatcherBrief({ stations, plan, learned, horizonMin, dataTs, enabled }) {
  if (!enabled || !process.env.ANTHROPIC_API_KEY) return { mode: 'template', text: templateBrief(plan, learned, horizonMin), toolCalls: [] };
  try {
    return await llmBrief({ stations, plan, learned, horizonMin, dataTs });
  } catch (err) {
    return { mode: 'template', text: templateBrief(plan, learned, horizonMin) + ` (LLM indisponible : ${err.message})`, toolCalls: [] };
  }
}

async function llmBrief({ stations, plan, learned, horizonMin, dataTs }) {
  const client = new Anthropic();
  const byId = new Map(stations.map((s) => [s.id, s]));
  let current = plan;
  const excluded = [];
  const toolCalls = [];
  const slim = (s) => ({ id: s.id, name: s.name, bikes: s.bikes, docks: s.docks, trend_per_min: round2(s.rate), minutes_to_empty: fin(s.minutesToEmpty), minutes_to_full: fin(s.minutesToFull), learned_bias: round2(s.bias) });
  const run = (name, input) => {
    if (name === 'get_at_risk_stations') {
      const list = input.kind === 'empty' ? current.deficits : current.surpluses;
      return list.slice(0, input.limit || 15).map((s) => slim(byId.get(s.id) || s));
    }
    if (name === 'get_plan') return current.trucks;
    if (name === 'replan_excluding') {
      excluded.push(...input.station_ids);
      current = planMissions(stations, FLEET, { exclude: excluded });
      return { excluded, trucks: current.trucks, totalAvoidedMinutes: current.totalAvoidedMinutes };
    }
    return { error: `unknown tool ${name}` };
  };

  const messages = [{
    role: 'user',
    content: `Relevé du ${new Date(dataTs * 1000).toISOString()}. Horizon ${horizonMin} min. Facteur d'amortissement appris k=${learned.k.toFixed(2)} (${learned.n} prévisions vérifiées). Le plan propose ${current.trucks.reduce((a, t) => a + t.missions.length, 0)} missions. Vérifie et rédige le brief.`,
  }];

  for (let turn = 0; turn < MAX_TURNS; turn++) {
    const res = await client.beta.messages.create({
      model: MODEL,
      max_tokens: 16000,
      betas: ['server-side-fallback-2026-07-01'],
      fallbacks: 'default',
      output_config: { effort: 'low' },
      system: SYSTEM,
      tools: TOOLS,
      messages,
    });
    if (res.stop_reason === 'refusal') throw new Error('refusal');
    messages.push({ role: 'assistant', content: res.content });
    const uses = res.content.filter((b) => b.type === 'tool_use');
    if (!uses.length) break;
    const results = [];
    for (const u of uses) {
      if (u.name === 'submit_brief') {
        toolCalls.push({ tool: u.name });
        return { mode: 'llm', text: u.input.brief, toolCalls, plan: current, excluded };
      }
      const out = run(u.name, u.input);
      toolCalls.push({ tool: u.name, input: u.input });
      results.push({ type: 'tool_result', tool_use_id: u.id, content: JSON.stringify(out) });
    }
    messages.push({ role: 'user', content: results });
  }
  throw new Error('no brief submitted');
}

export function templateBrief(plan, learned, horizonMin) {
  const ms = plan.trucks.flatMap((t) => t.missions.map((m) => ({ t: t.id, ...m })));
  if (!ms.length) return `Aucune intervention urgente à +${horizonMin} min. Modèle : k = ${learned.k.toFixed(2)}.`;
  const lines = ms.slice(0, 4).map((m) => `Camion ${m.t} : ${m.bikes} vélos de ${m.pickup.name} vers ${m.dropoff.name} (arrivée +${m.etaDropoffMin} min).`);
  return `${ms.length} missions proposées, ~${plan.totalAvoidedMinutes} min de station vide/pleine évitées (estimation). ${lines.join(' ')} Modèle : k = ${learned.k.toFixed(2)}.`;
}

const round2 = (x) => Math.round(x * 100) / 100;
const fin = (x) => (Number.isFinite(x) ? Math.round(x) : null);
