"""
Queue Manager pour Agnes IA
Gestion des files d'attente avec priorités: Premium > Admin > Gratuit
"""

from enum import Enum, auto
import time
import json
import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from config import config

try:
    import redis.asyncio as redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


class Priority(Enum):
    """Niveaux de priorité pour les files d'attente"""
    PREMIUM = 1
    ADMIN = 2
    FREE = 3


@dataclass
class QueueJob:
    """Représente un job dans la file d'attente"""
    id: str
    user_id: str
    priority: Priority
    data: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    retries: int = 0
    max_retries: int = 3
    status: str = "pending"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class QueueManager:
    """
    Gestionnaire des files d'attente avec priorités.
    Utilise Redis pour la persistance et Celery pour le traitement.
    """
    
    def __init__(self):
        if not HAS_REDIS:
            raise ImportError("Redis is required for QueueManager. Install with: pip install redis")
        
        self.redis = redis.from_url(config.REDIS_URL, decode_responses=True)
        
        # Noms des files Redis
        self.queues = {
            Priority.PREMIUM: "agnes:queue:premium",
            Priority.ADMIN: "agnes:queue:admin",
            Priority.FREE: "agnes:queue:free"
        }
        
        # Files de traitement (pour suivre les jobs en cours)
        self.processing = {
            Priority.PREMIUM: "agnes:processing:premium",
            Priority.ADMIN: "agnes:processing:admin",
            Priority.FREE: "agnes:processing:free"
        }
        
        # Limites de jobs simultanés par priorité
        self.max_processing = {
            Priority.PREMIUM: 10,
            Priority.ADMIN: 5,
            Priority.FREE: 2
        }
    
    async def add_job(self, job: QueueJob) -> str:
        """
        Ajouter un job à la file d'attente appropriée.
        
        Args:
            job: QueueJob à ajouter
            
        Returns:
            str: L'ID du job
        """
        queue_name = self.queues[job.priority]
        
        # Stocker le job dans Redis (file)
        job_data = job.__dict__.copy()
        job_data["_queue"] = queue_name
        
        await self.redis.lpush(queue_name, json.dumps(job_data))
        
        # Stocker les métadonnées complètes du job
        await self.redis.hset(f"agnes:job:{job.id}", mapping=job_data)
        await self.redis.expire(f"agnes:job:{job.id}", 86400)  # 24h TTL
        
        return job.id
    
    async def get_next_job(self) -> Optional[QueueJob]:
        """
        Récupérer le prochain job à traiter selon les priorités.
        
        Returns:
            Optional[QueueJob]: Le prochain job, ou None si aucune file n'a de jobs
        """
        # Parcourir les priorités de la plus haute à la plus basse
        for priority in [Priority.PREMIUM, Priority.ADMIN, Priority.FREE]:
            queue_name = self.queues[priority]
            processing_key = self.processing[priority]
            
            # Vérifier si on peut traiter plus de jobs de cette priorité
            processing_count = await self.redis.llen(processing_key)
            max_p = self.max_processing[priority]
            
            if processing_count >= max_p:
                continue
            
            # Récupérer un job de la file
            job_data = await self.redis.rpoplpush(queue_name, processing_key)
            
            if job_data:
                job_dict = json.loads(job_data)
                
                # Mettre à jour le statut
                job_dict["status"] = "processing"
                job_dict["started_at"] = time.time()
                
                # Sauvegarder dans Redis
                await self.redis.hset(f"agnes:job:{job_dict['id']}", mapping=job_dict)
                
                # Créer l'objet QueueJob
                job = QueueJob(**job_dict)
                return job
        
        return None
    
    async def complete_job(self, job_id: str, result: Dict[str, Any]) -> None:
        """
        Marquer un job comme terminé avec succès.
        
        Args:
            job_id: ID du job
            result: Résultat du traitement
        """
        job_data = await self.redis.hgetall(f"agnes:job:{job_id}")
        if not job_data:
            return
        
        priority = Priority(int(job_data.get("priority", 3)))
        processing_key = self.processing[priority]
        
        # Retirer de la file de traitement
        await self.redis.lrem(processing_key, 0, json.dumps(job_data))
        
        # Mettre à jour le statut
        job_data["status"] = "completed"
        job_data["result"] = json.dumps(result)
        job_data["completed_at"] = str(time.time())
        
        await self.redis.hset(f"agnes:job:{job_id}", mapping=job_data)
        await self.redis.expire(f"agnes:job:{job_id}", 259200)  # 3 jours TTL
    
    async def fail_job(self, job_id: str, error: str) -> None:
        """
        Marquer un job comme échoué et le réessayer si possible.
        
        Args:
            job_id: ID du job
            error: Message d'erreur
        """
        job_data = await self.redis.hgetall(f"agnes:job:{job_id}")
        if not job_data:
            return
        
        job = QueueJob(**{k: int(v) if k == "priority" else v for k, v in job_data.items()})
        job.retries += 1
        
        if job.retries <= job.max_retries:
            # Réessayer
            queue_name = self.queues[job.priority]
            processing_key = self.processing[job.priority]
            
            # Retirer de la file de traitement
            await self.redis.lrem(processing_key, 0, json.dumps(job_data))
            
            # Réajouter à la queue
            job_dict = job.__dict__.copy()
            job_dict["error"] = error
            job_dict["retries"] = job.retries
            
            await self.redis.lpush(queue_name, json.dumps(job_dict))
            
            # Définir un délai de backoff exponentiel
            delay = min(2 ** job.retries, 3600)  # Max 1 heure
            await self.redis.expire(f"agnes:job:{job_id}:retry", delay)
            
        else:
            # Échec définitif
            priority = job.priority
            processing_key = self.processing[priority]
            
            await self.redis.lrem(processing_key, 0, json.dumps(job_data))
            
            job_data["status"] = "failed"
            job_data["error"] = error
            job_data["completed_at"] = str(time.time())
            
            await self.redis.hset(f"agnes:job:{job_id}", mapping=job_data)
            await self.redis.expire(f"agnes:job:{job_id}", 259200)  # 3 jours TTL
    
    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """
        Récupérer le statut d'un job.
        
        Args:
            job_id: ID du job
            
        Returns:
            Dict[str, Any]: Statut du job
        """
        job_data = await self.redis.hgetall(f"agnes:job:{job_id}")
        if not job_data:
            return {"status": "not_found"}
        
        # Convertir les types
        for key, value in job_data.items():
            if key in ["priority", "retries", "max_retries"]:
                job_data[key] = int(value)
            elif key in ["created_at", "started_at", "completed_at"]:
                job_data[key] = float(value) if value else None
        
        return job_data
    
    async def get_queue_size(self, priority: Optional[Priority] = None) -> Dict[str, int]:
        """
        Récupérer la taille des files d'attente.
        
        Args:
            priority: Priorité spécifique (optionnel)
            
        Returns:
            Dict[str, int]: Taille de chaque file
        """
        sizes = {}
        
        if priority:
            queue_name = self.queues[priority]
            sizes[priority.name] = await self.redis.llen(queue_name)
        else:
            for p, queue_name in self.queues.items():
                sizes[p.name] = await self.redis.llen(queue_name)
        
        return sizes
    
    async def cleanup_expired_jobs(self) -> int:
        """
        Nettoyer les jobs expirés (plus de 3 jours).
        
        Returns:
            int: Nombre de jobs nettoyés
        """
        # Récupérer tous les jobs
        keys = []
        cursor = 0
        while True:
            cursor, batch = await self.redis.scan(cursor, match="agnes:job:*", count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        
        cleaned = 0
        for key in keys:
            ttl = await self.redis.ttl(key)
            if ttl == -2:  # Pas de TTL
                await self.redis.expire(key, 259200)  # 3 jours
            elif ttl < 0:  # Déjà expiré
                await self.redis.delete(key)
                cleaned += 1
        
        return cleaned
    
    def create_job(self, user_id: str, data: Dict[str, Any], priority: str = "free") -> QueueJob:
        """
        Créer un nouvel objet QueueJob.
        
        Args:
            user_id: ID de l'utilisateur
            data: Données du job
            priority: Niveau de priorité (premium/admin/free)
            
        Returns:
            QueueJob: Le job créé
        """
        priority_map = {
            "premium": Priority.PREMIUM,
            "admin": Priority.ADMIN,
            "free": Priority.FREE
        }
        job_priority = priority_map.get(priority.lower(), Priority.FREE)
        
        return QueueJob(
            id=f"job_{int(time.time() * 1000)}_{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=8))}",
            user_id=user_id,
            priority=job_priority,
            data=data
        )


# Importer random pour la génération d'IDs
import random
