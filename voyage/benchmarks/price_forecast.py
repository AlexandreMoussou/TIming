"""Peut-on prévoir si un billet d'avion va monter ou baisser dans les 14 jours ?

Données : historiques de prix réels Google Flights (~60 jours chacun) des trajets interrogés, lus dans le cache
Valkey. Plusieurs règles sont comparées ; la règle est choisie sur une moitié des trajets (réglage) et évaluée
sur l'autre moitié (test), pour ne pas se juger sur les données qui ont servi à choisir.

Usage : python -m benchmarks.price_forecast   (depuis voyage/)
"""
import json
from pathlib import Path

from app.db.valkey import r

OUT = Path(__file__).parent
H, THR = 14, 2.0


def actual_dir(pts, t):
    chg = 100 * (pts[t + H] / pts[t] - 1)
    return "up" if chg > THR else "down" if chg < -THR else "flat"


def rule_flat(p):
    return "flat"


def rule_momentum(p):
    m = 100 * (p[-1] / p[-1 - H] - 1)
    return "up" if m >= 3 else "down" if m <= -3 else "flat"


def rule_reversion(p):
    w = p[-30:]
    med = sorted(w)[len(w) // 2]
    return "up" if p[-1] <= 0.95 * med else "down" if p[-1] >= 1.05 * med else "flat"


def rule_low_in_range(p):
    lo, hi = min(p), max(p)
    pos = (p[-1] - lo) / (hi - lo) if hi > lo else 0.5
    return "up" if pos <= 0.15 else "flat"


RULES = {"toujours stable": rule_flat, "tendance continue": rule_momentum, "retour à la médiane": rule_reversion,
         "prix au plus bas → hausse": rule_low_in_range}


def evaluate(histories, rule):
    hits = n = 0
    calls = {"up": [0, 0], "down": [0, 0]}
    for pts in histories:
        for t in range(30, len(pts) - H):
            pred, act = rule(pts[: t + 1]), actual_dir(pts, t)
            n += 1
            hits += pred == act
            if pred in calls:
                calls[pred][1] += 1
                calls[pred][0] += pred == act
    return {"cases": n, "accuracy_pct": round(100 * hits / n, 1) if n else None,
            "up_calls": calls["up"][1], "up_precision_pct": round(100 * calls["up"][0] / calls["up"][1], 1) if calls["up"][1] else None,
            "down_calls": calls["down"][1], "down_precision_pct": round(100 * calls["down"][0] / calls["down"][1], 1) if calls["down"][1] else None}


def main():
    series = []
    for k in sorted(r().scan_iter("vg:fares:*")):
        d = json.loads(r().get(k))
        if d.get("trend") and len(d["trend"]["points"]) >= 45:
            series.append((k.decode(), d["trend"]["points"]))
    tune, test = series[0::2], series[1::2]
    res = {"routes": len(series), "tune_routes": [k for k, _ in tune], "test_routes": [k for k, _ in test],
           "tune": {n: evaluate([p for _, p in tune], f) for n, f in RULES.items()}}
    best = max((n for n in RULES if n != "toujours stable"), key=lambda n: res["tune"][n]["accuracy_pct"])
    res["chosen_on_tune"] = best
    res["test"] = {n: evaluate([p for _, p in test], RULES[n]) for n in ("toujours stable", best)}
    (OUT / "price_forecast.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("tune_routes", "test_routes")}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
