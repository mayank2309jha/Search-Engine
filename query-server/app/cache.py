# Repeated-query cache for /search results, keyed by normalized query string.
# Caches the full ranked+deduped result list (pre-pagination), so page 2 of an
# already-seen query is still a cache hit instead of re-running retrieval+ranking.
#
# Two implementations, one interface (.get/.set/.make_key/__len__): SearchResultCache
# is in-memory and per-process -- correct and simplest at one-instance scale, but
# each process (and each replica, once there's more than one) keeps its own copy,
# so a cache hit on worker A is a cache miss on worker B for the exact same query.
# RedisSearchResultCache fixes that by moving the cached state somewhere shared;
# build_search_cache() below picks between them based on REDIS_URL so main.py
# never has to know which one it got.
import os
import pickle

from cachetools import LRUCache

DEFAULT_MAXSIZE = 256


class SearchResultCache:
    def __init__(self, maxsize: int = DEFAULT_MAXSIZE):
        self._store: LRUCache = LRUCache(maxsize=maxsize)

    # normalize so "Python", " python", "python " all hit the same cache entry
    @staticmethod
    def make_key(query: str) -> str:
        return query.strip().lower()

    def get(self, query: str):
        return self._store.get(self.make_key(query))

    def set(self, query: str, value) -> None:
        self._store[self.make_key(query)] = value

    def __len__(self) -> int:
        return len(self._store)


class RedisSearchResultCache:
    """Same interface as SearchResultCache, backed by Redis so cached results are
    shared across every process/replica instead of living per-worker. Takes a
    connected client rather than a URL, so it's trivially testable against a fake
    client with no real Redis server involved (see tests/test_cache.py).

    Cached values are pickled: the payload (deduped result list, did_you_mean,
    the structured query) is plain Python data with no cross-service contract to
    keep stable, so pickle is the simplest correct choice here -- unlike
    data/index.bin, nothing outside this process ever needs to read this format.
    """

    def __init__(self, redis_client, ttl_seconds: int = 3600, prefix: str = "search:"):
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._prefix = prefix

    @staticmethod
    def make_key(query: str) -> str:
        return query.strip().lower()

    def _redis_key(self, query: str) -> str:
        return self._prefix + self.make_key(query)

    def get(self, query: str):
        raw = self._redis.get(self._redis_key(query))
        return pickle.loads(raw) if raw is not None else None

    def set(self, query: str, value) -> None:
        self._redis.set(self._redis_key(query), pickle.dumps(value), ex=self._ttl)

    def __len__(self) -> int:
        # Redis has no O(1) "count keys under this prefix" -- SCAN is fine since
        # this is only ever used for diagnostics/tests, never a hot path.
        return sum(1 for _ in self._redis.scan_iter(match=self._prefix + "*"))


def build_search_cache(maxsize: int = DEFAULT_MAXSIZE):
    """REDIS_URL unset -> in-memory (today's default, unchanged). REDIS_URL set
    -> Redis-backed, so cache state survives a process restart and is shared
    across replicas. If REDIS_URL is set but Redis is actually unreachable, this
    degrades to in-memory rather than failing startup -- the same "don't take the
    whole service down over a cache" judgment already applied to crawler.db being
    absent (app/crawler_db.py) and to the pagerank table being missing (the C++
    engine's own Parser::loadPageRanks()).
    """
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        try:
            import redis

            client = redis.from_url(redis_url)
            client.ping()
            return RedisSearchResultCache(client)
        except Exception:
            pass
    return SearchResultCache(maxsize=maxsize)
