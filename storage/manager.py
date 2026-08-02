"""
Agnes IA - Gestionnaire de Stockage
Stockage persistant avec Supabase + S3 + récupération des vidéos perdues
"""

import os
import time
import hashlib
import asyncio
from typing import Dict, Any, Optional
from pathlib import Path
import aioboto3
import logging

from config import config

logger = logging.getLogger(__name__)


class StorageManager:
    """
    Gestionnaire de stockage pour les vidéos et fichiers.
    
    Fonctionnalités:
    - Upload vers S3 et Supabase
    - Vérification d'existence
    - Récupération automatique des vidéos perdues
    - Stockage double pour la redondance
    """
    
    def __init__(self):
        self.s3 = None
        self.supabase = None
        
        # Initialiser S3
        if config.AWS_ACCESS_KEY_ID and config.AWS_SECRET_ACCESS_KEY:
            self.s3 = aioboto3.client(
                's3',
                aws_access_key_id=config.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
                region_name=config.S3_REGION
            )
            self.bucket = config.S3_BUCKET
        
        # Initialiser Supabase
        try:
            from supabase import create_client
            if config.SUPABASE_URL and config.SUPABASE_KEY:
                self.supabase = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        except Exception as e:
            logger.warning(f"Could not initialize Supabase: {e}")
        
        # Créer les répertoires locaux
        Path(config.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(config.QUARANTINE_DIR).mkdir(parents=True, exist_ok=True)
        
        logger.info("StorageManager initialized")
    
    async def upload(self, file_path: str, job_id: str, user_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Upload un fichier vers le stockage persistant.
        
        Args:
            file_path: Chemin du fichier local
            job_id: ID du job
            user_id: ID de l'utilisateur
            metadata: Métadonnées à sauvegarder
            
        Returns:
            str: URL du fichier stocké
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        file_name = os.path.basename(file_path)
        timestamp = int(time.time())
        
        # Chemin S3
        s3_key = f"users/{user_id}/videos/{job_id}/{timestamp}_{file_name}"
        
        # Upload vers S3
        s3_url = None
        if self.s3:
            try:
                s3_url = await self._upload_to_s3(file_path, s3_key)
                logger.info(f"Uploaded to S3: {s3_url}")
            except Exception as e:
                logger.error(f"S3 upload failed: {str(e)}")
        
        # Sauvegarder les métadonnées dans Supabase
        if self.supabase:
            try:
                file_hash = self._calculate_hash(file_path)
                file_size = os.path.getsize(file_path)
                
                self.supabase.table("videos").insert({
                    "id": job_id,
                    "user_id": user_id,
                    "s3_path": s3_url or f"s3://{self.bucket}/{s3_key}",
                    "original_path": file_path,
                    "hash": file_hash,
                    "size": file_size,
                    "metadata": metadata or {},
                    "status": "completed",
                    "created_at": time.time()
                }).execute()
                
                logger.info(f"Metadata saved to Supabase for job {job_id}")
            except Exception as e:
                logger.error(f"Supabase save failed: {str(e)}")
        
        # Nettoyer le fichier local si configuré
        if not config.KEEP_TEMP_FILES:
            try:
                os.remove(file_path)
                logger.info(f"Cleaned up local file: {file_path}")
            except Exception as e:
                logger.error(f"Failed to clean up {file_path}: {str(e)}")
        
        return s3_url or f"s3://{self.bucket}/{s3_key}"
    
    async def _upload_to_s3(self, file_path: str, s3_key: str, max_retries: int = 3) -> str:
        """Upload vers S3 avec retry"""
        for attempt in range(max_retries):
            try:
                await self.s3.upload_file(
                    file_path,
                    self.bucket,
                    s3_key,
                    ExtraArgs={
                        'ACL': 'private',
                        'StorageClass': 'STANDARD'
                    }
                )
                return f"s3://{self.bucket}/{s3_key}"
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                delay = 2 ** attempt
                logger.warning(f"S3 upload attempt {attempt + 1} failed, retrying in {delay}s...")
                await asyncio.sleep(delay)
        
        raise Exception("Failed to upload to S3 after retries")
    
    def _calculate_hash(self, file_path: str) -> str:
        """Calculer le hash SHA256 d'un fichier"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    async def verify_exists(self, video_path: str) -> bool:
        """Vérifier l'existence et l'intégrité d'une vidéo"""
        if not os.path.exists(video_path):
            return False
        
        # Calculer le hash
        file_hash = self._calculate_hash(video_path)
        
        # Vérifier dans Supabase
        if self.supabase:
            try:
                response = self.supabase.table("videos")                    .select("hash")                    .eq("path", video_path)
                    .execute()
                
                if response.data:
                    return response.data[0]["hash"] == file_hash
            except Exception as e:
                logger.error(f"Supabase verification failed: {str(e)}")
        
        return True
    
    async def auto_recover(self, video_id: str) -> bool:
        """
        Tenter de récupérer une vidéo perdue.
        
        Args:
            video_id: ID de la vidéo
            
        Returns:
            bool: True si la récupération a réussi
        """
        if not self.supabase:
            logger.warning("Supabase not configured, cannot auto-recover")
            return False
        
        try:
            # Récupérer les métadonnées
            response = self.supabase.table("videos")                .select("*")
                .eq("id", video_id)
                .execute()
            
            if not response.data:
                logger.warning(f"Video {video_id} not found in database")
                return False
            
            video = response.data[0]
            
            # Vérifier si le fichier existe localement
            if os.path.exists(video.get("original_path", "")):
                try:
                    s3_key = f"videos/{video_id}/{os.path.basename(video['original_path'])}"
                    await self._upload_to_s3(video["original_path"], s3_key)
                    
                    # Mettre à jour le statut
                    self.supabase.table("videos").update({
                        "status": "recovered",
                        "s3_path": f"s3://{self.bucket}/{s3_key}",
                        "updated_at": time.time()
                    }).eq("id", video_id).execute()
                    
                    logger.info(f"Recovered video {video_id} from local storage")
                    return True
                except Exception as e:
                    logger.error(f"Recovery from local failed: {str(e)}")
            
            # Vérifier si le fichier existe sur S3
            if video.get("s3_path"):
                try:
                    s3_key = video["s3_path"].replace(f"s3://{self.bucket}/", "")
                    if self.s3:
                        await self.s3.head_object(
                            Bucket=self.bucket,
                            Key=s3_key
                        )
                        # Le fichier existe sur S3
                        self.supabase.table("videos").update({
                            "status": "recovered",
                            "updated_at": time.time()
                        }).eq("id", video_id).execute()
                        
                        logger.info(f"Video {video_id} already exists on S3")
                        return True
                except Exception as e:
                    logger.error(f"S3 verification failed: {str(e)}")
            
            logger.warning(f"Could not recover video {video_id}")
            return False
            
        except Exception as e:
            logger.error(f"Auto recovery failed: {str(e)}")
            return False
    
    async def download(self, s3_url: str, local_path: str) -> str:
        """Télécharger un fichier depuis S3"""
        if not self.s3:
            raise Exception("S3 not configured")
        
        s3_key = s3_url.replace(f"s3://{self.bucket}/", "")
        
        await self.s3.download_file(
            self.bucket,
            s3_key,
            local_path
        )
        
        logger.info(f"Downloaded from S3: {s3_url} -> {local_path}")
        return local_path
    
    async def get_metadata(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Récupérer les métadonnées d'une vidéo"""
        if not self.supabase:
            return None
        
        try:
            response = self.supabase.table("videos")                .select("*")
                .eq("id", video_id)
                .execute()
            
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Failed to get metadata: {str(e)}")
            return None
    
    async def list_user_videos(self, user_id: str, limit: int = 100) -> list:
        """Lister les vidéos d'un utilisateur"""
        if not self.supabase:
            return []
        
        try:
            response = self.supabase.table("videos")                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            
            return response.data or []
        except Exception as e:
            logger.error(f"Failed to list videos: {str(e)}")
            return []
    
    async def delete_video(self, video_id: str) -> bool:
        """Supprimer une vidéo du stockage"""
        metadata = await self.get_metadata(video_id)
        if not metadata:
            return False
        
        try:
            # Supprimer de S3
            if self.s3 and metadata.get("s3_path"):
                s3_key = metadata["s3_path"].replace(f"s3://{self.bucket}/", "")
                await self.s3.delete_object(
                    Bucket=self.bucket,
                    Key=s3_key
                )
                logger.info(f"Deleted from S3: {metadata['s3_path']}")
        except Exception as e:
            logger.error(f"S3 deletion failed: {str(e)}")
        
        # Supprimer de Supabase
        if self.supabase:
            try:
                self.supabase.table("videos")                    .delete()
                    .eq("id", video_id)
                    .execute()
                logger.info(f"Deleted from Supabase: {video_id}")
            except Exception as e:
                logger.error(f"Supabase deletion failed: {str(e)}")
        
        return True
