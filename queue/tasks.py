"""
Celery Tasks pour Agnes IA
Tâches asynchrones pour le traitement des jobs
"""

from celery import Celery
from pipeline.ia_pipeline import IAPipeline
from queue.manager import QueueManager, Priority, QueueJob
from config import config
import asyncio
import time
import logging

logger = logging.getLogger(__name__)

# Initialiser Celery
celery_app = Celery(
    'agnes_ia',
    broker=config.REDIS_URL,
    backend=config.REDIS_URL
)

# Configuration Celery
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_acks_late=True,
    task_max_retries=3,
    task_default_retry_delay=60,
    task_retry_backoff=True,
    task_retry_backoff_max=3600
)

# Initialiser les composants
pipeline = IAPipeline()
queue_manager = QueueManager()


@celery_app.task(bind=True, max_retries=3)
def process_ia_job(self, job_data: dict):
    """
    Tâche Celery pour traiter un job IA.
    
    Args:
        job_data: Données du job
    """
    job = QueueJob(**job_data)
    
    try:
        logger.info(f"Processing job {job.id} (priority: {job.priority.name})")
        
        # Exécuter le pipeline
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(pipeline.process(job_data))
        
        if result.success:
            # Marquer comme terminé
            loop.run_until_complete(queue_manager.complete_job(job.id, result.data))
            logger.info(f"Job {job.id} completed successfully")
            return result.data
        else:
            raise Exception(result.error or "Unknown error")
            
    except Exception as e:
        logger.error(f"Error processing job {job.id}: {str(e)}")
        # Marquer comme échoué
        loop = asyncio.get_event_loop()
        loop.run_until_complete(queue_manager.fail_job(job.id, str(e)))
        self.retry(exc=e, countdown=min(2 ** job.retries, 3600))


@celery_app.task
async def check_pending_jobs():
    """
    Vérifier et traiter les jobs en attente.
    """
    while True:
        job = await queue_manager.get_next_job()
        if job:
            process_ia_job.delay(job.__dict__)
        else:
            await asyncio.sleep(1)
