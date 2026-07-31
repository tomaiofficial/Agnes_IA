"""
core/video — Modules avancés de post-traitement et d'orchestration vidéo (v8.0)

Sous-modules :
  - postprocess : upscaling, débruitage, amélioration visage/mouvement, HDR
  - prompt_optimizer : optimisation IA des prompts
  - queue : file d'attente asynchrone avec priorités
  - monitoring : collecte de métriques et logs
  - pipeline : orchestrateur complet du pipeline IA
"""

from core.video.postprocess import (
    VideoPostProcessor,
    PostProcessConfig,
    RESOLUTIONS,
    VIDEO_STYLES,
)
from core.video.prompt_optimizer import (
    PromptOptimizer,
    OptimizationResult,
)
from core.video.queue import (
    VideoQueue,
    TaskPriority,
    QueuedTask,
)
from core.video.monitoring import (
    VideoMonitor,
    TaskMetrics,
    StageMetrics,
)
from core.video.pipeline import (
    AIVideoPipeline,
    PipelineConfig,
    GenerationResult,
)

__all__ = [
    "VideoPostProcessor",
    "PostProcessConfig",
    "RESOLUTIONS",
    "VIDEO_STYLES",
    "PromptOptimizer",
    "OptimizationResult",
    "VideoQueue",
    "TaskPriority",
    "QueuedTask",
    "VideoMonitor",
    "TaskMetrics",
    "StageMetrics",
    "AIVideoPipeline",
    "PipelineConfig",
    "GenerationResult",
]
