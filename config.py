"""
Configuration centrale pour Agnes IA
"""
import os
from typing import Dict, Any
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()


class Config:
    """Configuration globale de l'application"""
    
    # ==================== REDIS ====================
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
    
    # ==================== SUPABASE ====================
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "https://your-project.supabase.co")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "your-supabase-key")
    
    # ==================== AMAZON S3 ====================
    AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    S3_BUCKET: str = os.getenv("S3_BUCKET", "agnes-ia")
    S3_REGION: str = os.getenv("S3_REGION", "us-east-1")
    
    # ==================== GPU ====================
    MAX_VRAM: float = float(os.getenv("MAX_VRAM", "0.9"))  # 90% de la VRAM max
    BATCH_SIZES: Dict[str, int] = {
        "stable_diffusion": int(os.getenv("BATCH_SIZE_SD", "4")),
        "upscaler": int(os.getenv("BATCH_SIZE_UPSCALE", "1")),
        "face_enhancer": int(os.getenv("BATCH_SIZE_FACE", "2")),
        "audio": int(os.getenv("BATCH_SIZE_AUDIO", "8"))
    }
    
    # ==================== RATE LIMITING ====================
    RATE_LIMIT: int = int(os.getenv("RATE_LIMIT", "100"))  # Requêtes par période
    RATE_LIMIT_PERIOD: int = int(os.getenv("RATE_LIMIT_PERIOD", "60"))  # En secondes
    BASE_DELAY: float = float(os.getenv("BASE_DELAY", "1.0"))  # Délai de base en secondes
    MAX_DELAY: float = float(os.getenv("MAX_DELAY", "3600.0"))  # Délai max (1h)
    
    # ==================== STOCKAGE ====================
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "/tmp/agnes_uploads")
    QUARANTINE_DIR: str = os.getenv("QUARANTINE_DIR", "/tmp/agnes_quarantine")
    TEMP_DIR: str = os.getenv("TEMP_DIR", "/tmp/agnes_pipeline")
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", "2147483648"))  # 2GB en octets
    KEEP_TEMP_FILES: bool = os.getenv("KEEP_TEMP_FILES", "false").lower() == "true"
    
    # ==================== SÉCURITÉ ====================
    ALLOWED_MIME_TYPES: list = [
        "video/mp4", "video/webm", "video/quicktime",
        "image/jpeg", "image/png", "image/webp",
        "audio/mpeg", "audio/wav", "audio/ogg"
    ]
    CLAMAV_ENABLED: bool = os.getenv("CLAMAV_ENABLED", "false").lower() == "true"
    CLAMAV_SOCKET: str = os.getenv("CLAMAV_SOCKET", "/var/run/clamav/clamd.ctl")
    
    # ==================== MONITORING ====================
    ELASTICSEARCH_ENABLED: bool = os.getenv("ELASTICSEARCH_ENABLED", "false").lower() == "true"
    ELASTICSEARCH_URL: str = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
    PROMETHEUS_ENABLED: bool = os.getenv("PROMETHEUS_ENABLED", "true").lower() == "true"
    PROMETHEUS_PORT: int = int(os.getenv("PROMETHEUS_PORT", "8000"))
    
    # ==================== API ====================
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    API_TITLE: str = os.getenv("API_TITLE", "Agnes IA API")
    API_VERSION: str = os.getenv("API_VERSION", "1.0.0")
    
    # ==================== PIPELINE ====================
    PIPELINE_TIMEOUT: int = int(os.getenv("PIPELINE_TIMEOUT", "3600"))  # 1h
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))


# Instance globale de configuration
config = Config()


def get_config() -> Config:
    """Retourne la configuration"""
    return config


def reload_config():
    """Recharge la configuration depuis les variables d'environnement"""
    global config
    config = Config()
