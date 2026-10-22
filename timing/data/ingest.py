"""Charge DVF, carte des loyers et encadrement Paris dans ClickHouse (Aiven).

Usage : python -m data.ingest [--reset]   (depuis timing/)
"""
import csv
import gzip
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from app.db.clickhouse import client

RAW = Path(__file__).parent / "raw"
SCHEMA = Path(__file__).parent / "schema_ch.sql"
DWELLINGS = ("Appartement", "Maison")


def fnum(s):
    s = (s or "").strip().replace(",", ".")
    return float(s) if s else None


def typology(pieces):
    return "studio_t1" if pieces <= 1 else "t2" if pieces == 2 else "t3plus"


def apply_schema(c, reset):
    if reset:
        for t in ("dvf_transactions", "dvf_sales", "rent_indicators", "rent_caps_paris"):
            c.command(f"DROP TABLE IF EXISTS {t}")
    for stmt in SCHEMA.read_text(encoding="utf-8").split(";"):
        body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
        if body:
            c.command(body)


def ingest_dvf(c):
    raw_cols = ["id_mutation", "date_mutation", "nature_mutation", "valeur_fonciere", "code_postal",
                "code_commune", "nom_commune", "code_departement", "id_parcelle", "type_local",
                "surface_reelle_bati", "nombre_pieces", "longitude", "latitude"]
    sale_cols = ["id_mutation", "date_mutation", "code_commune", "code_postal", "code_departement",
                 "type_local", "nombre_pieces", "typology", "surface", "valeur_fonciere", "prix_m2",
                 "longitude", "latitude"]
    n_raw = n_sales = 0
    for f in sorted((RAW / "dvf").glob("*.csv.gz")):
        rows, muts = [], defaultdict(list)
        for r in csv.DictReader(gzip.open(f, "rt", encoding="utf-8")):
            pieces = fnum(r["nombre_pieces_principales"])
            row = [r["id_mutation"], date.fromisoformat(r["date_mutation"]), r["nature_mutation"],
                   fnum(r["valeur_fonciere"]), r["code_postal"], r["code_commune"], r["nom_commune"],
                   r["code_departement"], r["id_parcelle"], r["type_local"], fnum(r["surface_reelle_bati"]),
                   int(pieces) if pieces is not None else None, fnum(r["longitude"]), fnum(r["latitude"])]
            rows.append(row)
            muts[r["id_mutation"]].append(row)
        c.insert("dvf_transactions", rows, column_names=raw_cols)
        sales = []
        for mrows in muts.values():
            homes = [x for x in mrows if x[9] in DWELLINGS]
            # une vente = un seul logement, pas de terrain/local commercial facturé dans le même prix
            if len(homes) != 1 or any(x[9] not in DWELLINGS + ("Dépendance", "") for x in mrows):
                continue
            h = homes[0]
            if h[2] != "Vente" or not h[3] or not h[10] or h[10] < 9 or h[11] is None:
                continue
            pm2 = h[3] / h[10]
            if not 1000 <= pm2 <= 40000:  # écarte les valeurs aberrantes (erreurs de saisie, ventes symboliques)
                continue
            sales.append([h[0], h[1], h[5], h[4], h[7], h[9], h[11], typology(h[11]), h[10], h[3], pm2,
                          h[12], h[13]])
        c.insert("dvf_sales", sales, column_names=sale_cols)
        n_raw += len(rows)
        n_sales += len(sales)
        print(f"{f.name}: {len(rows)} lignes, {len(sales)} ventes retenues", flush=True)
    print(f"DVF total : {n_raw} lignes brutes, {n_sales} ventes nettoyées")


def ingest_rents(c):
    cols = ["millesime", "segment", "code_commune", "nom_commune", "code_departement", "loyer_m2",
            "loyer_m2_low", "loyer_m2_high", "type_pred", "nb_obs_commune", "r2_adj"]
    total = 0
    for f in sorted((RAW / "loyers").glob("*.csv")):
        year, seg = f.stem.split("_")[:2]
        rows = []
        with open(f, encoding="latin-1", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                r = {k.strip().strip('"').lower(): v for k, v in r.items()}
                rows.append([int(year), seg, r["insee_c"], r["libgeo"], r["dep"], fnum(r["loypredm2"]),
                             fnum(r["lwr.ipm2"]), fnum(r["upr.ipm2"]), r["typpred"],
                             int(fnum(r["nbobs_com"]) or 0), fnum(r["r2_adj"])])
        c.insert("rent_indicators", rows, column_names=cols)
        total += len(rows)
    print(f"Loyers : {total} lignes")


def ingest_caps(c):
    cols = ["annee", "id_quartier", "nom_quartier", "code_grand_quartier", "code_commune", "pieces",
            "epoque", "meuble", "loyer_ref", "loyer_max", "loyer_min", "lat", "lon"]
    rows = []
    with open(RAW / "encadrement" / "encadrement.csv", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            lat, lon = (fnum(x) for x in r["geo_point_2d"].split(",")) if r["geo_point_2d"] else (None, None)
            rows.append([int(r["annee"]), int(r["id_quartier"]), r["nom_quartier"], r["code_grand_quartier"],
                         r["code_grand_quartier"][:5], int(r["piece"]), r["epoque"],
                         1 if r["meuble_txt"].strip() == "meublé" else 0, fnum(r["ref"]), fnum(r["max"]),
                         fnum(r["min"]), lat, lon])
    c.insert("rent_caps_paris", rows, column_names=cols)
    print(f"Encadrement Paris : {len(rows)} lignes")


if __name__ == "__main__":
    c = client()
    apply_schema(c, "--reset" in sys.argv)
    ingest_rents(c)
    ingest_caps(c)
    ingest_dvf(c)
