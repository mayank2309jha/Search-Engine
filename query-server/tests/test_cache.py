"""Tests for app/cache.py's two SearchResultCache implementations and the
build_search_cache() switch between them. RedisSearchResultCache is tested
against a fake, in-memory client (FakeRedis below) rather than a real Redis
server -- it only needs get/set/scan_iter, so a real server would test the
redis-py client library more than it would test this project's own code.
"""
from app.cache import RedisSearchResultCache, SearchResultCache, build_search_cache


class TestSearchResultCache:
    def test_miss_returns_none(self):
        cache = SearchResultCache()
        assert cache.get("python") is None

    def test_set_then_get_round_trips(self):
        cache = SearchResultCache()
        cache.set("python", {"results": [1, 2, 3]})
        assert cache.get("python") == {"results": [1, 2, 3]}

    def test_key_normalization(self):
        # "Python", " python", "python " must all hit the same entry
        cache = SearchResultCache()
        cache.set("  Python  ", "value")
        assert cache.get("python") == "value"
        assert cache.get("PYTHON") == "value"

    def test_len_reflects_distinct_keys(self):
        cache = SearchResultCache()
        cache.set("python", 1)
        cache.set("java", 2)
        cache.set("python", 3)  # overwrite, not a new entry
        assert len(cache) == 2

    def test_lru_eviction_at_maxsize(self):
        cache = SearchResultCache(maxsize=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # evicts "a", the least recently used
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3


class FakeRedis:
    """Just enough of redis-py's interface for RedisSearchResultCache: get, set
    with an `ex` kwarg (accepted and ignored -- TTL expiry isn't under test
    here), and scan_iter for __len__.
    """

    def __init__(self):
        self._store: dict[str, bytes] = {}

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value, ex=None):
        self._store[key] = value

    def scan_iter(self, match=None):
        if match is None:
            yield from self._store.keys()
            return
        prefix = match.rstrip("*")
        yield from (k for k in self._store if k.startswith(prefix))

    def ping(self):
        return True


class TestRedisSearchResultCache:
    def test_miss_returns_none(self):
        cache = RedisSearchResultCache(FakeRedis())
        assert cache.get("python") is None

    def test_set_then_get_round_trips_through_pickle(self):
        cache = RedisSearchResultCache(FakeRedis())
        payload = {"results": [{"doc_id": 1, "score": 0.9}], "did_you_mean": None}
        cache.set("python", payload)
        assert cache.get("python") == payload

    def test_key_normalization(self):
        cache = RedisSearchResultCache(FakeRedis())
        cache.set("  Python  ", "value")
        assert cache.get("python") == "value"

    def test_keys_are_namespaced_with_prefix(self):
        client = FakeRedis()
        cache = RedisSearchResultCache(client, prefix="search:")
        cache.set("python", "value")
        assert "search:python" in client._store

    def test_len_counts_only_matching_prefix(self):
        client = FakeRedis()
        cache = RedisSearchResultCache(client, prefix="search:")
        cache.set("python", 1)
        cache.set("java", 2)
        client._store["other:unrelated"] = b"noise"
        assert len(cache) == 2


class TestBuildSearchCache:
    def test_no_redis_url_returns_in_memory_cache(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        cache = build_search_cache()
        assert isinstance(cache, SearchResultCache)

    def test_unreachable_redis_url_degrades_to_in_memory(self, monkeypatch):
        # A real hostname that (barring extraordinary bad luck) nothing is
        # listening on -- build_search_cache() must not raise, and must not
        # hang the test suite; redis-py's own connect timeout bounds this.
        monkeypatch.setenv("REDIS_URL", "redis://localhost:1")
        cache = build_search_cache()
        assert isinstance(cache, SearchResultCache)
