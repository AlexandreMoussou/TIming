"""Outils des agents. Chaque outil renvoie des chiffres issus d'une requête réelle
(ClickHouse ou PostgreSQL) et la requête/source qui les a produits."""
from datetime import date

from app.analytics.seasonality import get_seasonality as _seasonality
from app.db import postgres as pg
from app.db.clickhouse import query
from app.db.valkey import cached

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
             "octobre", "novembre", "décembre"]
# Surface typique utilisée pour passer d'un loyer au m² à un loyer mensuel (hypothèse affichée)
TYPICAL_SURFACE = {"studio_t1": 22, "t2": 40, "t3plus": 62}
RENT_SEGMENT = {"studio_t1": "app12", "t2": "app12", "t3plus": "app3"}
CAP_PIECES = {"studio_t1": 1, "t2": 2, "t3plus": 3}
# Événements qui augmentent la concurrence selon le type de bien recherché
COMPETITION = {
    "studio_t1": ("Rush de la rentrée", "Résultats Parcoursup", "Admissions Mon Master",
                  "Résultats des concours", "Rentrée décalée"),
    "t2": ("Rush de la rentrée", "Résultats des mutations", "Admissions Mon Master"),
    "t3plus": ("Résultats des mutations", "Rush de la rentrée"),
}
# Événements qui réduisent l'offre visible (peu d'annonces, peu de visites)
SLOWDOWN = ("Creux estival", "Fêtes de fin d'année")


def get_seasonality(zone, typology=None):
    rows, hit = cached(f"season:v2:{zone}:{typology}", 86400, lambda: _seasonality(zone, typology))
    return {
        "zone": zone, "typology": typology, "cache_hit": hit,
        "source": "ClickHouse dvf_sales (DVF 2021-2025, années complètes)",
        "months": [{"month": r["month"], "name": MONTHS_FR[r["month"] - 1], "sales": int(r["sales"]),
                    "volume_vs_avg_pct": round((r["volume_index"] - 1) * 100, 1),
                    "price_vs_year_pct": round((r["price_index"] - 1) * 100, 2),
                    "median_prix_m2": round(r["median_prix_m2"])} for r in rows],
    }


def _paris_communes():
    return [f"751{i:02d}" for i in range(1, 21)]


def get_rent_levels(communes, typology):
    """Loyer d'annonce au m² (dernier millésime) + plafond d'encadrement Paris pour chaque commune."""
    seg = RENT_SEGMENT[typology]

    def run():
        rents = query(
            """SELECT code_commune, any(nom_commune) AS nom, argMax(loyer_m2, millesime) AS last_m2,
                      argMax(loyer_m2_low, millesime) AS low, argMax(loyer_m2_high, millesime) AS high,
                      max(millesime) AS last_year,
                      last_m2 / argMin(loyer_m2, millesime) - 1 AS evol
               FROM rent_indicators WHERE segment = {seg:String} AND code_commune IN {c:Array(String)}
               GROUP BY code_commune""", {"seg": seg, "c": communes})
        caps = query(
            """SELECT code_commune, avg(loyer_max) AS cap_m2, avg(loyer_ref) AS ref_m2
               FROM rent_caps_paris
               WHERE annee = (SELECT max(annee) FROM rent_caps_paris) AND pieces = {p:UInt8} AND meuble = 0
                 AND code_commune IN {c:Array(String)}
               GROUP BY code_commune""", {"p": CAP_PIECES[typology], "c": communes})
        return rents, caps

    (rents, caps), hit = cached(f"rents:v2:{typology}:{','.join(sorted(communes))}", 86400, run)
    cap = {c["code_commune"]: c for c in caps}
    s = TYPICAL_SURFACE[typology]
    out = []
    for r in rents:
        c = cap.get(r["code_commune"])
        out.append({
            "code_commune": r["code_commune"], "nom": r["nom"],
            "loyer_m2": round(r["last_m2"], 1), "loyer_m2_range": [round(r["low"], 1), round(r["high"], 1)],
            "loyer_mensuel_estime": round(r["last_m2"] * s), "surface_hypothese_m2": s,
            "evolution_2022_pct": round(r["evol"] * 100, 1), "millesime": r["last_year"],
            "plafond_encadrement_m2": round(c["cap_m2"], 1) if c else None,
            "plafond_mensuel_estime": round(c["cap_m2"] * s) if c else None,
        })
    return {"typology": typology, "cache_hit": hit,
            "source": "ClickHouse rent_indicators (carte des loyers, ministère) + rent_caps_paris (encadrement, non meublé)",
            "communes": out}


def get_upcoming_events(start, end, scope="75"):
    rows = pg.fetch(
        """SELECT name, kind, start_date, end_date, scope, expected_effect, source FROM events
           WHERE end_date >= %s AND start_date <= %s AND (scope = 'FR' OR scope = %s OR %s LIKE scope || '%%')
           ORDER BY start_date""", (start, end, scope, scope))
    return {"source": "PostgreSQL events", "from": str(start), "to": str(end),
            "events": [{**r, "start_date": str(r["start_date"]), "end_date": str(r["end_date"])} for r in rows]}


def _months_between(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _shift(y, m, k):
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


def _event_names_in(events, y, m):
    first = date(y, m, 1)
    last = date(y + (m == 12), m % 12 + 1, 1)
    return [e["name"] for e in events if e["start_date"] < str(last) and e["end_date"] >= str(first)]


def compute_window(intent, typology, zone, move_in, today):
    """Choisit le mois de recherche. Location : on cherche 1 à 3 mois avant l'emménagement, on maximise
    l'offre (volume) et on pénalise la concurrence (événements) et les périodes creuses.
    Achat : la vente se signe ~3 mois après le compromis ; on cherche le mois de signature le moins cher."""
    move_in, today = date.fromisoformat(str(move_in)), date.fromisoformat(str(today))
    season = get_seasonality(zone, typology)
    by_m = {r["month"]: r for r in season["months"]}
    if intent == "acheter":
        lead_min, lead_max = 3, 9
    elif intent == "vendre":
        lead_min, lead_max = 0, 6
    else:
        lead_min, lead_max = 1, 3
    events = get_upcoming_events(date(today.year, today.month, 1), move_in, zone[:2] if len(zone) > 2 else zone)["events"]
    lo = _shift(move_in.year, move_in.month, -lead_max)
    hi = _shift(move_in.year, move_in.month, -lead_min)
    lo = max(lo, (today.year, today.month))
    candidates = []
    for y, m in _months_between(date(*lo, 1), date(*hi, 1)) if lo <= hi else []:
        deed_m = m if intent == "louer" else _shift(y, m, 3)[1]
        s = by_m[deed_m]
        names = _event_names_in(events, y, m)
        competition = [n for n in names if n.startswith(COMPETITION[typology])]
        slow = [n for n in names if n.startswith(SLOWDOWN)]
        if intent == "louer":
            score = s["volume_vs_avg_pct"] - 12 * len(competition) - 15 * len(slow)
        elif intent == "acheter":
            score = -10 * s["price_vs_year_pct"] + 0.3 * s["volume_vs_avg_pct"] - 8 * len(slow)
        else:
            score = 10 * s["price_vs_year_pct"] + 0.3 * s["volume_vs_avg_pct"] - 8 * len(slow)
        candidates.append({"year": y, "month": m, "label": f"{MONTHS_FR[m - 1]} {y}", "score": round(score, 1),
                           "volume_vs_avg_pct": s["volume_vs_avg_pct"], "price_vs_year_pct": s["price_vs_year_pct"],
                           "competition_events": competition, "slowdown_events": slow})
    if not candidates:
        return {"too_late": True, "message": "La date d'emménagement est trop proche : commence à chercher maintenant.",
                "season": season, "events": events}
    best = max(candidates, key=lambda c: c["score"])
    naive_m = move_in.month if intent == "louer" else _shift(move_in.year, move_in.month, 0)[1]
    naive = by_m[naive_m]
    return {
        "intent": intent, "typology": typology, "zone": zone, "best": best, "candidates": candidates,
        "naive": {"label": f"{MONTHS_FR[naive_m - 1]} (mois de l'emménagement)",
                  "volume_vs_avg_pct": naive["volume_vs_avg_pct"], "price_vs_year_pct": naive["price_vs_year_pct"]},
        "gain_vs_naive": {
            "volume_pts": round(best["volume_vs_avg_pct"] - naive["volume_vs_avg_pct"], 1),
            "price_pts": round(best["price_vs_year_pct"] - naive["price_vs_year_pct"], 2),
        },
        "method": ("Score = volume de transactions vs moyenne (proxy de l'offre) − 12 pts par événement de "
                   "concurrence − 15 pts par période creuse" if intent == "louer" else
                   "Score = −10 × écart de prix au m² du mois de signature (compromis + 3 mois) + 0,3 × volume"),
        "season": season, "events": events,
    }


def rank_neighbourhoods(typology, budget=None, zone="75", intent="louer"):
    communes = _paris_communes() if zone == "75" else [zone]
    rents = get_rent_levels(communes, typology)["communes"]
    peaks = query(
        """SELECT code_commune, toMonth(date_mutation) AS m, count() AS n FROM dvf_sales
           WHERE code_commune IN {c:Array(String)} AND typology = {t:String} AND toYear(date_mutation) <= 2025
           GROUP BY code_commune, m""", {"c": communes, "t": typology})
    prices = {r["code_commune"]: r for r in query(
        """SELECT code_commune, median(prix_m2) AS pm2, count() AS n FROM dvf_sales
           WHERE code_commune IN {c:Array(String)} AND typology = {t:String}
             AND date_mutation > (SELECT max(date_mutation) FROM dvf_sales) - INTERVAL 12 MONTH
           GROUP BY code_commune""", {"c": communes, "t": typology})}
    by_c = {}
    for p in peaks:
        by_c.setdefault(p["code_commune"], {})[p["m"]] = p["n"]
    out = []
    for r in rents:
        months = by_c.get(r["code_commune"], {})
        tot = sum(months.values()) or 1
        top = sorted(months, key=months.get, reverse=True)[:2]
        pr = prices.get(r["code_commune"])
        price = int(round(pr["pm2"] * r["surface_hypothese_m2"], -3)) if pr else None
        cost = r["loyer_mensuel_estime"] if intent == "louer" else price
        fits = budget is None or (cost is not None and cost <= budget)
        out.append({**r, "fits_budget": fits, "cost": cost,
                    "prix_m2_12m": round(pr["pm2"]) if pr else None, "prix_estime": price,
                    "budget_margin": None if budget is None or cost is None else budget - cost,
                    "peak_months": [MONTHS_FR[m - 1] for m in top],
                    "peak_share_pct": round(100 * sum(months[m] for m in top) / tot, 1),
                    "sales_sample": tot})
    out.sort(key=lambda x: (not x["fits_budget"], x["cost"] or 1e12))
    return {"source": "ClickHouse rent_indicators + rent_caps_paris + dvf_sales", "budget": budget, "intent": intent,
            "typology": typology, "ranking": out}


# Schémas d'outils exposés à Claude (tool use)
TOOL_SCHEMAS = {
    "get_seasonality": {
        "description": "Saisonnalité mensuelle DVF (volume de ventes et prix au m², corrigés de la tendance) "
                       "pour une zone (département '75', commune '75111' ou code postal '75011') et une typologie.",
        "input_schema": {"type": "object", "properties": {
            "zone": {"type": "string"}, "typology": {"type": "string", "enum": ["studio_t1", "t2", "t3plus"]}},
            "required": ["zone"]},
    },
    "compute_window": {
        "description": "Calcule la fenêtre de recherche optimale entre aujourd'hui et la date d'emménagement.",
        "input_schema": {"type": "object", "properties": {
            "intent": {"type": "string", "enum": ["louer", "acheter", "vendre"]},
            "typology": {"type": "string", "enum": ["studio_t1", "t2", "t3plus"]},
            "zone": {"type": "string"}, "move_in": {"type": "string", "description": "YYYY-MM-DD"},
            "today": {"type": "string", "description": "YYYY-MM-DD"}},
            "required": ["intent", "typology", "zone", "move_in", "today"]},
    },
    "rank_neighbourhoods": {
        "description": "Classe les arrondissements par loyer estimé pour le budget, avec plafond d'encadrement "
                       "et mois où le plus de logements changent de main.",
        "input_schema": {"type": "object", "properties": {
            "typology": {"type": "string", "enum": ["studio_t1", "t2", "t3plus"]},
            "budget": {"type": "number"}, "zone": {"type": "string"},
            "intent": {"type": "string", "enum": ["louer", "acheter", "vendre"]}}, "required": ["typology"]},
    },
    "get_upcoming_events": {
        "description": "Événements (élections, calendrier universitaire, saisons, légal, grands événements) "
                       "entre deux dates, depuis la table events.",
        "input_schema": {"type": "object", "properties": {
            "start": {"type": "string"}, "end": {"type": "string"}, "scope": {"type": "string"}},
            "required": ["start", "end"]},
    },
}

TOOL_FUNCS = {
    "get_seasonality": lambda a: get_seasonality(a["zone"], a.get("typology")),
    "compute_window": lambda a: compute_window(a["intent"], a["typology"], a["zone"], a["move_in"], a["today"]),
    "rank_neighbourhoods": lambda a: rank_neighbourhoods(a["typology"], a.get("budget"), a.get("zone", "75"),
                                                   a.get("intent", "louer")),
    "get_upcoming_events": lambda a: get_upcoming_events(a["start"], a["end"], a.get("scope", "75")),
}
