import json

import redis

from app.config import VALKEY_URI

_r = None


def r():
    global _r
    if _r is None and VALKEY_URI:
        _r = redis.from_url(VALKEY_URI, socket_timeout=3)
    return _r


def cached(key, ttl, fn):
    """Lit dans Valkey, sinon calcule et met en cache. Renvoie (valeur, hit)."""
    try:
        if r() is not None:
            v = r().get(key)
            if v is not None:
                return json.loads(v), True
    except redis.RedisError:
        pass
    v = fn()
    try:
        if r() is not None:
            r().setex(key, ttl, json.dumps(v, default=str))
    except redis.RedisError:
        pass
    return v, False
