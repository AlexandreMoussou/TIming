"""Backtest hors échantillon (leave-one-year-out) de la règle « décale ton départ vers le mois le moins cher ».

Pour chaque année test Y (2016-2025, hors 2020-2021) et chaque mois visé M, la saisonnalité des prix est
recalculée SANS l'année Y ; on recommande le mois le moins cher parmi M-2..M+2, puis on compare sur les prix
réels de l'année Y (indice Eurostat) le mois recommandé au mois visé.

Usage : python -m benchmarks.backtest   (depuis voyage/)
"""
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

from app.db.clickhouse import query

OUT = Path(__file__).parent
YEARS = [y for y in range(2016, 2026) if y not in (2020, 2021)]


def main():
    rows = query("SELECT series, toYear(month) AS y, toMonth(month) AS m, value FROM vg_price_index "
                 "WHERE series IN ('air', 'rail') AND toYear(month) BETWEEN 2016 AND 2025")
    data = defaultdict(dict)
    for r in rows:
        data[(r["series"], r["y"])][r["m"]] = r["value"]
    summary = {}
    for series in ("air", "rail"):
        cases = []
        for y in YEARS:
            actual = data[(series, y)]
            if len(actual) < 12:
                continue
            idx = defaultdict(list)
            for yy in YEARS:
                if yy == y or len(data[(series, yy)]) < 12:
                    continue
                avg = st.mean(data[(series, yy)].values())
                for m, v in data[(series, yy)].items():
                    idx[m].append(v / avg - 1)
            season = {m: st.mean(v) for m, v in idx.items()}
            for target in range(1, 13):
                window = [((target - 1 + k) % 12) + 1 for k in (-2, -1, 0, 1, 2)]
                rec = min(window, key=lambda m: season[m])
                saving = 100 * (1 - actual[rec] / actual[target])
                rand = st.mean(100 * (1 - actual[m] / actual[target]) for m in window)
                cases.append({"year": y, "target": target, "recommended": rec, "saving_pct": saving,
                              "random_saving_pct": rand})
        moved = [c for c in cases if c["recommended"] != c["target"]]
        summary[series] = {
            "cases": len(cases), "cases_where_we_suggest_moving": len(moved),
            "mean_saving_pct_when_moving": round(st.mean(c["saving_pct"] for c in moved), 1) if moved else 0,
            "success_rate_when_moving_pct": round(100 * sum(c["saving_pct"] > 0 for c in moved) / len(moved), 1) if moved else None,
            "mean_saving_pct_all": round(st.mean(c["saving_pct"] for c in cases), 1),
            "mean_saving_pct_random_month_in_window": round(st.mean(c["random_saving_pct"] for c in cases), 1),
        }
    (OUT / "results.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
