-- ClickHouse (Aiven) : données de marché, analytique saisonnière

-- Lignes DVF brutes (une ligne par local / disposition), toutes communes
CREATE TABLE IF NOT EXISTS dvf_transactions (
    id_mutation         String,
    date_mutation       Date,
    nature_mutation     LowCardinality(String),
    valeur_fonciere     Nullable(Float64),
    code_postal         LowCardinality(String),
    code_commune        LowCardinality(String),
    nom_commune         LowCardinality(String),
    code_departement    LowCardinality(String),
    id_parcelle         String,
    type_local          LowCardinality(String),
    surface_reelle_bati Nullable(Float32),
    nombre_pieces       Nullable(UInt8),
    longitude           Nullable(Float64),
    latitude            Nullable(Float64)
) ENGINE = MergeTree
PARTITION BY toYear(date_mutation)
ORDER BY (code_departement, code_commune, date_mutation);

-- Ventes nettoyées : une ligne par mutation contenant exactement un logement
-- (appartement ou maison), prix au m² calculable sans double comptage
CREATE TABLE IF NOT EXISTS dvf_sales (
    id_mutation      String,
    date_mutation    Date,
    code_commune     LowCardinality(String),
    code_postal      LowCardinality(String),
    code_departement LowCardinality(String),
    type_local       LowCardinality(String),
    nombre_pieces    UInt8,
    typology         LowCardinality(String),  -- studio_t1, t2, t3plus
    surface          Float32,
    valeur_fonciere  Float64,
    prix_m2          Float64,
    longitude        Nullable(Float64),
    latitude         Nullable(Float64)
) ENGINE = MergeTree
PARTITION BY toYear(date_mutation)
ORDER BY (code_commune, typology, date_mutation);

-- Carte des loyers (indicateurs d'annonces, ministère), par commune et millésime
CREATE TABLE IF NOT EXISTS rent_indicators (
    millesime     UInt16,
    segment       LowCardinality(String),  -- app, app12, app3, mai
    code_commune  LowCardinality(String),
    nom_commune   String,
    code_departement LowCardinality(String),
    loyer_m2      Float64,
    loyer_m2_low  Float64,
    loyer_m2_high Float64,
    type_pred     LowCardinality(String),
    nb_obs_commune UInt32,
    r2_adj        Nullable(Float64)
) ENGINE = MergeTree
ORDER BY (code_commune, segment, millesime);

-- Encadrement des loyers Paris (loyers de référence par quartier)
CREATE TABLE IF NOT EXISTS rent_caps_paris (
    annee         UInt16,
    id_quartier   UInt16,
    nom_quartier  String,
    code_grand_quartier String,
    code_commune  LowCardinality(String),  -- 751xx dérivé du grand quartier
    pieces        UInt8,
    epoque        LowCardinality(String),
    meuble        UInt8,
    loyer_ref     Float64,
    loyer_max     Float64,
    loyer_min     Float64,
    lat           Nullable(Float64),
    lon           Nullable(Float64)
) ENGINE = MergeTree
ORDER BY (code_commune, id_quartier, pieces, annee);
