import logging
import threading
import time
from collections import OrderedDict


logger = logging.getLogger(__name__)

MAX_CACHE_ENTRIES = 512

_cache = OrderedDict()
_lock = threading.Lock()


def _get_cached_core(key, fn, ttl=5):
    now = time.time()
    with _lock:
        entry = _cache.get(key)
        if entry:
            value, expires_at = entry
            if now < expires_at:
                _cache.move_to_end(key)
                logger.info("Cache lookup", extra={"metric": "cache_hit", "cache_key": key})
                return value, "hit"
            _cache.pop(key, None)
            logger.info("Cache lookup", extra={"metric": "cache_expired", "cache_key": key})

    logger.info("Cache lookup", extra={"metric": "cache_miss", "cache_key": key})

    value = fn()
    stored_at = time.time()

    with _lock:
        while len(_cache) >= MAX_CACHE_ENTRIES:
            evicted_key, _ = _cache.popitem(last=False)
            logger.info(
                "Cache eviction",
                extra={"metric": "cache_evicted", "cache_key": evicted_key},
            )
        _cache[key] = (value, stored_at + ttl)

    return value, "miss"


def get_cached(key, fn, ttl=5):
    value, _ = _get_cached_core(key, fn, ttl)
    return value


def get_cached_with_status(key, fn, ttl=5):
    return _get_cached_core(key, fn, ttl)


def invalidate_cache_key(key):
    with _lock:
        _cache.pop(key, None)


def invalidate_cache_prefix(prefix):
    with _lock:
        keys = [key for key in _cache if key.startswith(prefix)]
        for key in keys:
            _cache.pop(key, None)


def invalidate_user_cache(user_id):
    invalidate_cache_prefix(f"user:{user_id}:")
