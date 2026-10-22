from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agents import orchestrator
from app.agents.tools import get_seasonality
from app.db import postgres as pg
from app.db.clickhouse import query
from app.db.valkey import cached

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Timing")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class RecommendIn(BaseModel):
    text: str | None = None
    handle: str | None = None
    today: str | None = None
    intent: str | None = None
    typology: str | None = None
    zone: str | None = None
    move_in: str | None = None
    budget: int | None = None
    flexible: bool = False


class FeedbackIn(BaseModel):
    recommendation_id: int
    thumbs_up: bool
    comment: str | None = None


class AlertIn(BaseModel):
    handle: str
    recommendation_id: int


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    out = {"ok": True, "mode": "llm" if orchestrator.llm() else "rules"}
    for name, fn in (("clickhouse", lambda: query("SELECT 1 AS x")),
                     ("postgres", lambda: pg.fetch_one("SELECT 1 AS x")),
                     ("valkey", lambda: cached("health", 5, lambda: 1))):
        try:
            fn()
            out[name] = "up"
        except Exception as e:
            out[name] = f"down: {e.__class__.__name__}"
            out["ok"] = False
    return out


@app.post("/api/recommend")
def recommend(body: RecommendIn):
    overrides = {k: getattr(body, k) for k in ("intent", "typology", "zone", "move_in", "budget", "flexible")}
    return orchestrator.recommend(body.text, body.handle or None, body.today or date.today().isoformat(), overrides)


@app.get("/api/seasonality")
def seasonality(zone: str = "75", typology: str | None = None):
    return get_seasonality(zone, typology)


@app.get("/api/runs/{run_id}")
def run(run_id: str):
    rows = pg.fetch("SELECT step, agent, kind, tool, input, output, duration_ms, created_at FROM agent_runs "
                    "WHERE run_id = %s ORDER BY step", (run_id,))
    if not rows:
        raise HTTPException(404, "run inconnu")
    return {"run_id": run_id, "steps": rows}


@app.post("/api/feedback")
def feedback(body: FeedbackIn):
    r = pg.fetch_one("INSERT INTO feedback (recommendation_id, thumbs_up, comment) VALUES (%s,%s,%s) RETURNING id",
                     (body.recommendation_id, body.thumbs_up, body.comment))
    return {"ok": True, "id": r["id"]}


@app.post("/api/alerts")
def alert(body: AlertIn):
    rec = pg.fetch_one("SELECT window_start, window_end FROM recommendations WHERE id = %s", (body.recommendation_id,))
    if not rec:
        raise HTTPException(404, "recommandation inconnue")
    a = {"alert": {"recommendation_id": body.recommendation_id, "window_start": str(rec["window_start"]),
                   "window_end": str(rec["window_end"])}}
    pg.fetch("""INSERT INTO users (handle, profile) VALUES (%s, %s)
                ON CONFLICT (handle) DO UPDATE SET profile = users.profile || EXCLUDED.profile RETURNING id""",
             (body.handle, pg.jsonb(a)))
    return {"ok": True, **a}


@app.get("/api/stats")
def stats():
    def run():
        ch = query("""SELECT (SELECT count() FROM dvf_transactions) AS dvf_rows, (SELECT count() FROM dvf_sales) AS sales,
                             (SELECT count() FROM rent_indicators) AS rent_rows, (SELECT count() FROM rent_caps_paris) AS caps,
                             (SELECT max(date_mutation) FROM dvf_sales) AS last_sale""")[0]
        return {k: str(v) if k == "last_sale" else int(v) for k, v in ch.items()}
    s, hit = cached("stats:v1", 600, run)
    p = pg.fetch_one("""SELECT (SELECT count(*) FROM events) AS events, (SELECT count(*) FROM searches) AS searches,
                               (SELECT count(*) FROM agent_runs) AS agent_steps, (SELECT count(*) FROM users) AS users""")
    return {**s, **p, "cache_hit": hit}
