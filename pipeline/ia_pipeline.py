"""
Agnes IA - Pipeline Principal (9 étapes) - Version Améliorée
Pipeline: PROMPT -> ANALYSE -> OPTIMISATION -> GENERATION -> UPSCALING -> FACE/MOUVEMENT -> AUDIO -> COMPRESSION -> DELIVERY

Améliorations:
- Affichage précis des pourcentages
- Gestion robuste des échecs vidéo
- Logging détaillé
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum, auto
import asyncio
import time
import hashlib
import logging
import os
import random
from pathlib import Path

from config import config

try:
    from models.prompt_optimizer import PromptOptimizer
    from models.video_enhancer import VideoEnhancer
    from models.audio_enhancer import AudioEnhancer
    from storage.manager import StorageManager
    from cache.redis_cache import RedisCache
    from utils.gpu_optimizer import GPUOptimizer
    from monitoring.manager import Monitor
    HAS_DEPENDENCIES = True
except ImportError as e:
    logging.warning(f"Missing dependencies: {e}")
    HAS_DEPENDENCIES = False

logger = logging.getLogger(__name__)


class PipelineStep(Enum):
    PROMPT = auto()
    ANALYSE = auto()
    OPTIMISATION = auto()
    GENERATION = auto()
    UPSCALING = auto()
    FACE_ENHANCEMENT = auto()
    AUDIO = auto()
    COMPRESSION = auto()
    DELIVERY = auto()


@dataclass
class StepResult:
    success: bool
    data: Any = None
    error: Optional[str] = None
    duration: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass  
class PipelineResult:
    job_id: str
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    steps: Dict[str, StepResult] = field(default_factory=dict)
    total_duration: float = 0.0
    current_step: Optional[str] = None
    progress_percent: float = 0.0


class IAPipeline:
    STEP_WEIGHTS = {
        "prompt": 5,
        "analyse": 5,
        "optimisation": 5,
        "generation": 25,
        "upscaling": 15,
        "face_enhancement": 15,
        "audio": 10,
        "compression": 10,
        "delivery": 15
    }
    
    TOTAL_WEIGHT = sum(STEP_WEIGHTS.values())
    
    def __init__(self):
        if not HAS_DEPENDENCIES:
            logger.warning("Some dependencies are missing")
            return
        self.prompt_optimizer = PromptOptimizer()
        self.video_enhancer = VideoEnhancer()
        self.audio_enhancer = AudioEnhancer()
        self.storage = StorageManager()
        self.cache = RedisCache()
        self.gpu = GPUOptimizer()
        self.monitor = Monitor()
        Path(config.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

    def _calculate_progress(self, completed_steps, current_step=None):
        completed_weight = sum(self.STEP_WEIGHTS.get(step, 0) for step in completed_steps)
        if current_step:
            current_weight = self.STEP_WEIGHTS.get(current_step, 0)
            completed_weight += current_weight * 0.5
        progress = (completed_weight / self.TOTAL_WEIGHT) * 100
        return round(min(100, max(0, progress)), 1)

    async def process(self, job):
        job_id = job.get("id", self._generate_job_id(job))
        start_time = time.time()
        result = PipelineResult(job_id=job_id, success=False, data={"job_id": job_id, "status": "processing", "progress": 0}, steps={}, current_step=None, progress_percent=0.0)
        self.monitor.start_job(job_id, job.get("user_id", "anonymous"), job.get("priority", "free"))
        completed_steps = []
        
        try:
            for step_name in ["prompt", "analyse", "optimisation", "generation", "upscaling", "face_enhancement", "audio", "compression", "delivery"]:
                result.current_step = step_name
                result.progress_percent = self._calculate_progress(completed_steps, step_name)
                result.steps[step_name] = await getattr(self, f"_step_{step_name}")(job, result)
                
                if not result.steps[step_name].success:
                    if step_name == "generation":
                        error_msg = result.steps[step_name].error
                        if "timeout" in error_msg.lower():
                            raise Exception(f"Generation timeout: {error_msg}")
                        elif "memory" in error_msg.lower():
                            raise Exception(f"Insufficient memory: {error_msg}")
                        else:
                            raise Exception(f"Video generation error: {error_msg}")
                    else:
                        raise Exception(f"{step_name.upper()} failed: {result.steps[step_name].error}")
                
                completed_steps.append(step_name)
            
            result.success = True
            result.total_duration = time.time() - start_time
            result.progress_percent = 100.0
            result.current_step = None
            result.data.update({"status": "completed", "duration": result.total_duration, "url": result.steps["delivery"].data.get("url"), "progress": 100})
            self.monitor.complete_job(job_id, True)
            
        except Exception as e:
            logger.error(f"Pipeline error for {job_id}: {str(e)}")
            result.error = str(e)
            result.success = False
            result.total_duration = time.time() - start_time
            result.progress_percent = self._calculate_progress(completed_steps, result.current_step)
            self.monitor.complete_job(job_id, False, str(e))
        
        return result

    async def _step_prompt(self, job):
        start = time.time()
        try:
            prompt = job.get("prompt", "")
            if not prompt or not prompt.strip():
                return StepResult(success=False, error="Prompt is required", duration=time.time()-start)
            cleaned_prompt = self.prompt_optimizer.clean(prompt)
            if len(cleaned_prompt) > 1000:
                return StepResult(success=False, error="Prompt too long", duration=time.time()-start)
            return StepResult(success=True, data={"original_prompt": prompt, "cleaned_prompt": cleaned_prompt}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _step_analyse(self, job, result):
        start = time.time()
        try:
            prompt = result.steps["prompt"].data["cleaned_prompt"]
            analysis = self.prompt_optimizer.analyse(prompt)
            return StepResult(success=True, data={"analysis": analysis, "resolution": job.get("resolution", "1080p"), "duration": job.get("duration", 10), "style": job.get("style", "realistic")}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _step_optimisation(self, job, result):
        start = time.time()
        try:
            prompt = result.steps["prompt"].data["cleaned_prompt"]
            analysis = result.steps["analyse"].data
            optimized_prompt = self.prompt_optimizer.optimize(prompt, analysis)
            return StepResult(success=True, data={"original_prompt": prompt, "optimized_prompt": optimized_prompt}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _step_generation(self, job, result):
        start = time.time()
        try:
            prompt = result.steps["optimisation"].data["optimized_prompt"]
            analysis = result.steps["analyse"].data
            cache_key = f"generation:{hashlib.sha256(prompt.encode()).hexdigest()}"
            cached_result = await self.cache.get(cache_key)
            if cached_result:
                return StepResult(success=True, data=cached_result, duration=0.01)
            video_path = await self._generate_video(prompt, analysis["resolution"], analysis["duration"], analysis["style"])
            await self.cache.set(cache_key, {"video_path": video_path}, ttl=86400)
            return StepResult(success=True, data={"video_path": video_path}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _generate_video(self, prompt, resolution, duration, style):
        output_path = f"{config.UPLOAD_DIR}/{int(time.time())}_raw.mp4"
        Path(output_path).touch()
        logger.warning("IMPLEMENT _generate_video() with real AI model")
        return output_path

    async def _step_upscaling(self, job, result):
        start = time.time()
        try:
            video_path = result.steps["generation"].data["video_path"]
            if not os.path.exists(video_path):
                return StepResult(success=False, error=f"Video not found: {video_path}", duration=time.time()-start)
            scale = self._get_upscale_factor(result.steps["analyse"].data.get("resolution", "4k"))
            upscaled_path = self.video_enhancer.upscale(video_path, scale)
            return StepResult(success=True, data={"video_path": upscaled_path}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    def _get_upscale_factor(self, resolution):
        return {"4k": 4.0, "2k": 2.0, "1440p": 1.5, "1080p": 1.0, "720p": 0.5}.get(resolution.lower(), 4.0)

    async def _step_face_enhancement(self, job, result):
        start = time.time()
        try:
            video_path = result.steps["upscaling"].data["video_path"]
            if not os.path.exists(video_path):
                return StepResult(success=False, error=f"Video not found: {video_path}", duration=time.time()-start)
            enhanced_path = self.video_enhancer.enhance_faces(video_path)
            stabilized_path = self.video_enhancer.stabilize(enhanced_path)
            return StepResult(success=True, data={"video_path": stabilized_path}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _step_audio(self, job, result):
        start = time.time()
        try:
            audio_path = job.get("audio_path")
            if audio_path and os.path.exists(audio_path):
                enhanced_audio = self.audio_enhancer.enhance(audio_path)
                return StepResult(success=True, data={"audio_path": enhanced_audio}, duration=time.time()-start)
            return StepResult(success=True, data={}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _step_compression(self, job, result):
        start = time.time()
        try:
            video_path = result.steps["face_enhancement"].data["video_path"]
            if not os.path.exists(video_path):
                return StepResult(success=False, error=f"Video not found: {video_path}", duration=time.time()-start)
            compressed_path = self.video_enhancer.compress(video_path, target_size_mb=job.get("target_size_mb"))
            return StepResult(success=True, data={"video_path": compressed_path}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _step_delivery(self, job, result):
        start = time.time()
        try:
            video_path = result.steps["compression"].data["video_path"]
            if not os.path.exists(video_path):
                return StepResult(success=False, error=f"Video not found: {video_path}", duration=time.time()-start)
            user_id = job.get("user_id", "anonymous")
            delivery_url = await self.storage.upload(video_path, result.job_id, user_id)
            audio_url = None
            if result.steps["audio"].success and result.steps["audio"].data.get("audio_path"):
                audio_url = await self.storage.upload(result.steps["audio"].data["audio_path"], f"{result.job_id}_audio", user_id)
            return StepResult(success=True, data={"video_url": delivery_url, "audio_url": audio_url}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    def _generate_job_id(self, job):
        user_id = job.get("user_id", "anonymous")
        timestamp = int(time.time() * 1000)
        random_part = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=4))
        return f"{user_id[:8]}_{timestamp}_{random_part}"
