"""
Agnes IA - Rate Limiter
Backoff exponentiel + Retry-After + retry intelligent
"""

import time
import random
from typing import Optional, Tuple, Callable
from functools import wraps
import asyncio

import redis.asyncio as redis
from fastapi import HTTPException, Request

from config import config


class RateLimiter:
    """
    Gestionnaire de rate limiting avec backoff exponentiel.
    
    Fonctionnalités:
    - Limite de requêtes par période
    - Backoff exponentiel avec jitter
    - Header Retry-After
    - Gestion des priorités
    """
    
    def __init__(self):
        self.redis = redis.from_url(config.REDIS_URL, decode_responses=True)
        self.max_requests = config.RATE_LIMIT
        self.period = config.RATE_LIMIT_PERIOD
        self.base_delay = config.BASE_DELAY
        self.max_delay = config.MAX_DELAY
    
    async def is_allowed(self, key: str) -> Tuple[bool, Optional[float]]:
        """
        Vérifier si une requête est autorisée.
        
        Args:
            key: Clé unique pour l'utilisateur/endpoint
            
        Returns:
            Tuple: (is_allowed, retry_after)
        """
        current = await self.redis.get(f"ratelimit:{key}")
        now = time.time()
        
        if current is None:
            # Première requête
            pipe = self.redis.pipeline()
            pipe.set(f"ratelimit:{key}", 1, ex=self.period)
            pipe.set(f"ratelimit:{key}:first", now, ex=self.period)
            await pipe.execute()
            return True, None
        
        count = int(current)
        first_request = float(await self.redis.get(f"ratelimit:{key}:first") or now)
        
        if count >= self.max_requests:
            # Limite dépassée - calculer le délai
            elapsed = now - first_request
            if elapsed < self.period:
                # Backoff exponentiel
                retries = count - self.max_requests
                delay = min(self.base_delay * (2 ** retries), self.max_delay)
                
                # Ajouter du jitter (±10%)
                jitter = delay * 0.1 * (random.random() * 2 - 1)
                delay = max(0, delay + jitter)
                
                # Temps restant dans la période
                remaining = self.period - elapsed
                retry_after = max(delay, remaining)
                
                return False, retry_after
            else:
                # Période écoulée - réinitialiser
                pipe = self.redis.pipeline()
                pipe.incr(f"ratelimit:{key}")
                pipe.expire(f"ratelimit:{key}", self.period)
                pipe.set(f"ratelimit:{key}:first", now, ex=self.period)
                await pipe.execute()
                return True, None
        else:
            # Incrémenter le compteur
            pipe = self.redis.pipeline()
            pipe.incr(f"ratelimit:{key}")
            pipe.expire(f"ratelimit:{key}", self.period)
            await pipe.execute()
            return True, None
    
    def rate_limit(self, key_func: Callable, priority: Optional[str] = None):
        """
        Décorateur pour le rate limiting.
        
        Args:
            key_func: Fonction pour générer la clé de rate limiting
            priority: Priorité (optionnel)
            
        Returns:
            Function: Décorateur
        """
        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                request = None
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
                
                key = key_func(*args, **kwargs)
                
                # Ajuster la limite selon la priorité
                max_requests = self.max_requests
                if priority == "premium":
                    max_requests = self.max_requests * 2
                elif priority == "admin":
                    max_requests = self.max_requests * 1.5
                
                # Vérifier le rate limiting
                allowed, retry_after = await self._check_limit(key, max_requests)
                
                if not allowed:
                    raise HTTPException(
                        status_code=429,
                        detail=f"Too many requests. Retry after {retry_after:.1f}s",
                        headers={"Retry-After": str(int(retry_after))}
                    )
                
                return await func(*args, **kwargs)
            
            return wrapper
        return decorator
    
    async def _check_limit(self, key: str, max_requests: int) -> Tuple[bool, Optional[float]]:
        """Vérifier la limite avec une limite personnalisée"""
        current = await self.redis.get(f"ratelimit:{key}")
        now = time.time()
        
        if current is None:
            pipe = self.redis.pipeline()
            pipe.set(f"ratelimit:{key}", 1, ex=self.period)
            pipe.set(f"ratelimit:{key}:first", now, ex=self.period)
            await pipe.execute()
            return True, None
        
        count = int(current)
        first_request = float(await self.redis.get(f"ratelimit:{key}:first") or now)
        
        if count >= max_requests:
            elapsed = now - first_request
            if elapsed < self.period:
                retries = count - max_requests
                delay = min(self.base_delay * (2 ** retries), self.max_delay)
                jitter = delay * 0.1 * (random.random() * 2 - 1)
                delay = max(0, delay + jitter)
                remaining = self.period - elapsed
                retry_after = max(delay, remaining)
                return False, retry_after
            else:
                pipe = self.redis.pipeline()
                pipe.incr(f"ratelimit:{key}")
                pipe.expire(f"ratelimit:{key}", self.period)
                pipe.set(f"ratelimit:{key}:first", now, ex=self.period)
                await pipe.execute()
                return True, None
        else:
            pipe = self.redis.pipeline()
            pipe.incr(f"ratelimit:{key}")
            pipe.expire(f"ratelimit:{key}", self.period)
            await pipe.execute()
            return True, None
    
    async def reset_limit(self, key: str) -> None:
        """Réinitialiser la limite pour une clé"""
        await self.redis.delete(f"ratelimit:{key}")
        await self.redis.delete(f"ratelimit:{key}:first")
