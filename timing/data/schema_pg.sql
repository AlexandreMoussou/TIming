-- PostgreSQL (Aiven) : mémoire utilisateur, événements, traces d'agents

CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    handle      TEXT UNIQUE NOT NULL,
    profile     JSONB NOT NULL DEFAULT '{}',   -- type de bien, budget, zones préférées
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS searches (
    id          SERIAL PRIMARY KEY,
    user_id     INT REFERENCES users(id),
    query_text  TEXT NOT NULL,
    params      JSONB NOT NULL DEFAULT '{}',   -- sortie de l'intake agent
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recommendations (
    id          SERIAL PRIMARY KEY,
    search_id   INT REFERENCES searches(id),
    window_start DATE,
    window_end   DATE,
    payload     JSONB NOT NULL,                -- fenêtre, courbe, classement, événements, chiffres sourcés
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS feedback (
    id                SERIAL PRIMARY KEY,
    recommendation_id INT REFERENCES recommendations(id),
    thumbs_up         BOOLEAN NOT NULL,
    comment           TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL,              -- election, academic, sport, season, legal, culture
    start_date   DATE NOT NULL,
    end_date     DATE NOT NULL,
    scope        TEXT NOT NULL DEFAULT 'FR', -- FR, 75, code commune...
    expected_effect TEXT,
    source       TEXT,                       -- seed manuel ou URL trouvée par l'events agent
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, start_date)
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id          BIGSERIAL PRIMARY KEY,
    run_id      UUID NOT NULL,
    step        INT NOT NULL,
    agent       TEXT NOT NULL,
    kind        TEXT NOT NULL,               -- llm, tool_call, tool_result, final
    tool        TEXT,
    input       JSONB,
    output      JSONB,
    duration_ms INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_runs_run_idx ON agent_runs (run_id, step);
