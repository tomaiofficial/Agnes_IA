"""Tests pour core/cache/redis_cache.py"""
import pytest
from core.cache.redis_cache import RedisCache, get_cache, reset_cache


@pytest.fixture(autouse=True)
def clean_cache():
    reset_cache()
    yield
    reset_cache()


@pytest.fixture
def cache():
    # Force le fallback mémoire (pas de REDIS_URL en test)
    return RedisCache(url="")


def test_set_get(cache):
    cache.set("key1", {"a": 1, "b": [1, 2, 3]})
    assert cache.get("key1") == {"a": 1, "b": [1, 2, 3]}


def test_get_missing(cache):
    assert cache.get("nonexistent") is None


def test_ttl_expiration(cache):
    cache.set("temp", "value", ttl=1)
    # set sérialise en JSON → get_raw renvoie '"value"' (avec quotes)
    assert cache.get_raw("temp") == '"value"'
    import time

    time.sleep(1.2)
    assert cache.get("temp") is None


def test_delete(cache):
    cache.set("key", "value")
    assert cache.delete("key") is True
    assert cache.get("key") is None
    assert cache.delete("key") is False


def test_get_or_set(cache):
    calls = []

    def producer():
        calls.append(1)
        return {"computed": True}

    assert cache.get_or_set("computed", producer) == {"computed": True}
    assert cache.get_or_set("computed", producer) == {"computed": True}
    assert len(calls) == 1  # le producer n'est appelé qu'une fois


def test_preload(cache):
    n = cache.preload({"a": 1, "b": 2, "c": 3})
    assert n == 3
    assert cache.get("a") == 1


def test_preload_skips_existing(cache):
    cache.set("x", 1)
    n = cache.preload({"x": 99, "y": 100})
    assert n == 1  # seul "y" est nouveau
    assert cache.get("x") == 1  # valeur inchangée


def test_preload_voices(cache):
    n = cache.preload_voices({"zh-CN-XiaoxiaoNeural": {"name": "Xiaoxiao"}})
    assert n == 1
    assert cache.get("voice:zh-CN-XiaoxiaoNeural") == {"name": "Xiaoxiao"}


def test_get_stats(cache):
    stats = cache.get_stats()
    assert stats["backend"] == "memory"
    assert "entries" in stats
    assert stats["ttl_default"] == 3600


def test_singleton_get_cache():
    c1 = get_cache()
    c2 = get_cache()
    assert c1 is c2


def test_flush(cache):
    cache.set("a", 1)
    cache.set("b", 2)
    cache.flush()
    assert cache.get("a") is None
    assert cache.get("b") is None
