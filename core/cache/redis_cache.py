"""
core/cache/redis_cache.py — Cache Redis + préchargement (v8.0)

Cache distribué avec fallback mémoire :
  - Redis (si `redis` installé et `REDIS_URL` configuré)
  - Sinon fallback dictionnaire en mémoire (LRU simple)

Fonctionnalités :
  - get / set / delete avec TTL
  - Cache d'URL de vidéos générées (évite régénérations)
  - Cache des résultats de prompts optimisés
  - Préchargement (preload) des ressources fréquentes :
    voix TTS, templates de prompts, modèles de styles

Usage::

    from core.cache.redis_cache import get_cache, RedisCache

    cache = get_cache()
    cache.set("video:url:abc", "https://...", ttl=3600)
    url = cache.get("video:url:abc")

    cache.preload({"voice:zh-CN-XiaoxiaoNeural": {"name": "Xiaoxiao"}})
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Optional

logger = logging.getLogger(__name__)

# URL Redis par défaut (peut être surchargée par REDIS_URL)
REDIS_URL = os.environ.get("REDIS_URL", "")


class MemoryCacheBackend:
    """Backend mémoire (LRU) — fallback quand Redis n'est pas disponible."""

    def __init__(self, max_items: int = 1024):
        self._store: "OrderedDict[str, tuple[float, str]]" = OrderedDict()
        self._max_items = max_items
        self._lock = Lock()

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [k for k, (exp, _) in self._store.items() if exp != 0 and exp < now]
        for k in expired:
            self._store.pop(k, None)

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            self._purge_expired()
            item = self._store.get(key)
            if item is None:
                return None
            exp, value = item
            if exp != 0 and exp < time.time():
                self._store.pop(key, None)
                return None
            # LRU : remettre à la fin
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        with self._lock:
            exp = (time.time() + ttl) if ttl else 0
            self._store[key] = (exp, value)
            self._store.move_to_end(key)
            while len(self._store) > self._max_items:
                self._store.popitem(last=False)

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._store.pop(key, None) is not None

    def flush(self) -> None:
        with self._lock:
            self._store.clear()

    def keys(self, prefix: str = "") -> list[str]:
        with self._lock:
            self._purge_expired()
            return [k for k in self._store if k.startswith(prefix)]

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired()
            return len(self._store)


class RedisCache:
    """Cache avec backend Redis ou mémoire.

    Toutes les méthodes sont fail-safe : si Redis est indisponible,
    on retombe sur le backend mémoire sans jamais lever d'exception.
    """

    def __init__(self, url: str = "", ttl_default: int = 3600):
        self.ttl_default = ttl_default
        self._redis = None
        self._memory = MemoryCacheBackend()
        url = url or REDIS_URL
        if url:
            try:
                import redis  # type: ignore

                pool = redis.ConnectionPool.from_url(url, decode_responses=True)
                self._redis = redis.Redis(connection_pool=pool)
                self._redis.ping()
                logger.info("[Cache] Redis connecté (%s)", url.split("@")[-1][:40])
            except Exception as e:  # noqa: BLE001
                logger.warning("[Cache] Redis indisponible, fallback mémoire: %s", e)
                self._redis = None
        else:
            logger.info("[Cache] Pas de REDIS_URL, fallback mémoire")

    @property
    def is_redis(self) -> bool:
        return self._redis is not None

    def get(self, key: str) -> Optional[Any]:
        """Retourne une valeur (objet Python) ou None."""
        if self._redis is not None:
            try:
                raw = self._redis.get(key)
                if raw is None:
                    return None
                return json.loads(raw)
            except Exception as e:  # noqa: BLE001
                logger.debug("[Cache] Redis get failed: %s", e)
        raw = self._memory.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    def get_raw(self, key: str) -> Optional[str]:
        """Retourne la valeur brute (chaîne)."""
        if self._redis is not None:
            try:
                return self._redis.get(key)
            except Exception as e:  # noqa: BLE001
                logger.debug("[Cache] Redis get_raw failed: %s", e)
        return self._memory.get(key)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl = ttl if ttl is not None else self.ttl_default
        payload = json.dumps(value, ensure_ascii=False)
        if self._redis is not None:
            try:
                self._redis.set(key, payload, ex=ttl)
                return
            except Exception as e:  # noqa: BLE001
                logger.debug("[Cache] Redis set failed: %s", e)
        self._memory.set(key, payload, ttl=ttl)

    def delete(self, key: str) -> bool:
        if self._redis is not None:
            try:
                return bool(self._redis.delete(key))
            except Exception as e:  # noqa: BLE001
                logger.debug("[Cache] Redis delete failed: %s", e)
        return self._memory.delete(key)

    def flush(self) -> None:
        if self._redis is not None:
            try:
                self._redis.flushdb()
            except Exception as e:  # noqa: BLE001
                logger.debug("[Cache] Redis flush failed: %s", e)
        self._memory.flush()

    def keys(self, prefix: str = "") -> list[str]:
        if self._redis is not None:
            try:
                return [k for k in self._redis.scan_iter(match=f"{prefix}*", count=200)]
            except Exception as e:  # noqa: BLE001
                logger.debug("[Cache] Redis keys failed: %s", e)
        return self._memory.keys(prefix)

    def get_or_set(self, key: str, producer, ttl: Optional[int] = None) -> Any:
        """Retourne la valeur en cache, ou calcule et stocke."""
        cached = self.get(key)
        if cached is not None:
            return cached
        value = producer() if callable(producer) else producer
        self.set(key, value, ttl=ttl)
        return value

    def __len__(self) -> int:
        if self._redis is not None:
            try:
                return int(self._redis.dbsize())
            except Exception:  # noqa: BLE001
                return 0
        return len(self._memory)

    # ── préchargement ──────────────────────────────────────────────

    def preload(self, items: dict[str, Any], ttl: Optional[int] = None) -> int:
        """Précharge un ensemble clé → valeur dans le cache.

        Args:
            items: Dictionnaire clé → valeur.
            ttl: Durée de vie (défaut : TTL du cache).

        Returns:
            Nombre d'éléments préchargés.
        """
        count = 0
        for key, value in items.items():
            if self.get(key) is None:
                self.set(key, value, ttl=ttl)
                count += 1
        logger.info("[Cache] Préchargé %d/%d entrées", count, len(items))
        return count

    def preload_voices(self, voices: dict[str, Any], ttl: int = 86400) -> int:
        """Précharge le catalogue de voix TTS (TTL 24h)."""
        items = {f"voice:{k}": v for k, v in voices.items()}
        return self.preload(items, ttl=ttl)

    def preload_prompt_templates(self, templates: dict[str, Any], ttl: int = 86400) -> int:
        """Précharge les templates de prompts optimisés (TTL 24h)."""
        items = {f"prompt_template:{k}": v for k, v in templates.items()}
        return self.preload(items, ttl=ttl)

    def get_stats(self) -> dict:
        """Statistiques du cache pour le monitoring."""
        return {
            "backend": "redis" if self.is_redis else "memory",
            "entries": len(self),
            "ttl_default": self.ttl_default,
        }


# ── singleton partagé ─────────────────────────────────────────────

_cache: Optional[RedisCache] = None
_cache_lock = Lock()


def get_cache() -> RedisCache:
    """Retourne le cache global (singleton)."""
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = RedisCache()
        return _cache


def reset_cache() -> None:
    """Réinitialise le cache global (utile en tests)."""
    global _cache
    with _cache_lock:
        _cache = None
