"""Saisonnalité mensuelle sur DVF : volume et prix au m², corrigés de la tendance annuelle."""
from app.db.clickhouse import query

TYPOLOGIES = ("studio_t1", "t2", "t3plus")


def _zone_filter(zone):
    # zone = code commune (75111), département (75) ou code postal (75011)
    if len(zone) == 2:
        return "code_departement = {zone:String}"
    if zone.startswith("75") and zone[2] == "0":
        return "code_postal = {zone:String}"
    return "code_commune = {zone:String}"


def get_seasonality(zone, typology=None):
    """12 mois : nb de ventes, indice de volume (1 = moyenne), indice de prix (1 = médiane de l'année).

    Chaque année est normalisée par sa propre moyenne avant d'agréger, pour que la hausse ou la baisse
    du marché d'une année à l'autre ne soit pas confondue avec un effet de saison.
    """
    typ = "AND typology = {typ:String}" if typology else ""
    sql = f"""
    WITH monthly AS (
        SELECT toYear(date_mutation) AS y, toMonth(date_mutation) AS m,
               count() AS n, median(prix_m2) AS p
        FROM dvf_sales
        WHERE {_zone_filter(zone)} {typ}
        GROUP BY y, m
    ), yearly AS (
        SELECT y, avg(n) AS n_avg, median(p) AS p_med FROM monthly GROUP BY y HAVING count() = 12
    )
    SELECT m AS month, sum(n) AS sales, avg(n / n_avg) AS volume_index, avg(p / p_med) AS price_index,
           median(p) AS median_prix_m2, count() AS years
    FROM monthly INNER JOIN yearly USING y
    GROUP BY m ORDER BY m
    """
    return query(sql, {"zone": zone, "typ": typology or ""})
