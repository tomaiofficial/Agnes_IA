"""
Agnes IA - Gestionnaire de Sécurité
Protection DDoS, validation des uploads, quarantaine, logs
"""

import os
import time
import hashlib
import logging
import magic
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

from fastapi import HTTPException, UploadFile, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import config

logger = logging.getLogger(__name__)

try:
    import clamd
    HAS_CLAMAV = True
except ImportError:
    HAS_CLAMAV = False


class SecurityManager:
    """
    Gestionnaire de sécurité pour Agnes IA.
    
    Fonctionnalités:
    - Validation des uploads (type MIME, taille, extension)
    - Scan antivirus avec ClamAV
    - Mise en quarantaine des fichiers suspects
    - Protection DDoS
    - Authentification API
    - Logging des requêtes
    """
    
    def __init__(self):
        self.bearer = HTTPBearer()
        self.clamav = self._init_clamav()
        
        # Créer les répertoires
        Path(config.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(config.QUARANTINE_DIR).mkdir(parents=True, exist_ok=True)
        
        logger.info("SecurityManager initialized")
    
    def _init_clamav(self):
        """Initialiser la connexion à ClamAV"""
        if HAS_CLAMAV and config.CLAMAV_ENABLED:
            try:
                return clamd.ClamdUnixSocket(config.CLAMAV_SOCKET)
            except Exception as e:
                logger.warning(f"Could not connect to ClamAV: {e}")
        return None
    
    async def validate_upload(self, file: UploadFile) -> Tuple[bool, str]:
        """
        Valider un fichier uploadé.
        
        Args:
            file: UploadFile à valider
            
        Returns:
            Tuple: (is_valid, message)
        """
        # 1. Vérifier la taille
        if file.size > config.MAX_FILE_SIZE:
            logger.warning(f"File too large: {file.filename} ({file.size} bytes)")
            return False, f"Fichier trop grand (max {config.MAX_FILE_SIZE // (1024*1024)}MB)"
        
        # 2. Lire le contenu pour détecter le type MIME
        try:
            content = await file.read(2048)
            file.file.seek(0)  # Réinitialiser le pointeur
        except:
            return False, "Impossible de lire le fichier"
        
        # 3. Vérifier le type MIME
        mime_type = magic.from_buffer(content, mime=True)
        if mime_type not in config.ALLOWED_MIME_TYPES:
            logger.warning(f"Invalid MIME type: {file.filename} ({mime_type})")
            return False, f"Type de fichier non autorisé: {mime_type}"
        
        # 4. Vérifier l'extension
        allowed_extensions = {
            "video/mp4": [".mp4", ".m4v"],
            "video/webm": [".webm"],
            "video/quicktime": [".mov"],
            "image/jpeg": [".jpg", ".jpeg"],
            "image/png": [".png"],
            "image/webp": [".webp"],
            "audio/mpeg": [".mp3"],
            "audio/wav": [".wav"],
            "audio/ogg": [".ogg", ".oga"]
        }
        
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions.get(mime_type, []):
            logger.warning(f"Extension mismatch: {file.filename} (type: {mime_type}, ext: {file_ext})")
            return False, f"Extension de fichier non valide pour le type {mime_type}"
        
        return True, "Valid"
    
    async def scan_file(self, file_path: str) -> Tuple[bool, str]:
        """
        Scanner un fichier avec ClamAV.
        
        Args:
            file_path: Chemin du fichier à scanner
            
        Returns:
            Tuple: (is_clean, message)
        """
        if not self.clamav:
            logger.warning("ClamAV not configured, skipping scan")
            return True, "Scan skipped (ClamAV not available)"
        
        try:
            result = self.clamav.scan(file_path)
            
            for _, virus_name in result.items():
                if virus_name != "OK":
                    logger.error(f"Virus detected: {file_path} -> {virus_name}")
                    return False, f"Virus détecté: {virus_name}"
            
            return True, "Clean"
        except Exception as e:
            logger.error(f"Scan failed: {str(e)}")
            return False, f"Scan échoué: {str(e)}"
    
    async def quarantine_file(self, file_path: str) -> str:
        """
        Mettre un fichier en quarantaine.
        
        Args:
            file_path: Chemin du fichier à mettre en quarantaine
            
        Returns:
            str: Chemin du fichier en quarantaine
        """
        timestamp = int(time.time())
        file_name = os.path.basename(file_path)
        quarantine_path = Path(config.QUARANTINE_DIR) / f"{timestamp}_{file_name}"
        
        import shutil
        shutil.move(file_path, quarantine_path)
        
        # Calculer le hash
        file_hash = self._calculate_file_hash(quarantine_path)
        
        logger.warning(f"File quarantined: {file_name} -> {quarantine_path} (hash: {file_hash})")
        return str(quarantine_path)
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculer le hash SHA256 d'un fichier"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    async def process_upload(self, file: UploadFile) -> Tuple[Optional[str], str]:
        """
        Traiter un upload de fichier (validation + quarantaine + scan).
        
        Args:
            file: UploadFile à traiter
            
        Returns:
            Tuple: (final_path, message)
        """
        # 1. Valider le fichier
        is_valid, validation_msg = await self.validate_upload(file)
        if not is_valid:
            return None, validation_msg
        
        # 2. Sauvegarder en quarantaine temporaire
        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name
        
        try:
            # Sauvegarder le fichier temporairement
            with open(temp_path, 'wb') as f:
                content = await file.read()
                f.write(content)
            
            # 3. Scanner le fichier
            is_clean, scan_msg = await self.scan_file(temp_path)
            if not is_clean:
                # Mettre en quarantaine
                quarantine_path = await self.quarantine_file(temp_path)
                return None, f"Fichier infecté: {scan_msg}. Mise en quarantaine: {quarantine_path}"
            
            # 4. Déplacer vers l'emplacement final
            final_path = f"{config.UPLOAD_DIR}/{int(time.time())}_{file.filename}"
            os.rename(temp_path, final_path)
            
            logger.info(f"Upload processed: {file.filename} -> {final_path}")
            return final_path, "Upload successful"
            
        except Exception as e:
            # Nettoyer en cas d'erreur
            if os.path.exists(temp_path):
                os.remove(temp_path)
            logger.error(f"Upload processing failed: {str(e)}")
            return None, f"Erreur lors du traitement: {str(e)}"
    
    def verify_api_key(self, api_key: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Vérifier une clé API.
        
        Args:
            api_key: Clé API à vérifier
            
        Returns:
            Tuple: (is_valid, user_data)
        """
        # En production, vérifier dans une base de données
        # Pour l'instant, utiliser une configuration simple
        valid_keys = {
            "test_premium_key": {"role": "premium", "user_id": "test_premium"},
            "test_admin_key": {"role": "admin", "user_id": "test_admin"},
            "test_free_key": {"role": "free", "user_id": "test_free"}
        }
        
        if api_key in valid_keys:
            return True, valid_keys[api_key]
        
        return False, {}
    
    def require_auth(self, required_role: Optional[str] = None):
        """
        Décorateur pour l'authentification.
        
        Args:
            required_role: Rôle requis (optionnel)
            
        Returns:
            Function: Décorateur
        """
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                request = None
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
                
                if not request:
                    raise HTTPException(status_code=401, detail="Non autorisé")
                
                # Récupérer les credentials
                credentials = await self.bearer(request)
                if not credentials:
                    raise HTTPException(status_code=401, detail="Non autorisé")
                
                # Vérifier la clé API
                api_key = credentials.credentials
                is_valid, user_data = self.verify_api_key(api_key)
                
                if not is_valid:
                    logger.warning(f"Invalid API key: {api_key[:8]}...")
                    raise HTTPException(status_code=401, detail="Clé API invalide")
                
                # Vérifier le rôle
                if required_role:
                    user_role = user_data.get("role", "user")
                    if user_role != required_role:
                        logger.warning(f"Insufficient permissions: {user_role} (required: {required_role})")
                        raise HTTPException(status_code=403, detail="Permissions insuffisantes")
                
                # Ajouter les données utilisateur aux kwargs
                kwargs['user_data'] = user_data
                
                return await func(*args, **kwargs)
            
            return wrapper
        return decorator
    
    def log_request(self, request: Request, response: Any, duration: float) -> None:
        """Logger une requête API"""
        log_data = {
            "timestamp": time.time(),
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration": duration,
            "client": request.client.host if hasattr(request, 'client') else "unknown",
            "user_agent": request.headers.get("user-agent", "")
        }
        
        if hasattr(request, 'user') and request.user:
            log_data["user_id"] = request.user.get("id")
        
        logger.info("API Request", extra=log_data)
    
    def detect_ddos(self, ip: str, window: int = 60, threshold: int = 100) -> bool:
        """
        Détecter une attaque DDoS.
        
        Args:
            ip: Adresse IP à vérifier
            window: Fenêtre de temps en secondes
            threshold: Seuil de requêtes
            
        Returns:
            bool: True si attaque DDoS détectée
        """
        # Implémentation simplifiée
        # En production, utiliser Redis pour compter les requêtes
        # Exemple:
        # count = redis.get(f"ddos:{ip}")
        # if count and count > threshold:
        #     return True
        return False


# Importer wraps pour le decorator
from functools import wraps
