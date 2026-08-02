"""
Agnes IA - Pipeline Principal (9 étapes)
Pipeline: PROMPT -> ANALYSE -> OPTIMISATION -> GENERATION -> UPSCALING -> FACE/MOUVEMENT -> AUDIO -> COMPRESSION -> DELIVERY
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


class IAPipeline:
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
        logger.info("IAPipeline initialized")

    async def process(self, job: Dict[str, Any]) -> PipelineResult:
        job_id = job.get("id", self._generate_job_id(job))
        start_time = time.time()
        result = PipelineResult(job_id=job_id, success=False, data={"job_id": job_id}, steps={})
        self.monitor.start_job(job_id, job.get("user_id", "anonymous"), job.get("priority", "free"))
        
        try:
            result.steps["prompt"] = await self._step_prompt(job)
            if not result.steps["prompt"].success:
                raise Exception(result.steps["prompt"].error)
            
            result.steps["analyse"] = await self._step_analyse(job, result)
            if not result.steps["analyse"].success:
                raise Exception(result.steps["analyse"].error)
            
            result.steps["optimisation"] = await self._step_optimisation(job, result)
            result.steps["generation"] = await self._step_generation(job, result)
            if not result.steps["generation"].success:
                raise Exception(result.steps["generation"].error)
            
            result.steps["upscaling"] = await self._step_upscaling(job, result)
            result.steps["face_enhancement"] = await self._step_face_enhancement(job, result)
            result.steps["audio"] = await self._step_audio(job, result)
            result.steps["compression"] = await self._step_compression(job, result)
            if not result.steps["compression"].success:
                raise Exception(result.steps["compression"].error)
            
            result.steps["delivery"] = await self._step_delivery(job, result)
            if not result.steps["delivery"].success:
                raise Exception(result.steps["delivery"].error)
            
            result.success = True
            result.total_duration = time.time() - start_time
            result.data.update({"status": "completed", "duration": result.total_duration, "url": result.steps["delivery"].data.get("url")})
            self.monitor.complete_job(job_id, True)
            logger.info(f"Job completed: {job_id} ({result.total_duration:.2f}s)")
            
        except Exception as e:
            logger.error(f"Pipeline error for {job_id}: {str(e)}")
            result.error = str(e)
            result.success = False
            result.total_duration = time.time() - start_time
            self.monitor.complete_job(job_id, False, str(e))
        
        return result

    async def _step_prompt(self, job: Dict[str, Any]) -> StepResult:
        start = time.time()
        try:
            prompt = job.get("prompt", "")
            if not prompt or not prompt.strip():
                return StepResult(success=False, error="Prompt is required", duration=time.time()-start)
            cleaned_prompt = self.prompt_optimizer.clean(prompt)
            if len(cleaned_prompt) > 1000:
                return StepResult(success=False, error="Prompt too long (max 1000 chars)", duration=time.time()-start)
            self.monitor.log(job.get("id", "unknown"), "PROMPT", "SUCCESS", duration=time.time()-start)
            return StepResult(success=True, data={"original_prompt": prompt, "cleaned_prompt": cleaned_prompt}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _step_analyse(self, job: Dict[str, Any], result: PipelineResult) -> StepResult:
        start = time.time()
        try:
            prompt = result.steps["prompt"].data["cleaned_prompt"]
            analysis = self.prompt_optimizer.analyse(prompt)
            resolution = job.get("resolution", "1080p")
            duration = job.get("duration", 10)
            style = job.get("style", analysis.get("style", "realistic"))
            self.monitor.log(result.job_id, "ANALYSE", "SUCCESS", duration=time.time()-start)
            return StepResult(success=True, data={"analysis": analysis, "resolution": resolution, "duration": duration, "style": style}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _step_optimisation(self, job: Dict[str, Any], result: PipelineResult) -> StepResult:
        start = time.time()
        try:
            prompt = result.steps["prompt"].data["cleaned_prompt"]
            analysis = result.steps["analyse"].data
            optimized_prompt = self.prompt_optimizer.optimize(prompt, analysis)
            variations = self.prompt_optimizer.generate_variations(prompt, count=3)
            self.monitor.log(result.job_id, "OPTIMISATION", "SUCCESS", duration=time.time()-start)
            return StepResult(success=True, data={"original_prompt": prompt, "optimized_prompt": optimized_prompt, "variations": variations}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _step_generation(self, job: Dict[str, Any], result: PipelineResult) -> StepResult:
        start = time.time()
        try:
            prompt = result.steps["optimisation"].data["optimized_prompt"]
            analysis = result.steps["analyse"].data
            cache_key = f"generation:{hashlib.sha256(prompt.encode()).hexdigest()}"
            cached_result = await self.cache.get(cache_key)
            if cached_result:
                logger.info(f"Cache hit for generation: {cache_key}")
                return StepResult(success=True, data=cached_result, duration=0.01, metadata={"cached": True})
            video_path = await self._generate_video(prompt, analysis["resolution"], analysis["duration"], analysis["style"])
            await self.cache.set(cache_key, {"video_path": video_path}, ttl=86400)
            self.monitor.log(result.job_id, "GENERATION", "SUCCESS", duration=time.time()-start)
            return StepResult(success=True, data={"video_path": video_path}, duration=time.time()-start, metadata={"cached": False})
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _generate_video(self, prompt: str, resolution: str, duration: int, style: str) -> str:
        output_path = f"{config.UPLOAD_DIR}/{int(time.time())}_raw.mp4"
        Path(output_path).touch()
        logger.info(f"Generated video (PLACEHOLDER): {output_path}")
        logger.warning("IMPLEMENT _generate_video() with real AI model")
        return output_path

    async def _step_upscaling(self, job: Dict[str, Any], result: PipelineResult) -> StepResult:
        start = time.time()
        try:
            video_path = result.steps["generation"].data["video_path"]
            analysis = result.steps["analyse"].data
            target_resolution = analysis.get("resolution", "4k")
            scale = self._get_upscale_factor(target_resolution)
            cache_key = f"upscale:{hashlib.sha256(video_path.encode()).hexdigest()}:{scale}"
            cached_result = await self.cache.get(cache_key)
            if cached_result:
                logger.info(f"Cache hit for upscaling: {cache_key}")
                return StepResult(success=True, data=cached_result, duration=0.01, metadata={"cached": True})
            upscaled_path = self.video_enhancer.upscale(video_path, scale)
            await self.cache.set(cache_key, {"video_path": upscaled_path}, ttl=86400)
            self.monitor.log(result.job_id, "UPSCALING", "SUCCESS", duration=time.time()-start)
            return StepResult(success=True, data={"video_path": upscaled_path}, duration=time.time()-start, metadata={"scale_factor": scale})
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    def _get_upscale_factor(self, resolution: str) -> float:
        resolution_map = {"4k": 4.0, "2k": 2.0, "1440p": 1.5, "1080p": 1.0, "720p": 0.5}
        return resolution_map.get(resolution.lower(), 4.0)

    async def _step_face_enhancement(self, job: Dict[str, Any], result: PipelineResult) -> StepResult:
        start = time.time()
        try:
            video_path = result.steps["upscaling"].data["video_path"]
            cache_key = f"face_enhance:{hashlib.sha256(video_path.encode()).hexdigest()}"
            cached_result = await self.cache.get(cache_key)
            if cached_result:
                logger.info(f"Cache hit for face enhancement: {cache_key}")
                return StepResult(success=True, data=cached_result, duration=0.01, metadata={"cached": True})
            enhanced_path = self.video_enhancer.enhance_faces(video_path)
            stabilized_path = self.video_enhancer.stabilize(enhanced_path)
            await self.cache.set(cache_key, {"video_path": stabilized_path}, ttl=86400)
            self.monitor.log(result.job_id, "FACE_ENHANCEMENT", "SUCCESS", duration=time.time()-start)
            return StepResult(success=True, data={"video_path": stabilized_path}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _step_audio(self, job: Dict[str, Any], result: PipelineResult) -> StepResult:
        start = time.time()
        try:
            audio_path = job.get("audio_path")
            if audio_path and os.path.exists(audio_path):
                enhanced_audio = self.audio_enhancer.enhance(audio_path)
                return StepResult(success=True, data={"audio_path": enhanced_audio}, duration=time.time()-start, metadata={"processed": True})
            return StepResult(success=True, data={}, duration=time.time()-start, metadata={"processed": False, "reason": "no_audio"})
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _step_compression(self, job: Dict[str, Any], result: PipelineResult) -> StepResult:
        start = time.time()
        try:
            video_path = result.steps["face_enhancement"].data["video_path"]
            target_size_mb = job.get("target_size_mb")
            compressed_path = self.video_enhancer.compress(video_path, target_size_mb=target_size_mb)
            self.monitor.log(result.job_id, "COMPRESSION", "SUCCESS", duration=time.time()-start)
            return StepResult(success=True, data={"video_path": compressed_path}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    async def _step_delivery(self, job: Dict[str, Any], result: PipelineResult) -> StepResult:
        start = time.time()
        try:
            video_path = result.steps["compression"].data["video_path"]
            audio_path = result.steps["audio"].data.get("audio_path") if result.steps["audio"].success else None
            user_id = job.get("user_id", "anonymous")
            delivery_url = await self.storage.upload(video_path, result.job_id, user_id, {"prompt": result.steps["prompt"].data["original_prompt"]})
            audio_url = None
            if audio_path and os.path.exists(audio_path):
                audio_url = await self.storage.upload(audio_path, f"{result.job_id}_audio", user_id, {"type": "audio"})
            self.monitor.log(result.job_id, "DELIVERY", "SUCCESS", duration=time.time()-start)
            return StepResult(success=True, data={"video_url": delivery_url, "audio_url": audio_url}, duration=time.time()-start)
        except Exception as e:
            return StepResult(success=False, error=str(e), duration=time.time()-start)

    def _generate_job_id(self, job: Dict[str, Any]) -> str:
        user_id = job.get("user_id", "anonymous")
        timestamp = int(time.time() * 1000)
        random_part = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=4))
        return f"{user_id[:8]}_{timestamp}_{random_part}"
