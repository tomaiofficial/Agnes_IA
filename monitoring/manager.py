"""
Agnes IA - Gestionnaire de Monitoring
Logs, métriques, alertes avec ELK et Prometheus
"""

import time
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp
from prometheus_client import start_http_server, Counter, Gauge, Histogram

from config import config

logger = logging.getLogger(__name__)


@dataclass
class JobMetrics:
    """Métriques pour un job"""
    job_id: str
    user_id: str
    steps: Dict[str, float] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    success: Optional[bool] = None
    error: Optional[str] = None
    current_step: Optional[str] = None
    progress_percent: float = 0.0


class Monitor:
    """
    Gestionnaire de monitoring pour Agnes IA.
    
    Fonctionnalités:
    - Logging des jobs
    - Métriques Prometheus
    - Alertes (GPU > 90%, temps > 10min, erreurs > 5)
    - Intégration Elasticsearch
    """
    
    def __init__(self):
        self.active_jobs: Dict[str, JobMetrics] = {}
        self.completed_jobs: List[JobMetrics] = []
        self.es_client = self._init_elasticsearch()
        
        # Métriques Prometheus
        self.job_counter = Counter(
            'agnes_jobs_total',
            'Total number of jobs',
            ['status', 'priority']
        )
        self.job_duration = Histogram(
            'agnes_job_duration_seconds',
            'Job duration in seconds',
            ['step', 'priority']
        )
        self.gpu_usage = Gauge(
            'agnes_gpu_usage_percent',
            'GPU usage percentage'
        )
        self.memory_usage = Gauge(
            'agnes_memory_usage_bytes',
            'Memory usage in bytes'
        )
        self.queue_size = Gauge(
            'agnes_queue_size',
            'Current queue size',
            ['priority']
        )
        self.active_jobs_gauge = Gauge(
            'agnes_active_jobs',
            'Number of active jobs'
        )
        
        # Démarrer le serveur Prometheus
        if config.PROMETHEUS_ENABLED:
            try:
                start_http_server(config.PROMETHEUS_PORT)
                logger.info(f"Prometheus server started on port {config.PROMETHEUS_PORT}")
            except Exception as e:
                logger.error(f"Failed to start Prometheus server: {str(e)}")
    
    def _init_elasticsearch(self) -> Optional[aiohttp.ClientSession]:
        """Initialiser la connexion Elasticsearch"""
        if not config.ELASTICSEARCH_ENABLED:
            return None
        
        try:
            return aiohttp.ClientSession(config.ELASTICSEARCH_URL)
        except Exception as e:
            logger.error(f"Failed to connect to Elasticsearch: {str(e)}")
            return None
    
    def start_job(self, job_id: str, user_id: str, priority: str = "free") -> None:
        """Démarrer le suivi d'un job"""
        self.active_jobs[job_id] = JobMetrics(
            job_id=job_id,
            user_id=user_id,
            start_time=time.time()
        )
        self.active_jobs_gauge.set(len(self.active_jobs))
        logger.info(f"Job started: {job_id} (user: {user_id}, priority: {priority})")
    
    def log(self, job_id: str, step: str, status: str, duration: Optional[float] = None, **kwargs) -> None:
        """Logger une étape du pipeline"""
        if job_id not in self.active_jobs:
            self.active_jobs[job_id] = JobMetrics(job_id=job_id, user_id="unknown")
        
        job = self.active_jobs[job_id]
        job.steps[step] = duration or (time.time() - job.start_time)
        job.current_step = step
        
        # Mettre à jour Prometheus
        self.job_duration.labels(step=step, priority="free").observe(duration or 0)
        
        # Logger
        log_data = {
            "job_id": job_id,
            "step": step,
            "status": status,
            "duration": duration or 0,
            **kwargs
        }
        
        if status == "ERROR":
            logger.error(f"Job step failed: {job_id} - {step}", extra=log_data)
        else:
            logger.info(f"Job step: {job_id} - {step} - {status}", extra=log_data)
    
    def complete_job(self, job_id: str, success: bool, error: Optional[str] = None) -> None:
        """Terminer le suivi d'un job"""
        if job_id not in self.active_jobs:
            return
        
        job = self.active_jobs[job_id]
        job.end_time = time.time()
        job.success = success
        job.error = error
        job.progress_percent = 100.0 if success else job.progress_percent
        
        # Mettre à jour Prometheus
        priority = "free"  # À adapter selon le job
        self.job_counter.labels(status="success" if success else "failed", priority=priority).inc()
        
        # Envoyer à Elasticsearch
        if self.es_client:
            asyncio.create_task(self._send_to_elasticsearch(job))
        
        # Déplacer vers les jobs terminés
        self.completed_jobs.append(job)
        del self.active_jobs[job_id]
        self.active_jobs_gauge.set(len(self.active_jobs))
        
        # Nettoyer les jobs anciens
        if len(self.completed_jobs) > 1000:
            self.completed_jobs = self.completed_jobs[-500:]
        
        logger.info(f"Job completed: {job_id} - {'SUCCESS' if success else 'FAILED'} ({job.end_time - job.start_time:.2f}s)")
    
    async def _send_to_elasticsearch(self, job: JobMetrics) -> None:
        """Envoyer les métriques à Elasticsearch"""
        if not self.es_client:
            return
        
        try:
            doc = {
                "@timestamp": datetime.utcnow().isoformat(),
                "job_id": job.job_id,
                "user_id": job.user_id,
                "success": job.success,
                "error": job.error,
                "duration": job.end_time - job.start_time if job.end_time else None,
                "steps": job.steps,
                "progress_percent": job.progress_percent
            }
            
            async with self.es_client.post(
                f"{config.ELASTICSEARCH_URL}/agnes-jobs/_doc",
                json=doc
            ) as resp:
                if resp.status != 201:
                    logger.error(f"Failed to send to Elasticsearch: {await resp.text()}")
        except Exception as e:
            logger.error(f"Error sending to Elasticsearch: {str(e)}")
    
    def update_gpu_metrics(self, usage: float, memory: int) -> None:
        """Mettre à jour les métriques GPU"""
        self.gpu_usage.set(usage)
        self.memory_usage.set(memory)
    
    def update_queue_size(self, priority: str, size: int) -> None:
        """Mettre à jour la taille de la file"""
        self.queue_size.labels(priority=priority).set(size)
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Récupérer le statut d'un job"""
        if job_id in self.active_jobs:
            job = self.active_jobs[job_id]
            return {
                "job_id": job.job_id,
                "user_id": job.user_id,
                "status": "processing",
                "progress_percent": job.progress_percent,
                "current_step": job.current_step,
                "steps": job.steps,
                "start_time": job.start_time
            }
        
        # Chercher dans les jobs terminés
        for job in reversed(self.completed_jobs):
            if job.job_id == job_id:
                return {
                    "job_id": job.job_id,
                    "user_id": job.user_id,
                    "status": "completed" if job.success else "failed",
                    "progress_percent": 100 if job.success else job.progress_percent,
                    "duration": job.end_time - job.start_time if job.end_time else None,
                    "error": job.error,
                    "completed_at": job.end_time
                }
        
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Récupérer les statistiques globales"""
        return {
            "active_jobs": len(self.active_jobs),
            "completed_jobs": len(self.completed_jobs),
            "gpu_usage": self.gpu_usage._value.get() or 0,
            "memory_usage": self.memory_usage._value.get() or 0
        }
    
    def check_alerts(self) -> List[Dict[str, Any]]:
        """Vérifier les alertes"""
        alerts = []
        
        # Alerte GPU > 90%
        gpu_usage = self.gpu_usage._value.get() or 0
        if gpu_usage > 90:
            alerts.append({
                "type": "gpu_usage",
                "level": "critical",
                "message": f"GPU usage too high: {gpu_usage:.1f}%",
                "value": gpu_usage
            })
        
        # Alerte jobs en échec
        failed_jobs = sum(1 for job in self.completed_jobs if not job.success)
        if failed_jobs > 5:
            alerts.append({
                "type": "failed_jobs",
                "level": "warning",
                "message": f"Too many failed jobs: {failed_jobs}",
                "value": failed_jobs
            })
        
        # Alerte temps de traitement
        for job in self.active_jobs.values():
            duration = time.time() - job.start_time
            if duration > 600:  # 10 minutes
                alerts.append({
                    "type": "long_running_job",
                    "level": "warning",
                    "message": f"Job {job.job_id} running too long",
                    "job_id": job.job_id,
                    "duration": duration
                })
        
        return alerts


# Importer asyncio pour les tâches asynchrones
import asyncio
