"""
Agnes IA - Cache Redis
Cache pour les résultats intermédiaires et les modèles
"""

import json
import time
import hashlib
from typing import Any, Optional, Dict
import logging

import redis.asyncio as redis

from config import config

logger = logging.getLogger(__name__)


class RedisCache:
    """
    Cache Redis pour le pipeline Agnes IA.
    
    Fonctionnalités:
    - Cache des prompts optimisés
    - Cache des résultats intermédiaires
    - Cache des modèles chargés
    - Préchargement des modèles fréquents
    """
    
    def __init__(self):
        self.redis = redis.from_url(config.REDIS_URL, decode_responses=True)
        logger.info("RedisCache initialized")
    
    async def get(self, key: str) -> Optional[Any]:
        """Récupérer une valeur du cache"""
        try:
            value = await self.redis.get(key)
            if value is None:
                return None
            return json.loads(value)
        except Exception as e:
            logger.error(f"Cache get failed: {str(e)}")
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Stocker une valeur dans le cache"""
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            
            if ttl:
                await self.redis.setex(key, ttl, value)
            else:
                await self.redis.set(key, value)
            
            logger.debug(f"Cached: {key}")
        except Exception as e:
            logger.error(f"Cache set failed: {str(e)}")
    
    async def delete(self, key: str) -> None:
        """Supprimer une clé du cache"""
        try:
            await self.redis.delete(key)
            logger.debug(f"Cache deleted: {key}")
        except Exception as e:
            logger.error(f"Cache delete failed: {str(e)}")
    
    async def get_prompt(self, prompt: str) -> Optional[str]:
        """Récupérer un prompt optimisé depuis le cache"""
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        key = f"cache:prompt:{prompt_hash}"
        return await self.get(key)
    
    async def set_prompt(self, prompt: str, optimized: str) -> None:
        """Stocker un prompt optimisé dans le cache"""
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        key = f"cache:prompt:{prompt_hash}"
        await self.set(key, optimized, ttl=3600)  # 1h
        logger.info(f"Cached optimized prompt: {prompt[:50]}...")
    
    async def get_intermediate(self, job_id: str, step: str) -> Optional[Dict[str, Any]]:
        """Récupérer un résultat intermédiaire"""
        key = f"cache:intermediate:{job_id}:{step}"
        return await self.get(key)
    
    async def set_intermediate(self, job_id: str, step: str, data: Dict[str, Any]) -> None:
        """Stocker un résultat intermédiaire"""
        key = f"cache:intermediate:{job_id}:{step}"
        await self.set(key, data, ttl=86400)  # 24h
        logger.debug(f"Cached intermediate result: {job_id}:{step}")
    
    async def get_model(self, model_name: str) -> Optional[str]:
        """Récupérer le chemin d'un modèle chargé"""
        key = f"cache:model:{model_name}"
        return await self.get(key)
    
    async def set_model(self, model_name: str, model_path: str) -> None:
        """Stocker le chemin d'un modèle"""
        key = f"cache:model:{model_name}"
        await self.set(key, model_path, ttl=86400)  # 24h
        logger.info(f"Cached model: {model_name}")
    
    async def clear_user_cache(self, user_id: str) -> None:
        """Effacer le cache d'un utilisateur"""
        try:
            pattern = f"cache:*:{user_id}*"
            keys = []
            cursor = 0
            
            while True:
                cursor, batch = await self.redis.scan(cursor, match=pattern, count=100)
                keys.extend(batch)
                if cursor == 0:
                    break
            
            if keys:
                await self.redis.delete(*keys)
                logger.info(f"Cleared cache for user: {user_id} ({len(keys)} keys)")
        except Exception as e:
            logger.error(f"Clear user cache failed: {str(e)}")
    
    async def clear_all_cache(self) -> None:
        """Effacer tout le cache"""
        try:
            await self.redis.flushdb()
            logger.info("Cleared all cache")
        except Exception as e:
            logger.error(f"Clear all cache failed: {str(e)}")
    
    async def preload_models(self, model_names: list) -> Dict[str, bool]:
        """
        Précharger les modèles fréquents dans le cache.
        
        Args:
            model_names: Liste des noms de modèles à précharger
            
        Returns:
            Dict: Statut de chargement pour chaque modèle
        """
        results = {}
        
        for model_name in model_names:
            # Vérifier si déjà en cache
            model_path = await self.get_model(model_name)
            if model_path:
                results[model_name] = True
                logger.info(f"Model {model_name} already in cache")
                continue
            
            # Charger le modèle (implémentation spécifique)
            try:
                # Exemple: model_path = await load_model_from_disk(model_name)
                model_path = f"/models/{model_name}"
                await self.set_model(model_name, model_path)
                results[model_name] = True
                logger.info(f"Preloaded model: {model_name}")
            except Exception as e:
                logger.error(f"Failed to preload model {model_name}: {str(e)}")
                results[model_name] = False
        
        return results
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Récupérer les statistiques du cache"""
        try:
            info = await self.redis.info()
            return {
                "keys": info.get("db0", {}).get("keys", 0),
                "memory_used": info.get("memory", {}).get("used_memory", 0),
                "hit_rate": info.get("stats", {}).get("keyspace_hits", 0) / 
                           max(1, info.get("stats", {}).get("keyspace_hits", 0) + 
                               info.get("stats", {}).get("keyspace_misses", 0))
            }
        except Exception as e:
            logger.error(f"Failed to get cache stats: {str(e)}")
            return {"keys": 0, "memory_used": 0, "hit_rate": 0}
