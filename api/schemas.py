"""
Agnes IA - Schémas Pydantic
Définition des modèles de données pour l'API
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class PriorityEnum(str, Enum):
    premium = "premium"
    admin = "admin"
    free = "free"


class JobCreateRequest(BaseModel):
    """Requête pour créer un nouveau job"""
    prompt: str = Field(..., description="Le prompt à traiter", min_length=1, max_length=1000)
    user_id: Optional[str] = Field(default="anonymous", description="ID de l'utilisateur")
    priority: Optional[PriorityEnum] = Field(default="free", description="Priorité du job")
    resolution: Optional[str] = Field(default="1080p", description="Résolution cible")
    duration: Optional[int] = Field(default=10, description="Durée en secondes", ge=1, le=300)
    style: Optional[str] = Field(default="realistic", description="Style de génération")
    audio_path: Optional[str] = Field(default=None, description="Chemin vers un fichier audio")
    target_size_mb: Optional[float] = Field(default=None, description="Taille cible en Mo")


class JobStatusResponse(BaseModel):
    """Réponse avec le statut d'un job"""
    job_id: str
    status: str
    progress_percent: float = Field(ge=0, le=100, description="Pourcentage de progression")
    current_step: Optional[str] = None
    steps: Optional[Dict[str, Any]] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class JobListResponse(BaseModel):
    """Réponse avec la liste des jobs"""
    jobs: List[JobStatusResponse]


class CreateJobResponse(BaseModel):
    """Réponse après création d'un job"""
    job_id: str
    status: str
    priority: str
    message: str


class StatsResponse(BaseModel):
    """Réponse avec les statistiques"""
    active_jobs: int
    completed_jobs: int
    gpu_usage: Optional[float] = None
    memory_usage: Optional[int] = None
    queues: Optional[Dict[str, int]] = None


class Alert(BaseModel):
    """Modèle pour une alerte"""
    type: str
    level: str
    message: str
    value: Optional[Any] = None


class AlertsResponse(BaseModel):
    """Réponse avec les alertes"""
    alerts: List[Alert]


class HealthResponse(BaseModel):
    """Réponse de vérification de santé"""
    status: str
    timestamp: str
    version: str
