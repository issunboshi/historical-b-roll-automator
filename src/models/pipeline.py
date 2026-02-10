"""
Pipeline configuration and checkpoint models for B-Roll Finder.

These models represent pipeline state and configuration.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class PipelineStep(str, Enum):
    """Pipeline steps in execution order."""

    EXTRACT = "extract"
    EXTRACT_VISUALS = "extract-visuals"
    ENRICH = "enrich"
    MONTAGES = "montages"
    STRATEGIES = "strategies"
    DISAMBIGUATE = "disambiguate"
    DOWNLOAD = "download"
    XML = "xml"


class StepStatus(BaseModel):
    """Status of a single pipeline step."""

    completed: bool = Field(default=False, description="Whether the step is complete")
    timestamp: Optional[str] = Field(
        default=None, description="ISO timestamp of completion"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if step failed"
    )


class PipelineCheckpoint(BaseModel):
    """Checkpoint for pipeline resumption.

    Tracks which steps have been completed to enable resumable pipelines.
    """

    version: int = Field(default=1, description="Checkpoint schema version")
    srt_path: str = Field(description="Absolute path to source SRT file")
    srt_hash: str = Field(description="SHA256 hash of SRT file for change detection")
    output_dir: str = Field(description="Absolute path to output directory")
    created: str = Field(description="ISO timestamp of checkpoint creation")
    steps: Dict[str, StepStatus] = Field(
        default_factory=dict, description="Status of each pipeline step"
    )

    def get_incomplete_steps(self) -> List[PipelineStep]:
        """Get list of steps that haven't been completed yet."""
        incomplete = []
        for step in PipelineStep:
            step_status = self.steps.get(step.value, StepStatus())
            if not step_status.completed:
                incomplete.append(step)
        return incomplete

    def mark_completed(self, step: PipelineStep) -> None:
        """Mark a step as completed with current timestamp."""
        self.steps[step.value] = StepStatus(
            completed=True, timestamp=datetime.utcnow().isoformat() + "Z"
        )


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: str = Field(default="openai", description="LLM provider (openai, ollama)")
    model: str = Field(default="gpt-4o-mini", description="Model name")
    visuals_model: Optional[str] = Field(
        default=None, description="Model for visual element extraction"
    )


class PipelineConfig(BaseModel):
    """Configuration for the B-Roll pipeline.

    Combines all configuration options from CLI and config file.
    """

    # Input/Output
    srt_path: Optional[str] = Field(default=None, description="Path to SRT transcript")
    output_dir: Optional[str] = Field(default=None, description="Output directory")

    # Timeline settings
    fps: float = Field(default=25.0, description="Timeline frame rate")
    image_duration_seconds: float = Field(
        default=4.0, description="Duration of each B-roll clip"
    )
    min_gap_seconds: float = Field(
        default=2.0, description="Minimum gap between clips"
    )
    broll_track_count: int = Field(
        default=4, description="Number of B-roll tracks in timeline"
    )

    # Download settings
    images_per_entity: int = Field(
        default=3, description="Maximum images to download per entity"
    )
    allow_non_pd: bool = Field(
        default=False, description="Include non-public-domain images"
    )
    parallel_downloads: int = Field(
        default=10, description="Number of parallel downloads"
    )

    # Disambiguation settings
    disambig_parallel: int = Field(
        default=10, description="Parallel disambiguation workers"
    )
    min_priority: float = Field(
        default=0.5, description="Minimum priority threshold"
    )

    # LLM settings
    llm: LLMConfig = Field(default_factory=LLMConfig, description="LLM configuration")

    # Pipeline control
    skip_visuals: bool = Field(
        default=False, description="Skip visual element extraction"
    )
    skip_montages: bool = Field(
        default=False, description="Skip montage detection"
    )
    min_match_quality: str = Field(
        default="high", description="Minimum match quality for timeline"
    )

    # Content settings
    subject: Optional[str] = Field(
        default=None, description="Transcript subject/context"
    )
    timeline_name: str = Field(
        default="B-Roll Timeline", description="Name for generated timeline"
    )


class PipelineStatus(BaseModel):
    """Current status of a pipeline run.

    Used by the API to report pipeline progress.
    """

    pipeline_id: str = Field(description="Unique identifier for this pipeline run")
    status: str = Field(
        description="Overall status (pending, running, completed, failed)"
    )
    current_step: Optional[PipelineStep] = Field(
        default=None, description="Currently executing step"
    )
    progress: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Overall progress 0-1"
    )
    steps_completed: List[str] = Field(
        default_factory=list, description="List of completed step names"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if failed"
    )
    output_dir: Optional[str] = Field(
        default=None, description="Output directory path"
    )
    entities_count: int = Field(
        default=0, description="Number of entities extracted"
    )
    images_downloaded: int = Field(
        default=0, description="Number of images downloaded"
    )


class PipelineRequest(BaseModel):
    """API request to start a pipeline run."""

    srt_path: str = Field(description="Path to SRT transcript file")
    config: PipelineConfig = Field(
        default_factory=PipelineConfig, description="Pipeline configuration"
    )
    resume: bool = Field(
        default=False, description="Resume from checkpoint if available"
    )
    from_step: Optional[PipelineStep] = Field(
        default=None, description="Start from specific step"
    )


class PipelineStatusResponse(BaseModel):
    """Public-facing pipeline status (excludes internal server paths).

    This is what API clients see — no output_dir or other server internals.
    """

    pipeline_id: str = Field(description="Unique identifier for this pipeline run")
    status: str = Field(
        description="Overall status (pending, running, completed, failed)"
    )
    current_step: Optional[PipelineStep] = Field(
        default=None, description="Currently executing step"
    )
    progress: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Overall progress 0-1"
    )
    steps_completed: List[str] = Field(
        default_factory=list, description="List of completed step names"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if failed"
    )
    entities_count: int = Field(
        default=0, description="Number of entities extracted"
    )
    images_downloaded: int = Field(
        default=0, description="Number of images downloaded"
    )


class ArtifactInfo(BaseModel):
    """Metadata for a downloadable pipeline artifact."""

    name: str = Field(description="Artifact identifier (e.g. 'entities_map')")
    filename: str = Field(description="Original filename (e.g. 'entities_map.json')")
    content_type: str = Field(description="MIME type (e.g. 'application/json')")
    size_bytes: int = Field(description="File size in bytes")
    download_url: str = Field(description="URL to download this artifact")


class PipelineResult(BaseModel):
    """Result of a completed pipeline run."""

    pipeline_id: str = Field(description="Unique identifier for this pipeline run")
    status: str = Field(description="Final status (completed, failed)")
    artifacts: List[ArtifactInfo] = Field(
        default_factory=list,
        description="Downloadable artifacts produced by the pipeline",
    )
    entities_count: int = Field(description="Number of entities extracted")
    images_count: int = Field(description="Number of images downloaded")
    duration_seconds: float = Field(description="Total pipeline duration")
    errors: List[str] = Field(
        default_factory=list, description="Any errors encountered"
    )
