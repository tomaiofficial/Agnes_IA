"""
Agnes IA - Optimiseur GPU
Gestion de la VRAM, batch processing, réutilisation des modèles
"""

import torch
from torch.cuda import empty_cache
from typing import Dict, Any, Optional, List
import logging

from config import config

logger = logging.getLogger(__name__)


class GPUOptimizer:
    """
    Optimiseur de l'utilisation du GPU.
    
    Fonctionnalités:
    - Gestion de la VRAM
    - Batch processing optimisé
    - Réutilisation des modèles
    - Nettoyage automatique
    """
    
    def __init__(self):
        self.has_gpu = torch.cuda.is_available()
        
        if self.has_gpu:
            self.device = torch.device("cuda")
            self.total_memory = torch.cuda.get_device_properties(0).total_memory
            self.max_memory = int(self.total_memory * config.MAX_VRAM)
            self.loaded_models: Dict[str, Any] = {}
            self.model_ref_counts: Dict[str, int] = {}
            self.batch_sizes = config.BATCH_SIZES
        else:
            self.device = torch.device("cpu")
            self.total_memory = 0
            self.max_memory = 0
            self.loaded_models = {}
            self.model_ref_counts = {}
            self.batch_sizes = config.BATCH_SIZES
        
        logger.info(f"GPUOptimizer initialized (GPU: {self.has_gpu})")
    
    def get_device(self) -> torch.device:
        """Récupérer le device (GPU ou CPU)"""
        return self.device
    
    def get_batch_size(self, model_type: str) -> int:
        """Récupérer la taille de batch optimale"""
        if not self.has_gpu:
            return 1
        return self.batch_sizes.get(model_type, 1)
    
    async def load_model(self, model_name: str, model_class: Any, *args, **kwargs) -> Any:
        """Charger un modèle en GPU avec gestion de la VRAM"""
        if not self.has_gpu:
            return model_class(*args, **kwargs).to(self.device)
        
        # Vérifier si déjà chargé
        if model_name in self.loaded_models:
            self.model_ref_counts[model_name] += 1
            logger.debug(f"Reusing model: {model_name}")
            return self.loaded_models[model_name]
        
        # Vérifier la mémoire disponible
        allocated = torch.cuda.memory_allocated(0)
        available = self.total_memory - allocated
        estimated = self._estimate_memory(model_name)
        
        if available < estimated:
            # Nettoyer la mémoire
            await self.cleanup_memory(estimated - available)
        
        # Charger le modèle
        model = model_class(*args, **kwargs).to(self.device)
        
        # Stocker dans le cache
        self.loaded_models[model_name] = model
        self.model_ref_counts[model_name] = 1
        
        logger.info(f"Loaded model: {model_name} in GPU")
        return model
    
    async def release_model(self, model_name: str) -> None:
        """Libérer un modèle du GPU"""
        if model_name not in self.loaded_models:
            return
        
        self.model_ref_counts[model_name] -= 1
        
        if self.model_ref_counts[model_name] <= 0:
            # Supprimer le modèle
            del self.loaded_models[model_name]
            del self.model_ref_counts[model_name]
            empty_cache()
            logger.info(f"Released model: {model_name} from GPU")
    
    async def cleanup_memory(self, required_memory: int) -> None:
        """Nettoyer la mémoire GPU pour libérer de l'espace"""
        if not self.has_gpu:
            return
        
        # Trier les modèles par nombre de références
        sorted_models = sorted(
            self.model_ref_counts.items(),
            key=lambda x: x[1]
        )
        
        # Libérer les modèles les moins utilisés
        for model_name, ref_count in sorted_models:
            if required_memory <= 0:
                break
            
            if ref_count <= 0:
                model = self.loaded_models.get(model_name)
                if model:
                    del model
                    del self.loaded_models[model_name]
                    del self.model_ref_counts[model_name]
                    empty_cache()
                    required_memory -= self._estimate_memory(model_name)
                    logger.info(f"Freed model {model_name} to make room")
    
    def _estimate_memory(self, model_name: str) -> int:
        """Estimer la mémoire nécessaire pour un modèle"""
        model_sizes = {
            "stable_diffusion": 2 * 1024**3,  # ~2GB
            "upscaler": 1 * 1024**3,        # ~1GB
            "face_enhancer": 512 * 1024**2,  # ~512MB
            "audio": 256 * 1024**2,         # ~256MB
            "esrgan": 1 * 1024**3,         # ~1GB
            "gfpgan": 512 * 1024**2        # ~512MB
        }
        return model_sizes.get(model_name, 512 * 1024**2)
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Récupérer les statistiques d'utilisation GPU"""
        if not self.has_gpu:
            return {
                "has_gpu": False,
                "device": "CPU",
                "total_memory": 0,
                "allocated": 0,
                "free": 0,
                "loaded_models": []
            }
        
        return {
            "has_gpu": True,
            "device": "CUDA",
            "total_memory": self.total_memory,
            "allocated": torch.cuda.memory_allocated(0),
            "reserved": torch.cuda.memory_reserved(0),
            "free": self.total_memory - torch.cuda.memory_allocated(0),
            "max_allowed": self.max_memory,
            "loaded_models": list(self.loaded_models.keys()),
            "model_ref_counts": self.model_ref_counts
        }
    
    def optimize_batch(self, model_type: str, items: List[Any]) -> List[List[Any]]:
        """Optimiser le batch processing"""
        batch_size = self.get_batch_size(model_type)
        return [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    
    def is_gpu_available(self) -> bool:
        """Vérifier si le GPU est disponible"""
        return self.has_gpu
