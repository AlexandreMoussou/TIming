"""Backtest hors échantillon de la recommandation de timing (leave-one-year-out).

Pour chaque année test Y (2021-2025), chaque arrondissement de Paris et chaque typologie :
- les indices saisonniers sont recalculés SANS l'année Y (pas de regard vers le futur) ;
- on choisit le mois recommandé avec la même règle que l'app (compute_window) pour un emménagement
  en septembre de l'année Y, avec les événements de l'année Y (connus à l'avance) ;
- on compare, sur les données réelles de l'année Y, le mois recommandé au mois naïf (septembre)
  et à la moyenne des mois candidats (choix au hasard dans la même fenêtre).

Location : métrique = volume de ventes du mois (proxy de l'offre), plus = mieux.
Achat : métrique = prix médian au m² du mois de signature (compromis + 3 mois), moins = mieux.

Usage : python -m benchmarks.backtest   (depuis timing/)
"""
import csv
import json
import statistics as st
from collections import defaultdict
from datetime import date
from pathlib import Path

from app.agents.tools import COMPETITION, MONTHS_FR, SLOWDOWN, _competition_penalty, _event_names_in
from app.db import postgres as pg
from app.db.clickhouse import query

OUT = Path(__file__).parent
YEARS = range(2021, 2026)
COMMUNES = [f"751{i:02d}" for i in range(1, 21)]
TYPOS = ("studio_t1", "t2", "t3plus")
MOVE_IN_MONTH = 9


def load():
    rows = query(
        """SELECT code_commune AS c, typology AS t, toYear(date_mutation) AS y, toMonth(date_mutation) AS m,
                  count() AS n, median(prix_m2) AS p
           FROM dvf_sales WHERE code_commune IN {c:Array(String)} AND toYear(date_mutation) BETWEEN 2021 AND 2025
           GROUP BY c, t, y, m""", {"c": COMMUNES})
    d = defaultdict(dict)
    for r in rows:
        d[(r["c"], r["t"], r["y"])][r["m"]] = (r["n"], r["p"])
    return d


def indices(d, c, t, exclude):
    """Indices de volume et de prix par mois, moyennés sur les années autres que `exclude`."""
    vol, pri = defaultdict(list), defaultdict(list)
    for y in YEARS:
        if y == exclude or len(d.get((c, t, y), {})) < 12:
            continue
        months = d[(c, t, y)]
        n_avg = st.mean(v[0] for v in months.values())
        p_med = st.median(v[1] for v in months.values())
        for m, (n, p) in months.items():
            vol[m].append(n / n_avg - 1)
            pri[m].append(p / p_med - 1)
    return {m: 100 * st.mean(v) for m, v in vol.items()}, {m: 100 * st.mean(v) for m, v in pri.items()}


def main():
    d = load()
    events = pg.fetch("SELECT name, start_date::text AS start_date, end_date::text AS end_date FROM events")
    rows = []
    for y in YEARS:
        for c in COMMUNES:
            for t in TYPOS:
                actual = d.get((c, t, y), {})
                if len(actual) < 12:
                    continue
                vol, pri = indices(d, c, t, y)
                if len(vol) < 12:
                    continue
                # Location : candidats juin-août (1 à 3 mois avant), même score que l'app
                cands = []
                for m in (6, 7, 8):
                    names = _event_names_in(events, y, m)
                    comp = [x for x in names if x.startswith(COMPETITION[t])]
                    slow = [x for x in names if x.startswith(SLOWDOWN)]
                    cands.append((vol[m] - _competition_penalty(comp) - 15 * len(slow), m))
                rec = max(cands)[1]
                n_rec, n_naive = actual[rec][0], actual[MOVE_IN_MONTH][0]
                n_rand = st.mean(actual[m][0] for _, m in cands)
                rows.append({"year": y, "commune": c, "typology": t, "intent": "louer",
                             "recommended": MONTHS_FR[rec - 1], "naive": "septembre",
                             "metric": "volume", "rec_value": n_rec, "naive_value": n_naive,
                             "random_value": round(n_rand, 1),
                             "gain_vs_naive_pct": round(100 * (n_rec / n_naive - 1), 2),
                             "gain_vs_random_pct": round(100 * (n_rec / n_rand - 1), 2),
                             "success": n_rec > n_naive})
                # Achat : signature (compromis + 3 mois) entre mars et septembre ; on vise le prix le plus bas
                sign = [m for m in range(3, 10)]
                rec_s = min(sign, key=lambda m: pri[m] - 0.03 * vol[m])
                p_rec, p_naive = actual[rec_s][1], actual[MOVE_IN_MONTH][1]
                p_rand = st.mean(actual[m][1] for m in sign)
                rows.append({"year": y, "commune": c, "typology": t, "intent": "acheter",
                             "recommended": MONTHS_FR[rec_s - 1], "naive": "septembre",
                             "metric": "prix_m2", "rec_value": round(p_rec), "naive_value": round(p_naive),
                             "random_value": round(p_rand),
                             "gain_vs_naive_pct": round(100 * (1 - p_rec / p_naive), 2),
                             "gain_vs_random_pct": round(100 * (1 - p_rec / p_rand), 2),
                             "success": p_rec < p_naive})

    with open(OUT / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    summary = {}
    for intent in ("louer", "acheter"):
        r = [x for x in rows if x["intent"] == intent]
        g = [x["gain_vs_naive_pct"] for x in r]
        summary[intent] = {
            "cases": len(r), "success_rate_pct": round(100 * sum(x["success"] for x in r) / len(r), 1),
            "mean_gain_vs_naive_pct": round(st.mean(g), 2), "median_gain_vs_naive_pct": round(st.median(g), 2),
            "mean_gain_vs_random_pct": round(st.mean(x["gain_vs_random_pct"] for x in r), 2),
            "success_rate_vs_random_pct": round(100 * sum(x["gain_vs_random_pct"] > 0 for x in r) / len(r), 1),
            "by_typology": {t: {"cases": len(rt := [x for x in r if x["typology"] == t]),
                                "success_rate_pct": round(100 * sum(x["success"] for x in rt) / len(rt), 1),
                                "mean_gain_vs_naive_pct": round(st.mean(x["gain_vs_naive_pct"] for x in rt), 2)}
                            for t in TYPOS},
            "by_year": {y: {"success_rate_pct": round(100 * sum(x["success"] for x in ry) / len(ry), 1),
                            "mean_gain_vs_naive_pct": round(st.mean(x["gain_vs_naive_pct"] for x in ry), 2)}
                        for y in YEARS if (ry := [x for x in r if x["year"] == y])},
        }
    (OUT / "results.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
