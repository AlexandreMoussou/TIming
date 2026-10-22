from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.agents import orchestrator
from app.agents.tools import get_demand, get_price_seasonality, list_destinations
from app.db import postgres as pg
from app.db.clickhouse import query
from app.db.valkey import cached

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Départ")


class RecommendIn(BaseModel):
    mode: str = "train"
    destination: str | None = None
    travel_month: str | None = None
    flexible: bool = False
    handle: str | None = None
    today: str | None = None


class FeedbackIn(BaseModel):
    recommendation_id: int
    thumbs_up: bool


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    out = {"ok": True, "mode": "llm" if orchestrator.llm() else "rules"}
    for name, fn in (("clickhouse", lambda: query("SELECT 1 AS x")), ("postgres", lambda: pg.fetch_one("SELECT 1 AS x")),
                     ("valkey", lambda: cached("vg:health", 5, lambda: 1))):
        try:
            fn()
            out[name] = "up"
        except Exception as e:
            out[name] = f"down: {e.__class__.__name__}"
            out["ok"] = False
    return out


@app.get("/api/destinations")
def destinations():
    return list_destinations()


@app.get("/api/insights")
def insights():
    """Chiffres de la page d'accueil, calculés sur les données (rien d'écrit en dur)."""
    out = {}
    for mode in ("avion", "train"):
        months = get_price_seasonality(mode)["months"]
        hi, lo = max(months, key=lambda x: x["price_vs_year_pct"]), min(months, key=lambda x: x["price_vs_year_pct"])
        out[mode] = {"max": hi, "min": lo, "months": months}
    out["air_demand"] = get_demand("avion", "national")["months"]
    return out


@app.post("/api/recommend")
def recommend(body: RecommendIn):
    params = {"mode": body.mode, "destination": body.destination, "travel_month": body.travel_month,
              "flexible": body.flexible}
    return orchestrator.recommend(params, body.handle or None, body.today or date.today().isoformat())


@app.get("/api/runs/{run_id}")
def run(run_id: str):
    rows = pg.fetch("SELECT step, agent, kind, tool, input, output, duration_ms FROM vg_agent_runs "
                    "WHERE run_id = %s ORDER BY step", (run_id,))
    if not rows:
        raise HTTPException(404, "run inconnu")
    return {"run_id": run_id, "steps": rows}


@app.post("/api/feedback")
def feedback(body: FeedbackIn):
    r = pg.fetch_one("INSERT INTO vg_feedback (recommendation_id, thumbs_up) VALUES (%s,%s) RETURNING id",
                     (body.recommendation_id, body.thumbs_up))
    return {"ok": True, "id": r["id"]}


@app.get("/api/stats")
def stats():
    def run():
        r = query("""SELECT (SELECT count() FROM vg_rail_regularity) AS reg, (SELECT count() FROM vg_rail_fares) AS fares,
                            (SELECT count() FROM vg_tgvmax) AS tgvmax, (SELECT count() FROM vg_price_index) AS prices,
                            (SELECT count() FROM vg_air_pax) AS airpax, (SELECT max(month) FROM vg_air_pax) AS air_last""")[0]
        return {k: str(v) if k == "air_last" else int(v) for k, v in r.items()}
    s, _ = cached("vg:stats:v1", 600, run)
    s["calendar"] = pg.fetch_one("SELECT count(*) AS n FROM vg_calendar")["n"]
    return s
