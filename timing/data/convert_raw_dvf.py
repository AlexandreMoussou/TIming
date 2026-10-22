"""Convertit un fichier DVF brut (format DGFiP, séparateur |) au format geo-dvf pour data.ingest.

Le format brut n'a pas d'identifiant de mutation : on en reconstruit un à partir de
(date, valeur foncière, commune, voie, numéro), ce qui regroupe les lignes d'une même vente.
Pas de coordonnées dans ce format (longitude/latitude vides).

Usage : python -m data.convert_raw_dvf raw/dvf/dvf_2026_s1.zip 2026 75 92 93 94
"""
import csv
import gzip
import hashlib
import io
import sys
import zipfile
from pathlib import Path

OUT_COLS = ["id_mutation", "date_mutation", "numero_disposition", "nature_mutation", "valeur_fonciere",
            "code_postal", "code_commune", "nom_commune", "code_departement", "id_parcelle", "type_local",
            "surface_reelle_bati", "nombre_pieces_principales", "longitude", "latitude"]


def main(zip_path, year, deps):
    zip_path = Path(zip_path)
    z = zipfile.ZipFile(zip_path)
    src = io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8", errors="replace")
    writers, files = {}, {}
    for d in deps:
        files[d] = gzip.open(zip_path.parent / f"{year}_{d}.csv.gz", "wt", encoding="utf-8", newline="")
        writers[d] = csv.writer(files[d])
        writers[d].writerow(OUT_COLS)
    counts = dict.fromkeys(deps, 0)
    for r in csv.DictReader(src, delimiter="|"):
        dep = r["Code departement"]
        if dep not in writers:
            continue
        dd, mm, yy = r["Date mutation"].split("/")
        commune = dep + r["Code commune"].zfill(3)
        valeur = r["Valeur fonciere"].replace(",", ".")
        key = "|".join([r["Date mutation"], valeur, commune, r["Code voie"], r["No voie"]])
        mid = f"{year}R-" + hashlib.sha1(key.encode()).hexdigest()[:12]
        parcelle = commune + (r["Prefixe de section"] or "000").zfill(3) + r["Section"].zfill(2) + r["No plan"].zfill(4)
        writers[dep].writerow([mid, f"{yy}-{mm}-{dd}", r["No disposition"], r["Nature mutation"], valeur,
                               r["Code postal"].zfill(5) if r["Code postal"] else "", commune, r["Commune"],
                               dep, parcelle, r["Type local"], r["Surface reelle bati"],
                               r["Nombre pieces principales"], "", ""])
        counts[dep] += 1
    for f in files.values():
        f.close()
    print(counts)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
