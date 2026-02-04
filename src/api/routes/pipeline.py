"""
Pipeline API endpoints.

Provides REST access to the B-Roll pipeline for asynchronous execution.
"""
from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.core.executor import PipelineExecutor, STEPS
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


class UploadResponse(BaseModel):
    """Response when uploading an SRT file."""

    pipeline_id: str = Field(description="Unique ID for tracking this pipeline run")
    status: str = Field(description="Initial status (pending)")
    filename: str = Field(description="Original filename")
    output_dir: str = Field(description="Directory where results will be saved")
    message: str = Field(description="Status message")


# Default upload directory (can be overridden via environment variable)
UPLOAD_DIR = Path(os.environ.get("BROLL_UPLOAD_DIR", tempfile.gettempdir())) / "broll_uploads"


@router.post("/pipeline/upload", response_model=UploadResponse)
async def upload_and_start_pipeline(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="SRT subtitle file to process"),
    output_dir: str | None = Form(None, description="Output directory for results"),
) -> UploadResponse:
    """Upload an SRT file and start the pipeline.

    This endpoint accepts file uploads, making it suitable for remote clients
    that don't have filesystem access to the server.

    Args:
        file: SRT file (multipart form upload)
        output_dir: Optional output directory (defaults to temp directory)

    Returns:
        UploadResponse with pipeline_id for tracking

    Example:
        ```bash
        curl -X POST http://localhost:8001/api/v1/pipeline/upload \\
          -F "file=@my_video.srt" \\
          -F "output_dir=/path/to/output"
        ```
    """
    # Validate file extension
    if not file.filename or not file.filename.lower().endswith(".srt"):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Please upload an SRT file.",
        )

    # Generate unique pipeline ID
    pipeline_id = str(uuid.uuid4())

    # Create upload directory
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Save uploaded file with pipeline ID prefix to avoid collisions
    safe_filename = f"{pipeline_id}_{file.filename}"
    srt_path = UPLOAD_DIR / safe_filename

    try:
        content = await file.read()
        srt_path.write_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {e}")

    # Determine output directory
    if output_dir:
        output_path = Path(output_dir)
    else:
        output_path = UPLOAD_DIR / pipeline_id / "output"
    output_path.mkdir(parents=True, exist_ok=True)

    # Create config
    config = PipelineConfig(output_dir=str(output_path))

    # Initialize status
    status = PipelineStatus(
        pipeline_id=pipeline_id,
        status="pending",
        current_step=None,
        progress=0.0,
        steps_completed=[],
        output_dir=str(output_path),
    )
    _pipeline_store[pipeline_id] = status

    # Start background task
    background_tasks.add_task(
        _run_pipeline_async,
        pipeline_id=pipeline_id,
        srt_path=srt_path,
        config=config,
        from_step=None,
    )

    return UploadResponse(
        pipeline_id=pipeline_id,
        status="pending",
        filename=file.filename,
        output_dir=str(output_path),
        message=f"File uploaded and pipeline started. Track at /api/v1/pipeline/{pipeline_id}",
    )


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
    # Validate SRT file exists
    srt_path = Path(request.srt_path)
    if not srt_path.exists():
        raise HTTPException(status_code=400, detail=f"SRT file not found: {request.srt_path}")

    # Warn if resume is requested (not yet implemented)
    if request.resume:
        logging.warning("Pipeline resume is not yet implemented - starting from beginning")

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
        srt_path=srt_path,
        config=request.config,
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
    srt_path: Path,
    config: PipelineConfig,
    from_step: PipelineStep | None,
) -> None:
    """Run the pipeline asynchronously using the executor.

    Args:
        pipeline_id: Unique pipeline identifier
        srt_path: Path to SRT file
        config: Pipeline configuration
        from_step: Optional step to start from
    """
    status = _pipeline_store[pipeline_id]
    status.status = "running"

    output_dir = Path(config.output_dir) if config.output_dir else srt_path.parent / "output"

    def on_step_start(step: str):
        # Map step string to PipelineStep enum if valid
        step_values = [s.value for s in PipelineStep]
        status.current_step = PipelineStep(step) if step in step_values else None

    def on_step_complete(result):
        if result.success:
            status.steps_completed.append(result.step)
        status.progress = len(status.steps_completed) / len(STEPS)

    executor = PipelineExecutor(
        srt_path=srt_path,
        output_dir=output_dir,
        config=config.model_dump() if hasattr(config, 'model_dump') else {},
        on_step_start=on_step_start,
        on_step_complete=on_step_complete,
    )

    try:
        from_step_str = from_step.value if from_step else None
        results = await executor.run_pipeline(from_step=from_step_str)

        # Check if all steps succeeded
        if all(r.success for r in results):
            status.status = "completed"
            status.progress = 1.0
        else:
            failed = next(r for r in results if not r.success)
            status.status = "failed"
            status.error = failed.stderr or failed.error or f"Step {failed.step} failed"

    except Exception as e:
        status.status = "failed"
        status.error = str(e)
