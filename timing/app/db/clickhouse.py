import threading
from urllib.parse import urlparse

import clickhouse_connect

from app.config import CH_URI

# Un client par thread : une session ClickHouse n'accepte pas de requêtes concurrentes
_local = threading.local()


def client():
    c = getattr(_local, "client", None)
    if c is None:
        u = urlparse(CH_URI)
        c = _local.client = clickhouse_connect.get_client(
            host=u.hostname, port=u.port, username=u.username, password=u.password,
            secure=u.scheme == "https", database=(u.path.strip("/") or "default"),
            autogenerate_session_id=False,
        )
    return c


def query(sql, params=None):
    r = client().query(sql, parameters=params or {})
    return [dict(zip(r.column_names, row)) for row in r.result_rows]
