"""Vrais billets d'avion : Google Flights via SerpApi (prix, compagnies, verdict et historique de prix).

Chaque réponse est mise en cache 12 h dans Valkey (quota gratuit limité) avec sa date de relevé.
"""
import urllib.parse
from datetime import date, datetime, timezone

import requests

from app.config import SERPAPI_KEY
from app.db.clickhouse import query
from app.db.valkey import cached


def search_airports(q, limit=12):
    q = (q or "").strip()
    if len(q) < 2:
        return []
    return query(
        """SELECT iata, icao, name, city, country, cc, large FROM vg_airports
           WHERE iata = upper({q:String}) OR positionCaseInsensitiveUTF8(city, {q:String}) > 0
              OR positionCaseInsensitiveUTF8(country, {q:String}) > 0 OR positionCaseInsensitiveUTF8(name, {q:String}) > 0
           ORDER BY iata = upper({q:String}) DESC, startsWith(lowerUTF8(city), lowerUTF8({q:String})) DESC, large DESC, city
           LIMIT {n:UInt8}""", {"q": q, "n": limit})


def airport(iata):
    rows = query("SELECT iata, icao, name, city, country, cc FROM vg_airports WHERE iata = {i:String} LIMIT 1",
                 {"i": iata})
    return rows[0] if rows else None


def get_real_fares(destination_iata, travel_date):
    """Billets Paris (CDG, ORY) → destination à une date, aller simple, en euros, tels qu'affichés par Google Flights."""
    if not SERPAPI_KEY:
        return {"available": False, "reason": "SERPAPI_KEY absente"}

    def run():
        params = {"engine": "google_flights", "departure_id": "CDG,ORY", "arrival_id": destination_iata,
                  "outbound_date": travel_date, "type": "2", "currency": "EUR", "hl": "fr", "gl": "fr",
                  "api_key": SERPAPI_KEY}
        d = requests.get("https://serpapi.com/search.json", params=params, timeout=60).json()
        if d.get("error"):
            return {"available": False, "reason": d["error"]}
        flights = []
        for f in (d.get("best_flights") or []) + (d.get("other_flights") or []):
            if "price" not in f:
                continue
            legs = f["flights"]
            flights.append({"price": f["price"], "airline": ", ".join(dict.fromkeys(l["airline"] for l in legs)),
                            "logo": f.get("airline_logo") or legs[0].get("airline_logo"),
                            "flight_numbers": [l.get("flight_number") for l in legs],
                            "departure": legs[0]["departure_airport"]["time"], "from": legs[0]["departure_airport"]["id"],
                            "arrival": legs[-1]["arrival_airport"]["time"], "to": legs[-1]["arrival_airport"]["id"],
                            "duration_min": f.get("total_duration"), "stops": len(legs) - 1})
        flights.sort(key=lambda x: x["price"])
        pi = d.get("price_insights") or {}
        hist = pi.get("price_history") or []
        trend = None
        if len(hist) >= 2:
            first, last = hist[0][1], hist[-1][1]
            trend = {"days": round((hist[-1][0] - hist[0][0]) / 86400), "first": first, "last": last,
                     "min": min(h[1] for h in hist), "max": max(h[1] for h in hist),
                     "change_pct": round(100 * (last / first - 1), 1),
                     "points": [h[1] for h in hist]}
        return {"available": True, "date": travel_date, "destination": destination_iata,
                "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "source": "Google Flights via SerpApi (aller simple, Paris CDG/ORY, EUR)",
                "flights": flights[:5], "lowest_price": pi.get("lowest_price") or (flights[0]["price"] if flights else None),
                "price_level": pi.get("price_level"), "typical_range": pi.get("typical_price_range"), "trend": trend,
                "google_flights_url": "https://www.google.com/travel/flights?hl=fr&curr=EUR&q=" + urllib.parse.quote(
                    f"Vols de Paris vers {destination_iata} le {travel_date} aller simple")}

    out, hit = cached(f"vg:fares:{destination_iata}:{travel_date}", 43200, run)
    if out.get("available") and out.get("trend"):
        days = (date.fromisoformat(travel_date) - date.today()).days
        out["forecast"] = forecast_from_history(out["trend"]["points"], out.get("price_level"), days)
    return {**out, "cache_hit": hit}


def fare_date(y, m, today):
    """Date de vol représentative d'un mois : le 15, ou au moins 7 jours après aujourd'hui."""
    d = date(y, m, 15)
    t = date.fromisoformat(str(today))
    return max(d, date.fromordinal(t.toordinal() + 7)).isoformat()


HORIZON = 14  # jours
# Mesuré sur des historiques Google Flights réels, trajets de test non utilisés pour choisir la règle
# (benchmarks/price_forecast.py) : un prix 5 % sous sa médiane de 30 jours remonte dans les 14 jours dans 59 % des cas.
# Prévoir une baisse ne marche pas sur nos données (4 %) : on ne l'annonce jamais.
RULE_UP_PRECISION_PCT = 59


def forecast_from_history(points, price_level=None, days_to_departure=None):
    """Va-t-il monter ? Signal unique, mesuré : prix nettement sous sa médiane des 30 derniers jours."""
    if not points or len(points) < 31:
        return None
    window = points[-30:]
    med = sorted(window)[len(window) // 2]
    last = points[-1]
    gap = round(100 * (last / med - 1), 1)
    notes = []
    if price_level == "low":
        notes.append("Google classe aussi ce prix comme bas")
    if days_to_departure is not None and days_to_departure <= 21:
        notes.append(f"départ dans {days_to_departure} jours : les prix montent souvent à l'approche (règle générale, non mesurée ici)")
    if last <= 0.95 * med:
        return {"direction": "up", "horizon_days": HORIZON, "median_30d": med, "gap_pct": gap,
                "measured_precision_pct": RULE_UP_PRECISION_PCT, "notes": notes,
                "headline": "Devrait remonter : réserve maintenant",
                "why": f"{last} € est {-gap:.0f} % sous sa médiane des 30 derniers jours ({med} €)"}
    return {"direction": "none", "horizon_days": HORIZON, "median_30d": med, "gap_pct": gap,
            "measured_precision_pct": None, "notes": notes,
            "headline": "Pas de signal fiable",
            "why": f"{last} € est proche ou au-dessus de sa médiane des 30 derniers jours ({med} €) ; "
                   "nos tests montrent qu'on ne sait pas prévoir une baisse"}
