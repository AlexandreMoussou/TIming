-- Reference data: one row per Vélib station (station_information.json)
CREATE TABLE IF NOT EXISTS stations (
  id        text PRIMARY KEY,
  code      text,
  name      text NOT NULL,
  lat       double precision NOT NULL,
  lon       double precision NOT NULL,
  capacity  int NOT NULL
);

-- Time series: one row per station per minute (station_status.json)
CREATE TABLE IF NOT EXISTS snapshots (
  ts          timestamptz NOT NULL,
  station_id  text NOT NULL,
  bikes       int NOT NULL,
  mechanical  int NOT NULL,
  ebike       int NOT NULL,
  docks       int NOT NULL,
  is_renting  boolean NOT NULL,
  is_returning boolean NOT NULL,
  PRIMARY KEY (station_id, ts)
);
CREATE INDEX IF NOT EXISTS snapshots_ts_idx ON snapshots (ts);

-- Agent memory: every run, with its full step-by-step trace
CREATE TABLE IF NOT EXISTS agent_runs (
  id          bigserial PRIMARY KEY,
  started_at  timestamptz NOT NULL DEFAULT now(),
  data_ts     timestamptz NOT NULL,
  mode        text NOT NULL,
  steps       jsonb NOT NULL,
  brief       text,
  stats       jsonb
);

-- Every forecast the agent makes, later resolved against what really happened
CREATE TABLE IF NOT EXISTS predictions (
  run_id          bigint NOT NULL REFERENCES agent_runs(id),
  station_id      text NOT NULL,
  made_at         timestamptz NOT NULL,
  target_ts       timestamptz NOT NULL,
  bikes_now       int NOT NULL,
  rate_per_min    double precision NOT NULL,
  predicted_bikes double precision NOT NULL,
  actual_bikes    int,
  resolved_at     timestamptz,
  PRIMARY KEY (run_id, station_id)
);
CREATE INDEX IF NOT EXISTS predictions_unresolved_idx ON predictions (target_ts) WHERE actual_bikes IS NULL;

-- Learned parameters (what the agent has learned from its past errors)
CREATE TABLE IF NOT EXISTS station_bias (
  station_id  text PRIMARY KEY,
  bias        double precision NOT NULL,
  n           int NOT NULL,
  updated_at  timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS model_params (
  name        text PRIMARY KEY,
  value       double precision NOT NULL,
  n           int NOT NULL,
  updated_at  timestamptz NOT NULL
);

-- Truck missions proposed to the dispatcher
CREATE TABLE IF NOT EXISTS missions (
  run_id           bigint NOT NULL REFERENCES agent_runs(id),
  truck            int NOT NULL,
  seq              int NOT NULL,
  pickup_station   text NOT NULL,
  dropoff_station  text NOT NULL,
  bikes            int NOT NULL,
  km               double precision NOT NULL,
  avoided_minutes  double precision NOT NULL,
  reason           text NOT NULL,
  PRIMARY KEY (run_id, truck, seq)
);
