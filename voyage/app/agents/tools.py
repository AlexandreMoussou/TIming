"""Outils des agents Départ. Chaque outil renvoie des chiffres issus d'une requête réelle et sa source."""
from datetime import date, timedelta

from app.db import postgres as pg
from app.db.clickhouse import query
from app.db.valkey import cached

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre"]
YEARS = (2016, 2025)  # années complètes, hors effondrement 2020-2021 traité par la normalisation annuelle


def _shift(y, m, k):
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


def get_price_seasonality(mode):
    """Prix du billet par mois vs la moyenne de l'année (indice Eurostat HICP France, 2016-2025)."""
    series = "air" if mode == "avion" else "rail"

    def run():
        return query(
            """WITH y AS (SELECT toYear(month) yr, avg(value) a FROM vg_price_index
                          WHERE series = {s:String} AND toYear(month) BETWEEN {y0:UInt16} AND {y1:UInt16} GROUP BY yr)
               SELECT toMonth(month) AS m, avg(value / a - 1) * 100 AS pct, count() AS years
               FROM vg_price_index JOIN y ON toYear(month) = yr
               WHERE series = {s:String} AND toYear(month) BETWEEN {y0:UInt16} AND {y1:UInt16}
               GROUP BY m ORDER BY m""", {"s": series, "y0": YEARS[0], "y1": YEARS[1]})
    rows, hit = cached(f"vg:price:{series}", 86400, run)
    return {"mode": mode, "cache_hit": hit,
            "source": f"Eurostat HICP France, {'transport aérien (CP0733)' if series == 'air' else 'transport ferroviaire (CP0731)'}, {YEARS[0]}-{YEARS[1]}",
            "months": [{"month": r["m"], "name": MONTHS_FR[r["m"] - 1], "price_vs_year_pct": round(r["pct"], 1)}
                       for r in rows]}


def is_air_route(destination):
    return bool(destination) and len(destination) == 4 and destination.isupper()


def get_demand(mode, destination=None):
    """Affluence par mois vs la moyenne de l'année : passagers de la liaison Paris → destination (Eurostat),
    passagers aériens France (national / international) ou trains prévus sur le trajet SNCF."""
    if mode == "avion" and is_air_route(destination):
        sql = """WITH y AS (SELECT toYear(month) yr, avg(passengers) a FROM vg_air_route
                            WHERE dest_icao = {d:String} AND toYear(month) NOT IN (2020, 2021) GROUP BY yr HAVING count() = 12)
                 SELECT toMonth(month) AS m, avg(passengers / a - 1) * 100 AS pct, any(dest_name) AS name
                 FROM vg_air_route JOIN y ON toYear(month) = yr WHERE dest_icao = {d:String} GROUP BY m ORDER BY m"""
        rows, hit = cached(f"vg:demand:route:{destination}", 86400, lambda: query(sql, {"d": destination}))
        name = rows[0]["name"] if rows else destination
        return {"mode": mode, "destination": destination, "destination_name": name, "cache_hit": hit,
                "source": f"Eurostat avia_par_fr, passagers Paris (Roissy + Orly) → {name}, 2016-2024 hors 2020-2021",
                "months": [{"month": r["m"], "demand_vs_year_pct": round(r["pct"], 1)} for r in rows]}
    if mode == "avion":
        cov = "INTL" if destination == "international" else "NAT"
        sql = """WITH y AS (SELECT toYear(month) yr, avg(passengers) a FROM vg_air_pax
                            WHERE coverage = {c:String} AND toYear(month) BETWEEN 2016 AND 2025 AND toYear(month) NOT IN (2020, 2021)
                            GROUP BY yr)
                 SELECT toMonth(month) AS m, avg(passengers / a - 1) * 100 AS pct
                 FROM vg_air_pax JOIN y ON toYear(month) = yr WHERE coverage = {c:String} GROUP BY m ORDER BY m"""
        rows, hit = cached(f"vg:demand:air:{cov}", 86400, lambda: query(sql, {"c": cov}))
        src = f"Eurostat avia_paoc, passagers aériens France ({'international' if cov == 'INTL' else 'national'}), 2016-2025 hors 2020-2021"
        return {"mode": mode, "cache_hit": hit, "source": src,
                "months": [{"month": r["m"], "demand_vs_year_pct": round(r["pct"], 1)} for r in rows]}
    sql = """WITH t AS (SELECT month, sum(planned) p, sum(cancelled) c, sum(late_arrival) l FROM vg_rail_regularity
                        WHERE origin LIKE 'PARIS%' AND destination = {d:String} AND toYear(month) NOT IN (2020, 2021)
                        GROUP BY month),
                  y AS (SELECT toYear(month) yr, avg(p) a FROM t GROUP BY yr HAVING count() = 12)
             SELECT toMonth(month) AS m, avg(p / a - 1) * 100 AS pct, avg(l / p) * 100 AS late_pct,
                    avg(c / p) * 100 AS cancel_pct, sum(p) AS trains
             FROM t JOIN y ON toYear(month) = yr GROUP BY m ORDER BY m"""
    rows, hit = cached(f"vg:demand:rail:{destination}", 86400, lambda: query(sql, {"d": destination}))
    return {"mode": mode, "destination": destination, "cache_hit": hit,
            "source": "SNCF régularité mensuelle TGV (AQST), Paris → destination, hors 2020-2021",
            "months": [{"month": r["m"], "demand_vs_year_pct": round(r["pct"], 1), "late_pct": round(r["late_pct"], 1),
                        "cancel_pct": round(r["cancel_pct"], 1), "trains": int(r["trains"])} for r in rows]}


def list_destinations():
    """Destinations TGV depuis Paris (France et international) avec au moins deux ans de données."""
    rows, _ = cached("vg:dest:v3", 86400, lambda: query(
        """SELECT destination, sum(planned) AS trains, round(avg(duration_min)) AS duration,
                  countIf(service = 'National') = 0 AS intl, count(DISTINCT month) AS months
           FROM vg_rail_regularity WHERE origin LIKE 'PARIS%' AND month >= '2024-01-01'
           GROUP BY destination HAVING months >= 12 ORDER BY trains DESC"""))
    return [{"destination": r["destination"], "trains_since_2024": int(r["trains"]), "duration_min": int(r["duration"]),
             "international": bool(r["intl"])} for r in rows]


def list_air_destinations():
    rows, _ = cached("vg:airdest:v1", 86400, lambda: query(
        """SELECT dest_icao, any(dest_name) AS name, any(country) AS country, sumIf(passengers, toYear(month) = 2024) AS pax
           FROM vg_air_route GROUP BY dest_icao ORDER BY pax DESC"""))
    return [{"code": r["dest_icao"], "name": r["name"], "country": r["country"], "passengers_2024": int(r["pax"]),
             "international": r["country"] != "FR"} for r in rows]


def _city_key(destination):
    return destination.split(" ")[0].split("-")[0]


def get_route(destination):
    """Fourchettes de prix SNCF (INOUI, OUIGO) et places TGVmax à 30 jours pour Paris → destination."""
    key = _city_key(destination)
    fares = query(
        """SELECT carrier, min(price_min) AS lo, max(price_max) AS hi, count() AS n FROM vg_rail_fares
           WHERE origin LIKE 'PARIS%' AND destination LIKE {k:String} AND class = '2'
           GROUP BY carrier ORDER BY lo""", {"k": f"{key}%"})
    tgvmax = query(
        """SELECT day, countIf(available = 1) AS free, count() AS trains FROM vg_tgvmax
           WHERE origin LIKE 'PARIS%' AND destination LIKE {k:String} GROUP BY day ORDER BY day""", {"k": f"{key}%"})
    return {"destination": destination,
            "source": "SNCF Open Data : tarifs TGV INOUI/OUIGO (2de classe) et disponibilités TGVmax à 30 jours",
            "fares": [{"carrier": f["carrier"], "price_min": round(f["lo"], 2), "price_max": round(f["hi"], 2)}
                      for f in fares],
            "tgvmax_next_days": [{"day": str(t["day"]), "free": int(t["free"]), "trains": int(t["trains"])}
                                 for t in tgvmax],
            "tgvmax_free_trains_30d": sum(int(t["free"]) for t in tgvmax),
            "tgvmax_trains_30d": sum(int(t["trains"]) for t in tgvmax)}


def get_calendar(start, end):
    """Vacances scolaires (par zone) et jours fériés entre deux dates (PostgreSQL vg_calendar)."""
    rows = pg.fetch("""SELECT kind, name, zones, start_date, end_date, source FROM vg_calendar
                       WHERE end_date >= %s AND start_date <= %s ORDER BY start_date""", (start, end))
    return {"source": "PostgreSQL vg_calendar (data.education.gouv.fr, calendrier.api.gouv.fr)",
            "periods": [{**r, "start_date": str(r["start_date"]), "end_date": str(r["end_date"])} for r in rows]}


def _holiday_share(periods, y, m):
    """Part des jours du mois couverts par des vacances scolaires (au moins une zone A, B ou C, métropole)."""
    first = date(y, m, 1)
    nxt = date(*_shift(y, m, 1), 1)
    days = set()
    for p in periods:
        if p["kind"] != "vacances" or p["zones"] not in ("Zone A", "Zone B", "Zone C"):
            continue
        a, b = max(date.fromisoformat(p["start_date"]), first), min(date.fromisoformat(p["end_date"]), nxt - timedelta(1))
        d = a
        while d <= b:
            days.add(d)
            d += timedelta(1)
    return len(days) / (nxt - first).days


def _level(v):
    return 1 if v < -8 else 2 if v < -3 else 3 if v < 3 else 4 if v < 10 else 5


def compute_travel_window(mode, destination, travel_month, today):
    """Meilleur mois pour partir. Score = −prix (poids 1) − affluence (0,4) − 15 × part de vacances scolaires
    − retards (train). Avec un mois visé : on regarde ce mois et les 2 mois autour ; sinon les 12 prochains."""
    today = date.fromisoformat(str(today))
    prices = {r["month"]: r for r in get_price_seasonality(mode)["months"]}
    demand = {r["month"]: r for r in get_demand(mode, destination)["months"]}
    start = (today.year, today.month)
    flexible = not travel_month
    if flexible:
        months = [_shift(*start, i) for i in range(12)]
    else:
        t = date.fromisoformat(str(travel_month))
        months = [x for x in (_shift(t.year, t.month, k) for k in (-2, -1, 0, 1, 2)) if x >= start]
    end = date(*_shift(*months[-1], 1), 1)
    cal = get_calendar(date(*start, 1), end)["periods"]
    timeline = []
    for y, m in months:
        p = prices[m]["price_vs_year_pct"]
        dm = demand.get(m, {})
        dv = dm.get("demand_vs_year_pct", 0)
        hol = _holiday_share(cal, y, m)
        late = dm.get("late_pct")
        if mode == "avion":  # passagers : plus il y a de monde, moins c'est intéressant
            score = -p - 0.4 * dv - 15 * hol
        else:  # trains prévus : plus il y a de trains, plus il y a de places
            score = -p + 0.2 * dv - 15 * hol - 0.3 * (late or 0)
        reasons = [("billets moins chers" if p <= -3 else "billets plus chers" if p >= 3 else "prix dans la moyenne")
                   + f" ({p:+.0f} %)"]
        if mode == "avion":
            reasons.append("peu de monde" if dv <= -5 else "beaucoup de monde" if dv >= 5 else "affluence moyenne")
        else:
            reasons.append("plus de trains que d'habitude" if dv >= 2 else "moins de trains que d'habitude" if dv <= -2
                           else "nombre de trains habituel")
        if hol >= 0.3:
            reasons.append(f"vacances scolaires {round(hol * 100)} % du mois")
        if late is not None:
            reasons.append(f"{late:.0f} % de trains en retard")
        timeline.append({"year": y, "month": m, "label": f"{MONTHS_FR[m - 1]} {y}", "score": round(score, 1),
                         "price_vs_year_pct": p, "demand_vs_year_pct": dv, "holiday_share_pct": round(hol * 100),
                         "late_pct": late, "price_level": _level(p), "reason": " · ".join(reasons)})
    best = max(timeline, key=lambda x: x["score"])
    for t in timeline:
        d = best["score"] - t["score"]
        t["status"] = "best" if t is best else "good" if d <= 5 else "ok" if d <= 15 else "avoid"
        if not flexible and (t["year"], t["month"]) == (date.fromisoformat(str(travel_month)).year,
                                                         date.fromisoformat(str(travel_month)).month):
            t["target"] = True
    target = next((t for t in timeline if t.get("target")), None)
    dem = get_demand(mode, destination)
    return {"mode": mode, "destination": destination, "destination_name": dem.get("destination_name"),
            "price_source": get_price_seasonality(mode)["source"], "demand_source": dem["source"],
            "flexible": flexible, "best": best, "target": target,
            "timeline": timeline, "calendar": [c for c in cal if c["kind"] == "vacances" and "C" in (c["zones"] or "")
                                               or c["kind"] == "ferie"],
            "saving_vs_target_pts": round(target["price_vs_year_pct"] - best["price_vs_year_pct"], 1) if target else None,
            "method": ("Avion : score = −écart de prix − 0,4 × affluence − 15 × part de vacances scolaires. "
                       "Train : score = −écart de prix + 0,2 × écart de trains prévus − 15 × vacances − 0,3 × % de retards")}


TOOL_SCHEMAS = {
    "compute_travel_window": {
        "description": "Meilleur mois pour partir (prix, affluence, vacances, retards) et verdict pour chaque mois.",
        "input_schema": {"type": "object", "properties": {
            "mode": {"type": "string", "enum": ["train", "avion"]}, "destination": {"type": "string"},
            "travel_month": {"type": ["string", "null"]}, "today": {"type": "string"}},
            "required": ["mode", "destination", "today"]}},
    "get_route": {
        "description": "Prix SNCF min/max par transporteur et places TGVmax libres sur 30 jours, Paris → destination.",
        "input_schema": {"type": "object", "properties": {"destination": {"type": "string"}},
                         "required": ["destination"]}},
    "get_price_seasonality": {
        "description": "Prix des billets par mois vs la moyenne de l'année (Eurostat, 2016-2025).",
        "input_schema": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["train", "avion"]}},
                         "required": ["mode"]}},
    "get_calendar": {
        "description": "Vacances scolaires et jours fériés entre deux dates.",
        "input_schema": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}},
                         "required": ["start", "end"]}},
}

TOOL_SCHEMAS["get_real_fares"] = {
    "description": "Vrais billets d'avion Paris → aéroport (code IATA) à une date : prix Google Flights, compagnies, "
                   "verdict bas/normal/élevé, fourchette habituelle et évolution du prix sur ~60 jours.",
    "input_schema": {"type": "object", "properties": {"destination_iata": {"type": "string"},
                                                      "travel_date": {"type": "string"}},
                     "required": ["destination_iata", "travel_date"]}}


def _real_fares(a):
    from app.agents.fares import get_real_fares
    return get_real_fares(a["destination_iata"], a["travel_date"])


TOOL_FUNCS = {
    "get_real_fares": _real_fares,
    "compute_travel_window": lambda a: compute_travel_window(a["mode"], a["destination"], a.get("travel_month"), a["today"]),
    "get_route": lambda a: get_route(a["destination"]),
    "get_price_seasonality": lambda a: get_price_seasonality(a["mode"]),
    "get_calendar": lambda a: get_calendar(a["start"], a["end"]),
}
