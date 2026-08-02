"""
Agnes IA - API Principal (FastAPI)
Gère les requêtes HTTP et WebSocket pour le pipeline
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Dict, Any, Optional
import asyncio
import json
import logging
from datetime import datetime

from pipeline.ia_pipeline import IAPipeline
from queue.manager import QueueManager, Priority, QueueJob
from monitoring.manager import Monitor
from security.manager import SecurityManager
from config import config

logger = logging.getLogger(__name__)

# Initialiser FastAPI
app = FastAPI(
    title="Agnes IA API",
    description="API pour le pipeline IA de génération et amélioration de vidéos",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialiser les composants
pipeline = IAPipeline()
queue_manager = QueueManager()
monitor = Monitor()
security = SecurityManager()

# Monter les fichiers statiques
templates = Jinja2Templates(directory="frontend/templates")
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

# Stockage des connexions WebSocket
websocket_connections: Dict[str, list] = {}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint pour les notifications en temps réel"""
    await websocket.accept()
    
    user_id = "anonymous"
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "subscribe":
                user_id = message.get("user_id", "anonymous")
                if user_id not in websocket_connections:
                    websocket_connections[user_id] = []
                websocket_connections[user_id].append(websocket)
                
                # Envoyer l'état actuel des jobs de l'utilisateur
                user_jobs = []
                for job_id, job_metrics in monitor.active_jobs.items():
                    if job_metrics.user_id == user_id:
                        user_jobs.append({
                            "job_id": job_id,
                            "user_id": user_id,
                            "status": "processing",
                            "progress_percent": job_metrics.progress_percent if hasattr(job_metrics, 'progress_percent') else 0,
                            "current_step": job_metrics.current_step if hasattr(job_metrics, 'current_step') else None,
                            "steps": job_metrics.steps if hasattr(job_metrics, 'steps') else {},
                            "start_time": job_metrics.start_time
                        })
                
                for job in user_jobs:
                    await websocket.send_text(json.dumps({
                        "type": "job_update",
                        "job": job
                    }))
                    
            elif message.get("type") == "unsubscribe":
                if user_id in websocket_connections:
                    websocket_connections[user_id].remove(websocket)
                    if not websocket_connections[user_id]:
                        del websocket_connections[user_id]
                break
    
    except WebSocketDisconnect:
        if user_id in websocket_connections:
            websocket_connections[user_id].remove(websocket)
            if not websocket_connections[user_id]:
                del websocket_connections[user_id]
        logger.info(f"WebSocket disconnected: {user_id}")


@app.post("/api/jobs")
async def create_job(job_data: Dict[str, Any]):
    """Créer un nouveau job de traitement"""
    try:
        # Valider les données
        if not job_data.get("prompt"):
            raise HTTPException(status_code=400, detail="Le prompt est requis")
        
        # Déterminer la priorité
        priority_str = job_data.get("priority", "free").lower()
        priority_map = {
            "premium": Priority.PREMIUM,
            "admin": Priority.ADMIN,
            "free": Priority.FREE
        }
        priority = priority_map.get(priority_str, Priority.FREE)
        
        # Créer le job
        job = QueueJob(
            id=f"job_{int(datetime.now().timestamp() * 1000)}_{abs(hash(job_data.get('user_id', 'anonymous'))) % 10000}",
            user_id=job_data.get("user_id", "anonymous"),
            priority=priority,
            data=job_data
        )
        
        # Ajouter à la file
        job_id = await queue_manager.add_job(job)
        
        # Démarrer le monitoring
        monitor.start_job(job_id, job.user_id, priority_str)
        
        logger.info(f"Nouveau job créé: {job_id} (priorité: {priority_str})")
        
        return {
            "job_id": job_id,
            "status": "queued",
            "priority": priority_str,
            "message": "Job ajouté à la file d'attente"
        }
        
    except Exception as e:
        logger.error(f"Erreur création job: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Récupérer le statut d'un job"""
    try:
        # Vérifier d'abord dans le monitoring
        status = monitor.get_job_status(job_id)
        if status:
            return status
        
        # Sinon, vérifier dans la file
        job_status = await queue_manager.get_job_status(job_id)
        if job_status.get("status") == "not_found":
            raise HTTPException(status_code=404, detail="Job non trouvé")
        
        return {
            "job_id": job_id,
            "status": job_status.get("status", "unknown"),
            "progress": job_status.get("progress_percent", 0),
            "steps": job_status.get("steps", {}),
            "error": job_status.get("error")
        }
        
    except Exception as e:
        logger.error(f"Erreur statut job {job_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs")
async def list_jobs(user_id: Optional[str] = None, limit: int = 10):
    """Lister les jobs"""
    try:
        jobs = []
        
        # Jobs actifs
        for job_id, job_metrics in monitor.active_jobs.items():
            if user_id is None or job_metrics.user_id == user_id:
                jobs.append({
                    "job_id": job_id,
                    "user_id": job_metrics.user_id,
                    "status": "processing",
                    "progress_percent": getattr(job_metrics, 'progress_percent', 0),
                    "current_step": getattr(job_metrics, 'current_step', None),
                    "steps": getattr(job_metrics, 'steps', {}),
                    "start_time": job_metrics.start_time
                })
        
        # Jobs terminés (à implémenter selon votre stockage)
        # Pour l'instant, on retourne uniquement les jobs actifs
        
        return {"jobs": jobs[:limit]}
        
    except Exception as e:
        logger.error(f"Erreur liste jobs: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_stats():
    """Récupérer les statistiques globales"""
    try:
        stats = monitor.get_stats()
        queue_sizes = await queue_manager.get_all_queues_size()
        stats["queues"] = queue_sizes
        return stats
    except Exception as e:
        logger.error(f"Erreur stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/alerts")
async def get_alerts():
    """Récupérer les alertes"""
    try:
        alerts = monitor.check_alerts()
        return {"alerts": alerts}
    except Exception as e:
        logger.error(f"Erreur alertes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def read_root(request: Any):
    """Page d'accueil"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check():
    """Vérification de santé"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    }


# Démarrer le worker de traitement en arrière-plan
async def process_jobs_background():
    """Traiter les jobs en arrière-plan"""
    while True:
        try:
            # Récupérer le prochain job
            job = await queue_manager.get_next_job()
            
            if job:
                try:
                    # Traiter le job via le pipeline
                    result = await pipeline.process(job.data)
                    
                    if result.success:
                        await queue_manager.complete_job(job.id, result.data)
                        monitor.complete_job(job.id, True)
                        
                        # Notifier les clients WebSocket
                        for user_id, connections in websocket_connections.items():
                            if job.user_id == user_id:
                                for ws in connections:
                                    await ws.send_text(json.dumps({
                                        "type": "job_completed",
                                        "job": {
                                            "job_id": job.id,
                                            "user_id": job.user_id,
                                            "status": "completed",
                                            "success": True,
                                            "progress_percent": 100,
                                            "result": result.data
                                        }
                                    }))
                    else:
                        await queue_manager.fail_job(job.id, result.error or "Unknown error")
                        monitor.complete_job(job.id, False, result.error)
                        
                        for user_id, connections in websocket_connections.items():
                            if job.user_id == user_id:
                                for ws in connections:
                                    await ws.send_text(json.dumps({
                                        "type": "job_completed",
                                        "job": {
                                            "job_id": job.id,
                                            "user_id": job.user_id,
                                            "status": "failed",
                                            "success": False,
                                            "progress_percent": result.progress_percent,
                                            "error": result.error
                                        }
                                    }))
                except Exception as e:
                    await queue_manager.fail_job(job.id, str(e))
                    monitor.complete_job(job.id, False, str(e))
                    logger.error(f"Erreur traitement job {job.id}: {str(e)}")
        except Exception as e:
            logger.error(f"Erreur dans la boucle de traitement: {str(e)}")
        
        await asyncio.sleep(1)


# Démarrer le worker au démarrage
@app.on_event("startup")
async def startup_event():
    logger.info("Démarrage de l'API Agnes IA...")
    asyncio.create_task(process_jobs_background())
    logger.info("Worker de traitement démarré")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Arrêt de l'API Agnes IA...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
