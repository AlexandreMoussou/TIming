import json
import threading

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import PG_URI

# Une connexion persistante partagée (ouvrir une connexion TLS vers Aiven coûte ~300 ms)
_conn = None
_lock = threading.Lock()


def _get():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg.connect(PG_URI, row_factory=dict_row, autocommit=True)
    return _conn


def fetch(sql, params=()):
    global _conn
    with _lock:
        try:
            return _get().execute(sql, params).fetchall()
        except psycopg.OperationalError:
            _conn = None  # connexion coupée : on rouvre une fois
            return _get().execute(sql, params).fetchall()


def fetch_one(sql, params=()):
    rows = fetch(sql, params)
    return rows[0] if rows else None


def jsonb(v):
    return Jsonb(json.loads(json.dumps(v, default=str)))
