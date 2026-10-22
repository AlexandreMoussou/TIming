"""Orchestrateur Départ : intake → (analyst ∥ calendar) → advisor.

Avec ANTHROPIC_API_KEY, analyst, calendar et advisor sont des appels Claude (tool use pour l'analyst) ; sans clé,
le même pipeline tourne avec un texte gabarit. Chaque étape est tracée dans vg_agent_runs.
"""
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from app.agents.fares import airport, fare_date
from app.agents.tools import MONTHS_FR, TOOL_FUNCS, TOOL_SCHEMAS, list_air_destinations
from app.config import ANTHROPIC_API_KEY
from app.db import postgres as pg

MODEL = "claude-sonnet-5-5"
THINK = {"type": "between_tools"}  # pas de longue réflexion avant de répondre : latence de démo

_llm = None


def llm():
    global _llm
    if _llm is None and ANTHROPIC_API_KEY:
        import anthropic
        _llm = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _llm


def _summary(out, limit=4000):
    s = json.dumps(out, default=str, ensure_ascii=False)
    return out if len(s) <= limit else {"truncated": s[:limit]}


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
        with self.lock:
            self.step += 1
            step = self.step
        entry = {"step": step, "agent": agent, "kind": kind, "tool": tool, "input": input, "output": output,
                 "duration_ms": duration_ms}
        self.trace.append(entry)
        try:
            pg.fetch("""INSERT INTO vg_agent_runs (run_id, step, agent, kind, tool, input, output, duration_ms)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (self.id, step, agent, kind, tool, pg.jsonb(input), pg.jsonb(_summary(output)), duration_ms))
        except Exception as e:
            entry["log_error"] = str(e)

    def call_tool(self, agent, name, args):
        t = time.time()
        self.log(agent, "tool_call", name, args)
        out = TOOL_FUNCS[name](args)
        self.tool_outputs.append(out)
        self.log(agent, "tool_result", name, None, out, int((time.time() - t) * 1000))
        return out

    def create(self, **kw):
        msg = llm().messages.create(thinking=THINK, **kw)
        with self.lock:
            self.tokens["input"] += msg.usage.input_tokens
            self.tokens["output"] += msg.usage.output_tokens
            self.llm_calls += 1
        return msg


def agent_loop(run, agent, system, user, tools, max_turns=3, max_tokens=700):
    msgs = [{"role": "user", "content": user}]
    specs = [{"name": n, **TOOL_SCHEMAS[n]} for n in tools]
    text = ""
    for _ in range(max_turns):
        t = time.time()
        kw = {"tools": specs} if specs else {}
        msg = run.create(model=MODEL, max_tokens=max_tokens, system=system, messages=msgs, **kw)
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
                                "content": json.dumps(_summary(out, 10000), default=str, ensure_ascii=False)})
        msgs.append({"role": "user", "content": results})
    return text


def analyst(run, p, today):
    series = p.get("series_destination", p["destination"])
    window = run.call_tool("analyst", "compute_travel_window", {"mode": p["mode"], "destination": series,
                                                               "travel_month": p.get("travel_month"), "today": today})
    if p.get("destination_label"):
        window["destination_name"] = p["destination_label"]
    route = run.call_tool("analyst", "get_route", {"destination": p["destination"]}) if p["mode"] == "train" else None
    fares = []
    if p.get("iata"):  # vrais billets : le mois visé (ou le mois prochain) et le meilleur mois
        b = window["best"]
        ref = window.get("target") or window["timeline"][1 if len(window["timeline"]) > 1 else 0]
        months = [(ref["year"], ref["month"])]
        if (b["year"], b["month"]) != (ref["year"], ref["month"]):
            months.append((b["year"], b["month"]))
        for y, m in months:
            f = run.call_tool("analyst", "get_real_fares", {"destination_iata": p["iata"],
                                                            "travel_date": fare_date(y, m, today)})
            fares.append({**f, "month_label": f"{MONTHS_FR[m - 1]} {y}", "is_best": (y, m) == (b["year"], b["month"])})
    note = None
    if llm():
        note = agent_loop(
            run, "analyst",
            "Tu es l'analyst agent de Départ (billets de train et d'avion depuis Paris). Tu as la frise des mois et, "
            "en train, les prix SNCF et les places TGVmax ; en avion vers un aéroport précis, de vrais billets Google "
            "Flights. Si utile, appelle get_price_seasonality pour comparer train et avion. Résume en 3 phrases courtes, "
            "texte brut, uniquement avec les chiffres des outils.",
            json.dumps({"params": p, "best": window["best"], "target": window.get("target"),
                        "timeline": [{k: t[k] for k in ("label", "status", "reason")} for t in window["timeline"]],
                        "real_fares": [{k: f.get(k) for k in ("month_label", "date", "lowest_price", "price_level",
                                                              "typical_range")} for f in fares],
                        "route": route and {"fares": route["fares"],
                                            "tgvmax_free_trains_30d": sum(d["free"] for d in route["tgvmax_next_days"])}},
                       default=str, ensure_ascii=False), ["get_price_seasonality"])
    return {"window": window, "route": route, "fares": fares, "note": note}


def calendar_agent(run, p, today):
    end = (date.fromisoformat(p["travel_month"]) + timedelta(days=62)).isoformat() if p.get("travel_month") \
        else (date.fromisoformat(today) + timedelta(days=365)).isoformat()
    out = run.call_tool("calendar", "get_calendar", {"start": today, "end": end})
    periods = [x for x in out["periods"] if x["kind"] == "ferie" or x["zones"] in ("Zone A", "Zone B", "Zone C")]
    note = None
    if llm():
        note = agent_loop(
            run, "calendar",
            "Tu es le calendar agent de Départ. À partir des vacances scolaires (zones A, B, C) et des jours fériés, "
            "liste les 3 à 5 périodes à éviter ou à viser pour partir moins cher (ponts, vacances décalées entre "
            "zones). Une ligne par période, 'nom (dates) : effet', texte brut, 14 mots max par effet.",
            json.dumps({"params": p, "periods": periods[:80]}, default=str, ensure_ascii=False), [], 1, 600)
    return {"periods": periods, "note": note}


def advisor_template(p, a):
    w = a["window"]
    b = w["best"]
    where = ("Paris → " + p["destination"].title() if p["mode"] == "train" else
             f"un vol Paris → {w['destination_name']}" if w.get("destination_name") else
             "un vol international" if p["destination"] == "international" else "un vol en France")
    s = f"Pour {where}, le meilleur moment pour partir est {b['label']} : {b['reason'].lower().replace(' · ', ', ')}"
    if w.get("target") and w["target"] is not b:
        s += (f". En {w['target']['label']}, les billets sont à {w['target']['price_vs_year_pct']:+.0f} % : "
              f"partir en {b['label']} te fait gagner environ {w['saving_vs_target_pts']:.0f} points de prix")
    real = [f for f in a.get("fares", []) if f.get("available") and f.get("lowest_price")]
    if real:
        lv = {"low": "un prix bas", "typical": "un prix normal", "high": "un prix élevé"}
        s += ". Vrais billets aujourd'hui : " + ", ".join(
            f"dès {f['lowest_price']} € le {f['date'][8:10]}/{f['date'][5:7]}"
            + (f" ({lv[f['price_level']]} selon Google)" if f.get("price_level") in lv else "") for f in real)
        if len(real) == 2:
            cheaper = min(real, key=lambda f: f["lowest_price"])
            if not cheaper["is_best"] and cheaper["lowest_price"] < max(f["lowest_price"] for f in real):
                other = max(real, key=lambda f: f["lowest_price"])
                s += (f". Mais aujourd'hui, le vrai billet de {cheaper['month_label']} ({cheaper['lowest_price']} €) est moins "
                      f"cher que celui de {other['month_label']} ({other['lowest_price']} €) : les vrais prix priment, "
                      f"prends {cheaper['month_label']}")
        ups = [f for f in real if (f.get("forecast") or {}).get("direction") == "up"]
        for f in ups:
            fc = f["forecast"]
            s += (f". Le billet du {f['date'][8:10]}/{f['date'][5:7]} devrait remonter : {fc['why']}, et dans nos tests "
                  f"ce signal s'est vérifié {fc['measured_precision_pct']} % du temps, réserve-le maintenant")
        tr = real[0].get("trend")
        if not ups and tr and abs(tr["change_pct"]) >= 1:
            s += (f". Sur les {tr['days']} derniers jours, ce billet est passé de {tr['first']} € à {tr['last']} € "
                  f"({tr['change_pct']:+.0f} %)")
    if a.get("route") and a["route"]["fares"]:
        cheapest = min(a["route"]["fares"], key=lambda f: f["price_min"])
        s += f". Billets dès {cheapest['price_min']:.0f} € en {cheapest['carrier']}"
        free = sum(d["free"] for d in a["route"]["tgvmax_next_days"])
        if a["route"]["tgvmax_next_days"]:
            s += f", et {free} trains avec des places TGVmax libres sur les 30 prochains jours"
    return s + "."


def advisor_llm(run, p, a, c, memory):
    t = time.time()
    payload = {"params": p, "best": a["window"]["best"], "target": a["window"].get("target"),
               "saving_vs_target_pts": a["window"].get("saving_vs_target_pts"),
               "timeline": [{k: x[k] for k in ("label", "status", "reason")} for x in a["window"]["timeline"]],
               "route": a["route"] and {"fares": a["route"]["fares"],
                                        "tgvmax_free_trains_30d": sum(d["free"] for d in a["route"]["tgvmax_next_days"])},
               "real_fares": [{**{k: f.get(k) for k in ("month_label", "date", "lowest_price", "price_level",
                                                         "typical_range")},
                               "trend": f.get("trend") and {k: f["trend"][k] for k in ("days", "first", "last", "change_pct")},
                               "forecast_14d": f.get("forecast") and {k: f["forecast"].get(k) for k in
                                                                      ("direction", "headline", "why", "measured_precision_pct")},
                               "cheapest_flights": [{k: x[k] for k in ("airline", "price", "stops")}
                                                    for x in f.get("flights", [])[:3]]}
                              for f in a.get("fares", []) if f.get("available")],
               "analyst_note": a["note"], "calendar_note": c["note"], "memory": memory}
    msg = run.create(
        model=MODEL, max_tokens=1200,
        system=("Tu es l'advisor agent de Départ, qui dit quand partir pour payer moins cher en train ou en avion "
                "depuis Paris. Français, tutoiement, 3 à 4 phrases courtes et simples : le meilleur mois et pourquoi, "
                "ce que ça fait gagner par rapport au mois visé s'il y en a un, les vrais billets en avion (prix du jour, "
                "verdict de Google, et si le prix monte ou descend sur les derniers jours), la prévision à 14 jours si elle "
                "annonce une hausse ; si les vrais billets du jour contredisent la moyenne historique, les vrais billets "
                "priment et tu le dis (avec son taux de réussite mesuré ; si direction = none, dis qu'on ne sait pas prévoir "
                "une baisse, sans inventer), les prix SNCF en train, les périodes à éviter. N'utilise QUE les chiffres fournis, arrondis à l'unité. Pas de jargon (ni 'indice', ni "
                "'HICP', ni 'score'), pas de markdown. Les écarts de prix sont des moyennes historiques, pas une "
                "promesse : dis-le en quelques mots. Si une mémoire est fournie, fais-y référence."),
        messages=[{"role": "user", "content": json.dumps(payload, default=str, ensure_ascii=False)}])
    text = " ".join(b.text for b in msg.content if b.type == "text").strip()
    run.log("advisor", "llm", None, None, {"text": text}, int((time.time() - t) * 1000))
    return text


def grounding(text, outputs, salient=None):
    text = re.sub(r"(?<=\d)[   ](?=\d{3}(?!\d))", "", text)
    nums = {float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", text)}
    nums = {x for x in nums if not 1900 < x < 2100}
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
            pool.update(float(x) for x in re.findall(r"\d+(?:\.\d+)?", v))
    for o in outputs:
        walk(o)
    ok = [x for x in nums if x in pool or round(x) in pool]
    # Un écart entre deux valeurs sourcées (ex. 502 € − 408 € = 94 €, +24 % vs −8 %) est calculé, pas inventé
    ints = {round(v) for v in (salient if salient is not None else pool) if isinstance(v, (int, float)) and abs(v) < 100000}
    def is_gap(x):  # x ≈ a − b pour deux valeurs sourcées a et b (à 1 près, pour les arrondis)
        x = round(x)
        return any(b + k in ints for a in ints for b in (a - x, a + x) for k in (-1, 0, 1))
    derived = [x for x in nums - set(ok) if is_gap(x)]
    return {"numbers": len(nums), "grounded": len(ok) + len(derived), "derived": len(derived),
            "ungrounded": sorted(nums - set(ok) - set(derived))}


def describe(p):
    where = p["destination"].title() if p["mode"] == "train" else p.get("destination_label") or p["destination"]
    when = (f"{MONTHS_FR[int(p['travel_month'][5:7]) - 1]} {p['travel_month'][:4]}" if p.get("travel_month")
            else "dates flexibles")
    return f"{p['mode']} vers {where}, {when}"


def recommend(params, handle=None, today=None):
    run = Run()
    today = today or date.today().isoformat()
    t0 = time.time()
    user_id, profile, past = None, {}, []
    if handle:
        u = pg.fetch_one("""INSERT INTO vg_users (handle) VALUES (%s) ON CONFLICT (handle) DO UPDATE
                            SET handle = EXCLUDED.handle RETURNING id, profile""", (handle,))
        user_id, profile = u["id"], u["profile"] or {}
        past = pg.fetch("SELECT label FROM vg_searches WHERE user_id = %s ORDER BY id DESC LIMIT 3", (user_id,))
    p = {"mode": "train", "destination": "LYON PART DIEU", "travel_month": None, **profile,
         **{k: v for k, v in params.items() if v not in (None, "")}}
    if params.get("flexible"):
        p["travel_month"] = None
    p.pop("flexible", None)
    air_codes = {d["code"] for d in list_air_destinations()}
    ap = airport(p["destination"]) if p["mode"] == "avion" and len(p["destination"]) == 3 else None
    if ap:  # aéroport du monde (IATA) : vrais billets + saisonnalité de la liaison si Eurostat la couvre
        p["iata"] = ap["iata"]
        p["destination_label"] = f"{ap['city'] or ap['name']} ({ap['iata']})"
        p["series_destination"] = ap["icao"] if ap["icao"] in air_codes else ("national" if ap["cc"] == "FR" else "international")
    elif p["mode"] == "avion" and p["destination"] not in ("national", "international", *air_codes):
        p["destination"] = "national"
    if p["mode"] == "train" and p["destination"] in (*air_codes, "national", "international"):
        p["destination"] = "LYON PART DIEU"
    memory = f"{len(past)} recherche(s) précédente(s), dernière : « {past[0]['label']} »" if past else None
    run.log("intake", "form", "validate", {"fields": params, "memory": profile}, p)
    if memory:
        run.log("memory", "tool_result", "postgres.vg_searches", {"user": handle}, {"past": [x["label"] for x in past]})
    with ThreadPoolExecutor(2) as ex:
        fa, fc = ex.submit(analyst, run, p, today), ex.submit(calendar_agent, run, p, today)
        a, c = fa.result(), fc.result()
    mode = "llm" if llm() else "rules"
    advice = advisor_llm(run, p, a, c, memory) if mode == "llm" else advisor_template(p, a)
    if mode == "rules":
        run.log("advisor", "rules", "template", None, {"text": advice})
    # valeurs-clés dont un écart peut être cité : mois de la frise, vrais billets, tarifs SNCF
    salient = [v for t in a["window"]["timeline"] for v in (t["price_vs_year_pct"], t["demand_vs_year_pct"])]
    for f in a.get("fares", []):
        salient += [f.get("lowest_price") or 0] + [x["price"] for x in f.get("flights", [])]
        if f.get("trend"):
            salient += [f["trend"]["first"], f["trend"]["last"]]
    if a.get("route"):
        salient += [x for fa in a["route"]["fares"] for x in (fa["price_min"], fa["price_max"])]
    g = grounding(advice, run.tool_outputs, salient)
    run.log("advisor", "final", "grounding_check", None, g)
    result = {"run_id": run.id, "mode": mode, "params": p, "advice": advice, "grounding": g, "memory": memory,
              "window": a["window"], "route": a["route"], "fares": a["fares"], "calendar": c["periods"],
              "notes": {"analyst": a["note"], "calendar": c["note"]},
              "usage": {"llm_calls": run.llm_calls, **run.tokens, "tool_calls": len(run.tool_outputs)},
              "latency_ms": int((time.time() - t0) * 1000), "trace": run.trace}
    try:
        s = pg.fetch_one("INSERT INTO vg_searches (user_id, params, label) VALUES (%s,%s,%s) RETURNING id",
                         (user_id, pg.jsonb(p), describe(p)))
        rec = pg.fetch_one("INSERT INTO vg_recommendations (search_id, payload) VALUES (%s,%s) RETURNING id",
                           (s["id"], pg.jsonb({k: v for k, v in result.items() if k != "trace"})))
        result["recommendation_id"] = rec["id"]
        if user_id:
            pg.fetch("UPDATE vg_users SET profile = profile || %s WHERE id = %s RETURNING id",
                     (pg.jsonb({k: p[k] for k in ("mode", "destination") if p.get(k)}), user_id))
    except Exception as ex:
        result["persist_error"] = str(ex)
    return result
