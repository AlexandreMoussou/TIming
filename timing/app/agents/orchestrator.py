"""Orchestrateur multi-agents : intake → (analyst ∥ events) → advisor.

Avec ANTHROPIC_API_KEY, chaque agent est une boucle Claude tool use sur ses propres outils.
Sans clé, le même pipeline tourne en mode déterministe (mêmes outils, mêmes traces, texte gabarit) :
l'interface affiche le mode utilisé.
"""
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from app.agents.tools import MONTHS_FR, TOOL_FUNCS, TOOL_SCHEMAS
from app.config import ANTHROPIC_API_KEY
from app.db import postgres as pg

MODEL = "claude-sonnet-5-5"
ADVISOR_MODEL = "claude-sonnet-5-5"
# Pas de réflexion longue avant de répondre (latence de démo) ; le modèle raisonne entre les appels d'outils
THINK = {"type": "between_tools"}
TYPO_LABEL = {"studio_t1": "studio / T1", "t2": "T2", "t3plus": "T3 et plus"}

_llm = None


def llm():
    global _llm
    if _llm is None and ANTHROPIC_API_KEY:
        import anthropic
        _llm = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _llm


def _create(run, **kw):
    msg = llm().messages.create(thinking=THINK, **kw)
    with run.lock:
        run.tokens["input"] += msg.usage.input_tokens
        run.tokens["output"] += msg.usage.output_tokens
        run.llm_calls += 1
    return msg


class Run:
    def __init__(self):
        self.id = str(uuid.uuid4())
        self.step = 0
        self.trace = []
        self.tool_outputs = []
        self.tokens = {"input": 0, "output": 0}
        self.llm_calls = 0
        self.lock = threading.Lock()

    def log(self, agent, kind, tool=None, input=None, output=None, duration_ms=None):
        self.step += 1
        entry = {"step": self.step, "agent": agent, "kind": kind, "tool": tool, "input": input,
                 "output": output, "duration_ms": duration_ms, "at": time.time()}
        self.trace.append(entry)
        try:
            pg.fetch("""INSERT INTO agent_runs (run_id, step, agent, kind, tool, input, output, duration_ms)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (self.id, self.step, agent, kind, tool, pg.jsonb(input), pg.jsonb(_summary(output)), duration_ms))
        except Exception as e:  # la trace en mémoire reste disponible même si Postgres est indisponible
            entry["log_error"] = str(e)

    def call_tool(self, agent, name, args):
        t = time.time()
        self.log(agent, "tool_call", name, args)
        out = TOOL_FUNCS[name](args)
        ms = int((time.time() - t) * 1000)
        self.tool_outputs.append(out)
        self.log(agent, "tool_result", name, None, out, ms)
        return out


def _summary(out, limit=4000):
    s = json.dumps(out, default=str, ensure_ascii=False)
    return out if len(s) <= limit else {"truncated": s[:limit]}


# ---------- Intake ----------

ARR = re.compile(r"\b(\d{1,2})\s*(?:e|ème|eme|er)\b")
MONTH_RE = re.compile(r"(" + "|".join(MONTHS_FR) + r")\s+(\d{4})", re.I)


def intake_rules(text, defaults):
    t = text.lower()
    intent = "acheter" if re.search(r"achet|acqu", t) else "vendre" if "vend" in t else "louer"
    typology = ("studio_t1" if re.search(r"studio|t1\b|f1\b|chambre", t) else
                "t2" if re.search(r"t2\b|f2\b|2 pi", t) else
                "t3plus" if re.search(r"t3|t4|t5|f3|f4|3 pi|4 pi|famille", t) else defaults.get("typology"))
    m = ARR.search(t)
    zone = f"751{int(m.group(1)):02d}" if m and 1 <= int(m.group(1)) <= 20 else defaults.get("zone", "75")
    mm = MONTH_RE.search(t)
    move_in = (date(int(mm.group(2)), MONTHS_FR.index(mm.group(1).lower()) + 1, 1).isoformat()
               if mm else defaults.get("move_in"))
    b = re.search(r"(\d[\d\s]{2,})\s*(?:€|euros?|eur)", t)
    budget = int(re.sub(r"\s", "", b.group(1))) if b else defaults.get("budget")
    return {"intent": intent, "typology": typology or "studio_t1", "zone": zone, "move_in": move_in,
            "budget": budget}


def intake_llm(run, text, defaults, today):
    tool = {"name": "submit_params", "description": "Paramètres structurés de la demande.",
            "input_schema": {"type": "object", "properties": {
                "intent": {"type": "string", "enum": ["louer", "acheter", "vendre"]},
                "typology": {"type": "string", "enum": ["studio_t1", "t2", "t3plus"]},
                "zone": {"type": "string", "description": "'75' pour tout Paris, ou code INSEE 751xx d'un arrondissement"},
                "move_in": {"type": "string", "description": "YYYY-MM-DD, 1er du mois si seul le mois est donné"},
                "budget": {"type": ["number", "null"], "description": "loyer mensuel ou prix max en €"}},
                "required": ["intent", "typology", "zone", "move_in"]}}
    t = time.time()
    msg = _create(run, 
        model=MODEL, max_tokens=600, tools=[tool],
        system=(f"Tu es l'intake agent de Timing. Aujourd'hui : {today}. Extrais les paramètres de la demande "
                f"logement et appelle obligatoirement submit_params, sans texte. Mémoire de l'utilisateur "
                f"(à utiliser si un champ manque) : {json.dumps(defaults, ensure_ascii=False)}"),
        messages=[{"role": "user", "content": text}])
    params = next((b.input for b in msg.content if b.type == "tool_use"), None)
    if params is None:  # le modèle n'a pas appelé l'outil : repli sur l'analyse par règles
        params = intake_rules(text, defaults)
        run.log("intake", "rules", "parse_fallback", {"text": text}, params, int((time.time() - t) * 1000))
        return params
    run.log("intake", "llm", "submit_params", {"text": text}, params, int((time.time() - t) * 1000))
    return params


# ---------- Agents spécialistes (mode LLM) ----------

def agent_loop(run, agent, system, user, tools, max_turns=6, max_tokens=1500):
    """Boucle tool use : l'agent décide quels outils appeler et quand s'arrêter."""
    msgs = [{"role": "user", "content": user}]
    specs = [{"name": n, **TOOL_SCHEMAS[n]} for n in tools]
    for _ in range(max_turns):
        t = time.time()
        msg = _create(run, model=MODEL, max_tokens=max_tokens, system=system, tools=specs or [], messages=msgs) if specs else _create(run, model=MODEL, max_tokens=max_tokens, system=system, messages=msgs)
        text = " ".join(b.text for b in msg.content if b.type == "text")
        run.log(agent, "llm", None, None, {"text": text, "stop": msg.stop_reason}, int((time.time() - t) * 1000))
        if msg.stop_reason != "tool_use":
            return text
        msgs.append({"role": "assistant", "content": msg.content})
        results = []
        for b in msg.content:
            if b.type == "tool_use":
                try:
                    out = run.call_tool(agent, b.name, b.input)
                except Exception as e:
                    out = {"error": str(e)}
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(_summary(out, 12000), default=str, ensure_ascii=False)})
        msgs.append({"role": "user", "content": results})
    return text


# ---------- Pipeline ----------

def analyst(run, p, today):
    args = {"intent": p["intent"], "typology": p["typology"], "zone": p["zone"], "move_in": p["move_in"],
            "today": today}
    window = run.call_tool("analyst", "compute_window", args)
    ranking = run.call_tool("analyst", "rank_neighbourhoods",
                            {"typology": p["typology"], "budget": p.get("budget"), "zone": "75",
                             "intent": p["intent"]})
    note = None
    if llm():
        note = agent_loop(
            run, "analyst",
            "Tu es le market analyst agent de Timing. Tu as déjà la fenêtre et le classement. Si une comparaison "
            "manque (ex. arrondissement vs tout Paris), appelle get_seasonality une fois, puis résume en 3 phrases "
            "courtes les chiffres clés, texte brut. Ne cite que des chiffres renvoyés par les outils.",
            json.dumps({"params": p, "window_best": window.get("best"), "naive": window.get("naive"),
                        "top_ranking": ranking["ranking"][:5]}, default=str, ensure_ascii=False),
            ["get_seasonality"], max_turns=3, max_tokens=500)
    return {"window": window, "ranking": ranking, "note": note}


def events_agent(run, p, today):
    scope = "75"
    out = run.call_tool("events", "get_upcoming_events", {"start": today, "end": p["move_in"], "scope": scope})
    note = None
    if llm():
        note = agent_loop(
            run, "events",
            "Tu es l'events agent de Timing. À partir des événements fournis, identifie les 3 à 5 qui pèsent le plus "
            "sur la recherche de l'utilisateur (concurrence, offre, attentisme). Format : une ligne par événement, "
            "'nom (dates) : effet', 12 mots max par effet, texte brut sans markdown. Signale les dates 'à confirmer'.",
            json.dumps({"params": p, "events": [{k: x[k] for k in ("name", "start_date", "end_date", "expected_effect", "source")}
                                                 for x in out["events"]]}, default=str, ensure_ascii=False),
            [], max_turns=1, max_tokens=900)
    return {"events": out["events"], "note": note}


def window_dates(best, intent):
    y, m = best["year"], best["month"]
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return date(y, m, 1), date.fromordinal(nxt.toordinal() - 1)


def advisor_template(p, a, e):
    w = a["window"]
    if w.get("too_late"):
        return w["message"]
    b, n = w["best"], w["naive"]
    typ = TYPO_LABEL[p["typology"]]
    fits = [r for r in a["ranking"]["ranking"] if r["fits_budget"]][:3]
    zones = ", ".join(f"{r['nom'].replace('Paris ', '').replace(' Arrondissement', '')} (~{r['cost']:,} €)".replace(",", " ")
                      for r in fits)
    if p["intent"] == "louer":
        s = (f"Pour un {typ}, cherche en {b['label']} : le volume de logements qui changent de main y est à "
             f"{b['volume_vs_avg_pct']:+.0f} % de la moyenne annuelle")
        s += (f", contre {n['volume_vs_avg_pct']:+.0f} % en {n['label'].split(' (')[0]}" if b["label"].split()[0] !=
              n["label"].split()[0] else "")
        if b["competition_events"]:
            s += f". Concurrence à surveiller : {', '.join(x.rsplit(' ', 1)[0] for x in b['competition_events'])}"
    else:
        s = (f"Pour {p['intent']} un {typ}, vise un compromis en {b['label']} : prix au m² du mois de signature "
             f"{b['price_vs_year_pct']:+.1f} % vs la médiane de l'année, volume {b['volume_vs_avg_pct']:+.0f} %")
    if zones:
        s += f". Arrondissements dans ton budget : {zones}"
    elif p.get("budget"):
        cheap = a["ranking"]["ranking"][:2]
        s += (f". Aucun arrondissement n'entre dans {p['budget']} € pour ce type de bien ; les moins chers : "
              + ", ".join(f"{r['nom'].replace('Paris ', '').replace(' Arrondissement', '')} (~{r['cost']:,} €)".replace(",", " ")
                          for r in cheap))
    return s + "."


def advisor_llm(run, p, a, e, memory_note):
    t = time.time()
    payload = {"params": p, "window": {k: a["window"].get(k) for k in ("best", "naive", "gain_vs_naive", "method",
                                                                         "candidates", "too_late", "message")},
               "ranking": a["ranking"]["ranking"][:8], "analyst_note": a["note"], "events_note": e["note"],
               "events": [x["name"] for x in e["events"]][:30], "memory": memory_note}
    msg = _create(run, 
        model=ADVISOR_MODEL, max_tokens=1500,
        system=("Tu es l'advisor agent de Timing, conseiller logement pour étudiants et jeunes actifs à Paris. "
                "Écris en français, tutoiement, 4 à 5 phrases courtes : quand chercher (fenêtre), pourquoi (chiffres), où "
                "(2-3 arrondissements dans le budget avec loyer estimé), quels événements surveiller. N'utilise QUE "
                "des chiffres présents dans les données fournies, arrondis à l'unité comme dans les données. Ne parle "
                "jamais de 'score'. Texte brut, sans markdown ni puces. Rappelle en fin de réponse que le volume de "
                "ventes DVF est un proxy de l'offre. Si une mémoire utilisateur est fournie, fais-y référence."),
        messages=[{"role": "user", "content": json.dumps(payload, default=str, ensure_ascii=False)}])
    text = " ".join(b.text for b in msg.content if b.type == "text").strip()
    run.log("advisor", "llm", None, None, {"text": text}, int((time.time() - t) * 1000))
    return text


def grounding(text, tool_outputs):
    """Part des nombres de la réponse qui apparaissent dans les sorties d'outils (même arrondis)."""
    text = re.sub(r"(?<=\d)[ \u202f\u00a0](?=\d{3}(?!\d))", "", text)  # 328 000 -> 328000
    text = re.sub(r"\b\d{1,2}(?:e|er|ème)\b", "", text)  # numéros d'arrondissement
    nums = {float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", text)}
    nums = {x for x in nums if not 1900 < x < 2100}  # années exclues
    pool = set()

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            pool.update({round(v), round(v, 1), round(abs(v)), round(abs(v), 1)})
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            for x in re.findall(r"\d+(?:\.\d+)?", v):
                pool.add(float(x))
    for o in tool_outputs:
        walk(o)
    ok = [x for x in nums if x in pool or round(x) in pool]
    return {"numbers": len(nums), "grounded": len(ok), "ungrounded": sorted(nums - set(ok))}


def get_user(handle):
    if not handle:
        return None, {}
    u = pg.fetch_one("""INSERT INTO users (handle) VALUES (%s) ON CONFLICT (handle) DO UPDATE SET handle = EXCLUDED.handle
                        RETURNING id, profile""", (handle,))
    return u["id"], u["profile"] or {}


def recommend(text, handle=None, today=None, overrides=None):
    run = Run()
    today = today or date.today().isoformat()
    t0 = time.time()
    user_id, profile = get_user(handle)
    past = pg.fetch("SELECT query_text, params, created_at FROM searches WHERE user_id = %s ORDER BY id DESC LIMIT 3",
                    (user_id,)) if user_id else []
    memory_note = None
    if past:
        memory_note = f"{len(past)} recherche(s) précédente(s), dernière : « {past[0]['query_text']} »"
        run.log("memory", "tool_result", "postgres.searches", {"user": handle},
                {"profile": profile, "past": [x["query_text"] for x in past]})
    mode = "llm" if llm() else "rules"
    p = intake_llm(run, text, profile, today) if mode == "llm" else intake_rules(text, profile)
    if mode == "rules":
        run.log("intake", "rules", "parse", {"text": text}, p)
    p.update({k: v for k, v in (overrides or {}).items() if v not in (None, "")})
    if not p.get("move_in"):
        p["move_in"] = date(date.fromisoformat(today).year + 1, 9, 1).isoformat()
    with ThreadPoolExecutor(2) as ex:  # analyst et events en parallèle
        fa = ex.submit(analyst, run, p, today)
        fe = ex.submit(events_agent, run, p, today)
        a, e = fa.result(), fe.result()
    advice = advisor_llm(run, p, a, e, memory_note) if mode == "llm" else advisor_template(p, a, e)
    if mode == "rules":
        run.log("advisor", "rules", "template", None, {"text": advice})
    g = grounding(advice, run.tool_outputs)
    run.log("advisor", "final", "grounding_check", None, g)
    w = a["window"]
    start, end = (window_dates(w["best"], p["intent"]) if not w.get("too_late") else (None, None))
    result = {
        "run_id": run.id, "mode": mode, "params": p, "advice": advice, "grounding": g, "memory": memory_note,
        "window": {"start": str(start) if start else None, "end": str(end) if end else None, **w},
        "ranking": a["ranking"], "events": e["events"], "notes": {"analyst": a["note"], "events": e["note"]},
        "latency_ms": int((time.time() - t0) * 1000), "trace": run.trace,
        "usage": {"llm_calls": run.llm_calls, **run.tokens, "tool_calls": len(run.tool_outputs)},
    }
    try:
        s = pg.fetch_one("INSERT INTO searches (user_id, query_text, params) VALUES (%s,%s,%s) RETURNING id",
                         (user_id, text, pg.jsonb(p)))
        rec = pg.fetch_one("""INSERT INTO recommendations (search_id, window_start, window_end, payload)
                              VALUES (%s,%s,%s,%s) RETURNING id""",
                           (s["id"], start, end, pg.jsonb({k: v for k, v in result.items() if k != "trace"})))
        result["recommendation_id"] = rec["id"]
        if user_id:
            pg.fetch("UPDATE users SET profile = profile || %s WHERE id = %s RETURNING id",
                     (pg.jsonb({k: p[k] for k in ("typology", "budget", "zone", "move_in", "intent") if p.get(k)}), user_id))
    except Exception as ex:
        result["persist_error"] = str(ex)
    return result
