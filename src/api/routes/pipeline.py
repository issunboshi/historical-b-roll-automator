"""
Pipeline API endpoints.

Provides REST access to the B-Roll pipeline for asynchronous execution.
"""
from __future__ import annotations

import uuid
from typing import Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from src.models.pipeline import (
    PipelineConfig,
    PipelineRequest,
    PipelineResult,
    PipelineStatus,
    PipelineStep,
)

router = APIRouter()

# In-memory storage for pipeline status (would use Redis/DB in production)
_pipeline_store: Dict[str, PipelineStatus] = {}


class PipelineStartResponse(BaseModel):
    """Response when starting a pipeline."""

    pipeline_id: str = Field(description="Unique ID for tracking this pipeline run")
    status: str = Field(description="Initial status (pending)")
    message: str = Field(description="Status message")


@router.post("/pipeline/start", response_model=PipelineStartResponse)
async def start_pipeline(
    request: PipelineRequest, background_tasks: BackgroundTasks
) -> PipelineStartResponse:
    """Start a new pipeline run.

    The pipeline runs asynchronously in the background. Use the returned
    pipeline_id to check status and retrieve results.

    Args:
        request: PipelineRequest with SRT path and configuration

    Returns:
        PipelineStartResponse with pipeline_id for tracking
    """
    # Generate unique pipeline ID
    pipeline_id = str(uuid.uuid4())

    # Initialize status
    status = PipelineStatus(
        pipeline_id=pipeline_id,
        status="pending",
        current_step=None,
        progress=0.0,
        steps_completed=[],
        output_dir=request.config.output_dir,
    )
    _pipeline_store[pipeline_id] = status

    # Start background task
    background_tasks.add_task(
        _run_pipeline_async,
        pipeline_id=pipeline_id,
        srt_path=request.srt_path,
        config=request.config,
        resume=request.resume,
        from_step=request.from_step,
    )

    return PipelineStartResponse(
        pipeline_id=pipeline_id,
        status="pending",
        message=f"Pipeline started. Track status at /api/v1/pipeline/{pipeline_id}",
    )


@router.get("/pipeline/{pipeline_id}", response_model=PipelineStatus)
async def get_pipeline_status(pipeline_id: str) -> PipelineStatus:
    """Get the status of a pipeline run.

    Args:
        pipeline_id: ID returned from start_pipeline

    Returns:
        Current pipeline status

    Raises:
        HTTPException: If pipeline_id not found
    """
    if pipeline_id not in _pipeline_store:
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}")

    return _pipeline_store[pipeline_id]


@router.get("/pipeline/{pipeline_id}/result", response_model=PipelineResult)
async def get_pipeline_result(pipeline_id: str) -> PipelineResult:
    """Get the result of a completed pipeline run.

    Args:
        pipeline_id: ID returned from start_pipeline

    Returns:
        Pipeline result with output paths and statistics

    Raises:
        HTTPException: If pipeline not found or not yet complete
    """
    if pipeline_id not in _pipeline_store:
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}")

    status = _pipeline_store[pipeline_id]

    if status.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Pipeline not yet complete. Current status: {status.status}",
        )

    # Build result from stored status
    return PipelineResult(
        pipeline_id=pipeline_id,
        status=status.status,
        entities_path=f"{status.output_dir}/entities_map.json" if status.output_dir else "",
        xml_path=f"{status.output_dir}/broll_timeline.xml" if status.output_dir else None,
        entities_count=status.entities_count,
        images_count=status.images_downloaded,
        duration_seconds=0.0,  # Would track actual duration
        errors=[status.error] if status.error else [],
    )


@router.delete("/pipeline/{pipeline_id}")
async def cancel_pipeline(pipeline_id: str) -> dict:
    """Cancel a running pipeline.

    Args:
        pipeline_id: ID of pipeline to cancel

    Returns:
        Confirmation message

    Raises:
        HTTPException: If pipeline not found
    """
    if pipeline_id not in _pipeline_store:
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}")

    status = _pipeline_store[pipeline_id]

    if status.status in ("completed", "failed"):
        return {"message": f"Pipeline already {status.status}", "pipeline_id": pipeline_id}

    # Mark as cancelled (actual cancellation would need task coordination)
    status.status = "cancelled"
    status.error = "Cancelled by user"

    return {"message": "Pipeline cancellation requested", "pipeline_id": pipeline_id}


async def _run_pipeline_async(
    pipeline_id: str,
    srt_path: str,
    config: PipelineConfig,
    resume: bool,
    from_step: PipelineStep | None,
) -> None:
    """Run the pipeline asynchronously.

    This is a placeholder that demonstrates the async pattern.
    Full implementation would call the actual pipeline steps.

    Args:
        pipeline_id: Unique pipeline identifier
        srt_path: Path to SRT file
        config: Pipeline configuration
        resume: Whether to resume from checkpoint
        from_step: Optional step to start from
    """
    status = _pipeline_store[pipeline_id]
    status.status = "running"

    try:
        # TODO: Implement actual pipeline execution
        # This would call the core pipeline functions

        steps = [
            PipelineStep.EXTRACT,
            PipelineStep.ENRICH,
            PipelineStep.STRATEGIES,
            PipelineStep.DISAMBIGUATE,
            PipelineStep.DOWNLOAD,
            PipelineStep.XML,
        ]

        for i, step in enumerate(steps):
            if status.status == "cancelled":
                break

            status.current_step = step
            status.progress = (i + 1) / len(steps)

            # Simulate step execution (replace with actual implementation)
            # await asyncio.sleep(1)

            status.steps_completed.append(step.value)

        if status.status != "cancelled":
            status.status = "completed"
            status.progress = 1.0

    except Exception as e:
        status.status = "failed"
        status.error = str(e)
