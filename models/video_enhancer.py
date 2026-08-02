"""
Agnes IA - Améliorateur de Vidéos
Upscaling, amélioration des visages, stabilisation, etc.
"""

import os
import tempfile
import cv2
import numpy as np
from typing import Optional, Dict, Any
from pathlib import Path
from config import config
import logging

logger = logging.getLogger(__name__)


class VideoEnhancer:
    """
    Améliorateur de vidéos avec plusieurs fonctionnalités:
    - Upscaling (ESRGAN, Real-ESRGAN)
    - Amélioration des visages (GFPGAN)
    - Débruitage
    - HDR
    - Sharpening
    - Compression
    - Stabilisation
    """
    
    def __init__(self):
        self.upscaler = None
        self.face_enhancer = None
        self._init_models()
    
    def _init_models(self):
        """Initialiser les modèles d'amélioration"""
        try:
            from realesrgan import RealESRGANer
            self.upscaler = RealESRGANer(
                scale=4,
                model_path="RealESRGAN_x4plus",
                model=self._download_model("RealESRGAN_x4plus"),
                gpu_id=0 if self._has_gpu() else None
            )
            logger.info("RealESRGAN model loaded")
        except Exception as e:
            logger.warning(f"Could not load RealESRGAN: {e}")
            self.upscaler = None
        
        try:
            # Charger GFPGAN pour l'amélioration des visages
            import gfpgan
            self.face_enhancer = gfpgan.GFPGAN(
                model_path=self._download_model("GFPGANv1.3"),
                upscale=2,
                arch="clean",
                channel_multiplier=2
            )
            logger.info("GFPGAN model loaded")
        except Exception as e:
            logger.warning(f"Could not load GFPGAN: {e}")
            self.face_enhancer = None
    
    def _has_gpu(self) -> bool:
        """Vérifier si le GPU est disponible"""
        try:
            import torch
            return torch.cuda.is_available()
        except:
            return False
    
    def _download_model(self, model_name: str) -> str:
        """Télécharger un modèle (simplifié)"""
        # En production, utiliser huggingface_hub ou un cache local
        model_dir = Path(config.UPLOAD_DIR) / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        return str(model_dir / model_name)
    
    def upscale(self, video_path: str, scale: float = 4.0) -> str:
        """Upscaler une vidéo"""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        if not self.upscaler:
            return self._upscale_simple(video_path, scale)
        
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            output_path = f.name
        
        try:
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(
                output_path,
                fourcc,
                fps,
                (int(width * scale), int(height * scale))
            )
            
            frame_count = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Upscaler le frame
                enhanced_frame = self.upscaler.predict(frame)
                
                out.write(enhanced_frame)
                frame_count += 1
                
                if frame_count % 10 == 0:
                    logger.info(f"Upscaling frame {frame_count}")
            
            cap.release()
            out.release()
            
            logger.info(f"Upscaled video: {video_path} -> {output_path} ({scale}x)")
            return output_path
            
        except Exception as e:
            if os.path.exists(output_path):
                os.remove(output_path)
            logger.error(f"Upscaling failed: {str(e)}")
            raise
    
    def _upscale_simple(self, video_path: str, scale: float = 4.0) -> str:
        """Upscaling simple avec OpenCV"""
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            output_path = f.name
        
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(
            output_path,
            fourcc,
            fps,
            (int(width * scale), int(height * scale))
        )
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            upscaled = cv2.resize(
                frame,
                (int(width * scale), int(height * scale)),
                interpolation=cv2.INTER_LANCZOS4
            )
            
            out.write(upscaled)
        
        cap.release()
        out.release()
        
        logger.info(f"Simple upscaled video: {video_path} -> {output_path} ({scale}x)")
        return output_path
    
    def enhance_faces(self, video_path: str) -> str:
        """Améliorer les visages dans une vidéo"""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        if not self.face_enhancer:
            logger.warning("GFPGAN not available, skipping face enhancement")
            return video_path
        
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            output_path = f.name
        
        try:
            import torch
            from basicsr.utils import img2tensor, tensor2img
            
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            
            frame_count = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Convertir en RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # Améliorer le visage
                _, _, restored_img = self.face_enhancer.enhance(
                    frame_rgb,
                    has_aligned=False,
                    only_center_face=False,
                    paste_back=True
                )
                
                # Convertir en BGR pour OpenCV
                restored_bgr = cv2.cvtColor(restored_img, cv2.COLOR_RGB2BGR)
                
                out.write(restored_bgr)
                frame_count += 1
                
                if frame_count % 10 == 0:
                    logger.info(f"Enhanced faces on frame {frame_count}")
            
            cap.release()
            out.release()
            
            logger.info(f"Enhanced faces: {video_path} -> {output_path}")
            return output_path
            
        except Exception as e:
            if os.path.exists(output_path):
                os.remove(output_path)
            logger.error(f"Face enhancement failed: {str(e)}")
            return video_path
    
    def denoise(self, video_path: str, strength: float = 0.5) -> str:
        """Débruiter une vidéo"""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            output_path = f.name
        
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            denoised = cv2.fastNlMeansDenoisingColored(
                frame,
                None,
                h=10 * strength,
                hColor=10 * strength,
                templateWindowSize=7,
                searchWindowSize=21
            )
            
            out.write(denoised)
        
        cap.release()
        out.release()
        
        logger.info(f"Denoised video: {video_path} -> {output_path}")
        return output_path
    
    def apply_hdr(self, video_path: str) -> str:
        """Appliquer le HDR à une vidéo"""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            output_path = f.name
        
        try:
            import ffmpeg
            (
                ffmpeg
                .input(video_path)
                .output(
                    output_path,
                    vf="tonemap=tonemap=hable:desat=0",
                    crf=18,
                    preset="slow"
                )
                .run(overwrite_output=True, quiet=True)
            )
            logger.info(f"Applied HDR: {video_path} -> {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"HDR failed, falling back to copy: {str(e)}")
            import shutil
            shutil.copy(video_path, output_path)
            return output_path
    
    def sharpen(self, video_path: str, amount: float = 1.5) -> str:
        """Appliquer un sharpening à une vidéo"""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            output_path = f.name
        
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        
        kernel = np.array([
            [-1, -1, -1],
            [-1, 9 + amount, -1],
            [-1, -1, -1]
        ])
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            sharpened = cv2.filter2D(frame, -1, kernel)
            out.write(sharpened)
        
        cap.release()
        out.release()
        
        logger.info(f"Sharpened video: {video_path} -> {output_path}")
        return output_path
    
    def compress(self, video_path: str, target_size_mb: Optional[float] = None, crf: int = 23) -> str:
        """Compresser une vidéo"""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            output_path = f.name
        
        if target_size_mb:
            current_size = os.path.getsize(video_path) / (1024 * 1024)
            if current_size <= target_size_mb:
                import shutil
                shutil.copy(video_path, output_path)
                return output_path
            
            ratio = target_size_mb / current_size
            crf = min(51, max(18, int(23 + (1 - ratio) * 20)))
        
        try:
            import ffmpeg
            (
                ffmpeg
                .input(video_path)
                .output(
                    output_path,
                    crf=crf,
                    preset="medium",
                    vcodec="libx264",
                    acodec="aac"
                )
                .run(overwrite_output=True, quiet=True)
            )
            logger.info(f"Compressed video: {video_path} -> {output_path} (CRF: {crf})")
            return output_path
        except Exception as e:
            logger.error(f"Compression failed: {str(e)}")
            import shutil
            shutil.copy(video_path, output_path)
            return output_path
    
    def stabilize(self, video_path: str, radius: int = 15) -> str:
        """Stabiliser une vidéo"""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            output_path = f.name
        
        try:
            import ffmpeg
            (
                ffmpeg
                .input(video_path)
                .output(
                    output_path,
                    vf=f"vidstab=shakiness=5:accuracy={radius}",
                    crf=18
                )
                .run(overwrite_output=True, quiet=True)
            )
            logger.info(f"Stabilized video: {video_path} -> {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Stabilization failed: {str(e)}")
            import shutil
            shutil.copy(video_path, output_path)
            return output_path
