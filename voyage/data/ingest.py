"""Charge les données de voyage dans Aiven : ClickHouse (séries, trajets, places) et PostgreSQL (calendrier).

Sources : Eurostat (indices de prix HICP train/avion, passagers aériens France), SNCF Open Data (régularité
mensuelle TGV par trajet, tarifs TGV INOUI/OUIGO, places TGVmax à 30 jours), Éducation nationale (vacances
scolaires), calendrier.api.gouv.fr (jours fériés).

Usage : python -m data.ingest   (depuis voyage/)
"""
import json
from datetime import date
from pathlib import Path

import psycopg

from app.config import PG_URI
from app.db.clickhouse import client

RAW = Path(__file__).parent / "raw"

CH_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS vg_price_index (series LowCardinality(String), month Date, value Float64)
       ENGINE = MergeTree ORDER BY (series, month)""",
    """CREATE TABLE IF NOT EXISTS vg_air_pax (coverage LowCardinality(String), month Date, passengers Float64)
       ENGINE = MergeTree ORDER BY (coverage, month)""",
    """CREATE TABLE IF NOT EXISTS vg_rail_regularity (month Date, service LowCardinality(String),
       origin LowCardinality(String), destination LowCardinality(String), duration_min Float32,
       planned UInt32, cancelled UInt32, late_arrival UInt32, avg_delay_late_min Float32)
       ENGINE = MergeTree ORDER BY (origin, destination, month)""",
    """CREATE TABLE IF NOT EXISTS vg_rail_fares (carrier LowCardinality(String), origin LowCardinality(String),
       destination LowCardinality(String), class LowCardinality(String), profile LowCardinality(String),
       price_min Float32, price_max Float32) ENGINE = MergeTree ORDER BY (origin, destination)""",
    """CREATE TABLE IF NOT EXISTS vg_air_route (dest_icao LowCardinality(String), dest_name String,
       country LowCardinality(String), month Date, passengers Float64)
       ENGINE = MergeTree ORDER BY (dest_icao, month)""",
    """CREATE TABLE IF NOT EXISTS vg_tgvmax (day Date, train_no String, axe LowCardinality(String),
       origin LowCardinality(String), destination LowCardinality(String), dep_time String, arr_time String,
       available UInt8) ENGINE = MergeTree ORDER BY (origin, destination, day)""",
]

PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS vg_users (id SERIAL PRIMARY KEY, handle TEXT UNIQUE NOT NULL,
    profile JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS vg_searches (id SERIAL PRIMARY KEY, user_id INT REFERENCES vg_users(id),
    params JSONB NOT NULL, label TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS vg_recommendations (id SERIAL PRIMARY KEY, search_id INT REFERENCES vg_searches(id),
    payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS vg_feedback (id SERIAL PRIMARY KEY, recommendation_id INT REFERENCES vg_recommendations(id),
    thumbs_up BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS vg_calendar (id SERIAL PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
    zones TEXT, start_date DATE NOT NULL, end_date DATE NOT NULL, source TEXT NOT NULL,
    UNIQUE (kind, name, zones, start_date));
CREATE TABLE IF NOT EXISTS vg_agent_runs (id BIGSERIAL PRIMARY KEY, run_id UUID NOT NULL, step INT NOT NULL,
    agent TEXT NOT NULL, kind TEXT NOT NULL, tool TEXT, input JSONB, output JSONB, duration_ms INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS vg_agent_runs_run_idx ON vg_agent_runs (run_id, step);
"""


def month(s):
    y, m = s[:7].split("-")
    return date(int(y), int(m), 1)


def eurostat_rows(path, key_dim):
    d = json.load(open(path, encoding="utf-8"))
    dims = d["id"]
    sizes = d["size"]
    idx = {k: {v: i for v, i in d["dimension"][k]["category"]["index"].items()} for k in dims}
    inv = {k: {i: v for v, i in idx[k].items()} for k in dims}
    out = []
    for flat, val in d["value"].items():
        flat = int(flat)
        coords = {}
        for k, size in zip(reversed(dims), reversed(sizes)):
            coords[k] = inv[k][flat % size]
            flat //= size
        out.append((coords[key_dim], month(coords["time"]), float(val)))
    return out


def ingest_air_routes(c):
    """Passagers par liaison Paris (Roissy + Orly) → destination, Eurostat avia_par_fr (pairs_sel.json)."""
    names = json.load(open(RAW / "pairs_sel.json", encoding="utf-8"))["names"]
    agg = {}
    for pair, m, v in eurostat_rows(RAW / "airroutes.json", "airp_pr"):
        icao = pair[-4:]
        k = (icao, pair.split("_")[2], m)
        agg[k] = agg.get(k, 0) + v
    rows = [(icao, names[icao], country, m, v) for (icao, country, m), v in agg.items()]
    c.insert("vg_air_route", rows, column_names=["dest_icao", "dest_name", "country", "month", "passengers"])
    print(f"Eurostat liaisons Paris : {len(rows)} points, {len({r[0] for r in rows})} destinations")


def main():
    c = client()
    for t in ("vg_price_index", "vg_air_pax", "vg_rail_regularity", "vg_rail_fares", "vg_tgvmax", "vg_air_route"):
        c.command(f"DROP TABLE IF EXISTS {t}")
    for stmt in CH_SCHEMA:
        c.command(stmt)

    names = {"CP0731": "rail", "CP0733": "air", "CP00": "all_items"}
    rows = [(names[s], m, v) for s, m, v in eurostat_rows(RAW / "hicp.json", "coicop")]
    c.insert("vg_price_index", rows, column_names=["series", "month", "value"])
    print(f"Eurostat HICP : {len(rows)} points")

    rows = eurostat_rows(RAW / "airpax.json", "tra_cov")
    c.insert("vg_air_pax", rows, column_names=["coverage", "month", "passengers"])
    print(f"Eurostat passagers aériens : {len(rows)} points")

    ingest_air_routes(c)

    reg = json.load(open(RAW / "regularite-mensuelle-tgv-aqst.json", encoding="utf-8"))
    rows = [(month(r["date"]), r["service"] or "", r["gare_depart"], r["gare_arrivee"], r["duree_moyenne"] or 0,
             int(r["nb_train_prevu"] or 0), int(r["nb_annulation"] or 0), int(r["nb_train_retard_arrivee"] or 0),
             r["retard_moyen_arrivee"] or 0) for r in reg]
    c.insert("vg_rail_regularity", rows, column_names=["month", "service", "origin", "destination", "duration_min",
                                                        "planned", "cancelled", "late_arrival", "avg_delay_late_min"])
    print(f"SNCF régularité : {len(rows)} lignes")

    fares = json.load(open(RAW / "tarifs-tgv-inoui-ouigo.json", encoding="utf-8"))
    rows = [(r["transporteur"], r["gare_origine"], r["gare_destination"], str(r["classe"] or ""),
             r["profil_tarifaire"] or "", r["prix_minimum"] or 0, r["prix_maximum"] or 0) for r in fares]
    c.insert("vg_rail_fares", rows, column_names=["carrier", "origin", "destination", "class", "profile",
                                                  "price_min", "price_max"])
    print(f"SNCF tarifs : {len(rows)} lignes")

    tg = json.load(open(RAW / "tgvmax.json", encoding="utf-8"))
    rows = [(date.fromisoformat(r["date"]), str(r["train_no"]), r["axe"] or "", r["origine"], r["destination"],
             r["heure_depart"] or "", r["heure_arrivee"] or "", 1 if r["od_happy_card"] == "OUI" else 0) for r in tg]
    c.insert("vg_tgvmax", rows, column_names=["day", "train_no", "axe", "origin", "destination", "dep_time",
                                              "arr_time", "available"])
    print(f"SNCF TGVmax : {len(rows)} trains")

    with psycopg.connect(PG_URI, autocommit=True) as pg:
        pg.execute(PG_SCHEMA)
        pg.execute("DELETE FROM vg_calendar")
        vac = json.load(open(RAW / "vacances.json", encoding="utf-8"))
        seen, cal = set(), []
        for v in vac:
            if v.get("population") not in ("-", "Élèves", None) or not v.get("start_date"):
                continue
            key = (v["description"], v["zones"], v["start_date"][:10])
            if key in seen:
                continue
            seen.add(key)
            cal.append(("vacances", v["description"], v["zones"], v["start_date"][:10], v["end_date"][:10],
                        "data.education.gouv.fr"))
        for d, name in json.load(open(RAW / "feries.json", encoding="utf-8")).items():
            if d >= "2018-01-01":
                cal.append(("ferie", name, "France", d, d, "calendrier.api.gouv.fr"))
        with pg.cursor() as cur:
            cur.executemany("""INSERT INTO vg_calendar (kind, name, zones, start_date, end_date, source)
                               VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", cal)
        print(f"Calendrier : {len(cal)} périodes (vacances par zone + jours fériés)")


if __name__ == "__main__":
    main()
