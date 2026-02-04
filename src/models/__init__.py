"""
Shared Pydantic models for B-Roll Finder.

These models are used across CLI, API, and core library components.
"""

from src.models.entity import (
    Entity,
    Occurrence,
    ImageMetadata,
    SearchStrategies,
    DisambiguationMetadata,
)
from src.models.disambiguation import (
    CandidateInfo,
    DisambiguationDecision,
    DisambiguationReviewEntry,
)
from src.models.pipeline import (
    PipelineConfig,
    PipelineCheckpoint,
    PipelineStep,
)

__all__ = [
    # Entity models
    "Entity",
    "Occurrence",
    "ImageMetadata",
    "SearchStrategies",
    "DisambiguationMetadata",
    # Disambiguation models
    "CandidateInfo",
    "DisambiguationDecision",
    "DisambiguationReviewEntry",
    # Pipeline models
    "PipelineConfig",
    "PipelineCheckpoint",
    "PipelineStep",
]
