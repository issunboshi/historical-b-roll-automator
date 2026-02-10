"""
Pipeline API endpoints.

Provides REST access to the B-Roll pipeline for asynchronous execution.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from src.core.executor import PipelineExecutor, STEPS
from src.models.pipeline import (
    ArtifactInfo,
    PipelineConfig,
    PipelineRequest,
    PipelineResult,
    PipelineStatus,
    PipelineStatusResponse,
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
    message: str = Field(description="Status message")


# Default upload directory (can be overridden via environment variable)
UPLOAD_DIR = Path(os.environ.get("BROLL_UPLOAD_DIR", tempfile.gettempdir())) / "broll_uploads"


@router.post("/pipeline/upload", response_model=UploadResponse)
async def upload_and_start_pipeline(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="SRT subtitle file to process"),
) -> UploadResponse:
    """Upload an SRT file and start the pipeline.

    This endpoint accepts file uploads, making it suitable for remote clients
    that don't have filesystem access to the server. Results are retrieved via
    the download endpoints.

    Args:
        file: SRT file (multipart form upload)

    Returns:
        UploadResponse with pipeline_id for tracking

    Example:
        ```bash
        curl -X POST http://localhost:8001/api/v1/pipeline/upload \\
          -F "file=@my_video.srt"
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

    # Server always controls the output directory
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


@router.get("/pipeline/{pipeline_id}", response_model=PipelineStatusResponse)
async def get_pipeline_status(pipeline_id: str) -> PipelineStatusResponse:
    """Get the status of a pipeline run.

    Args:
        pipeline_id: ID returned from start_pipeline

    Returns:
        Current pipeline status (excludes internal server paths)

    Raises:
        HTTPException: If pipeline_id not found
    """
    if pipeline_id not in _pipeline_store:
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}")

    internal = _pipeline_store[pipeline_id]
    return PipelineStatusResponse(
        pipeline_id=internal.pipeline_id,
        status=internal.status,
        current_step=internal.current_step,
        progress=internal.progress,
        steps_completed=internal.steps_completed,
        error=internal.error,
        entities_count=internal.entities_count,
        images_downloaded=internal.images_downloaded,
    )


@router.get("/pipeline/{pipeline_id}/result", response_model=PipelineResult)
async def get_pipeline_result(pipeline_id: str) -> PipelineResult:
    """Get the result of a completed pipeline run.

    Returns artifact metadata with download URLs instead of server paths.

    Args:
        pipeline_id: ID returned from start_pipeline

    Returns:
        Pipeline result with downloadable artifacts and statistics

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

    # Scan output directory for known artifacts
    artifacts: list[ArtifactInfo] = []
    output_dir = Path(status.output_dir) if status.output_dir else None

    if output_dir and output_dir.is_dir():
        known_files = [
            "entities_map.json",
            "broll_timeline.xml",
            "visual_elements.json",
            "strategies_entities.json",
        ]
        for filename in known_files:
            filepath = output_dir / filename
            if filepath.is_file():
                content_type = (
                    mimetypes.guess_type(filename)[0] or "application/octet-stream"
                )
                name = filepath.stem  # e.g. "entities_map"
                artifacts.append(
                    ArtifactInfo(
                        name=name,
                        filename=filename,
                        content_type=content_type,
                        size_bytes=filepath.stat().st_size,
                        download_url=f"/api/v1/pipeline/{pipeline_id}/download/{name}",
                    )
                )

        # Check for image directories
        has_images = any(
            d.is_dir() and any(d.iterdir()) for d in output_dir.iterdir() if d.is_dir()
        )
        if has_images:
            artifacts.append(
                ArtifactInfo(
                    name="images",
                    filename="images.zip",
                    content_type="application/zip",
                    size_bytes=0,  # computed on-the-fly during download
                    download_url=f"/api/v1/pipeline/{pipeline_id}/download/images",
                )
            )

        # Always add an "all" zip for the complete output
        artifacts.append(
            ArtifactInfo(
                name="all",
                filename="output.zip",
                content_type="application/zip",
                size_bytes=0,
                download_url=f"/api/v1/pipeline/{pipeline_id}/download/all",
            )
        )

    return PipelineResult(
        pipeline_id=pipeline_id,
        status=status.status,
        artifacts=artifacts,
        entities_count=status.entities_count,
        images_count=status.images_downloaded,
        duration_seconds=0.0,  # Would track actual duration
        errors=[status.error] if status.error else [],
    )


def _get_output_dir(pipeline_id: str) -> Path:
    """Resolve and validate the output directory for a pipeline."""
    if pipeline_id not in _pipeline_store:
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}")
    status = _pipeline_store[pipeline_id]
    if not status.output_dir:
        raise HTTPException(status_code=404, detail="No output directory for this pipeline")
    output_dir = Path(status.output_dir)
    if not output_dir.is_dir():
        raise HTTPException(status_code=404, detail="Output directory not found on server")
    return output_dir


# Map artifact names to filenames for individual file downloads
_ARTIFACT_FILENAMES: dict[str, str] = {
    "entities_map": "entities_map.json",
    "broll_timeline": "broll_timeline.xml",
    "visual_elements": "visual_elements.json",
    "strategies_entities": "strategies_entities.json",
}


@router.get("/pipeline/{pipeline_id}/download/{artifact_name}")
async def download_artifact(pipeline_id: str, artifact_name: str) -> FileResponse:
    """Download a single pipeline artifact.

    Args:
        pipeline_id: Pipeline identifier
        artifact_name: Artifact name (e.g. 'entities_map', 'broll_timeline')

    Returns:
        The artifact file

    Raises:
        HTTPException: If pipeline or artifact not found
    """
    # Route images and all to their dedicated handlers
    if artifact_name == "images":
        return await download_images_zip(pipeline_id)
    if artifact_name == "all":
        return await download_all_zip(pipeline_id)

    output_dir = _get_output_dir(pipeline_id)

    filename = _ARTIFACT_FILENAMES.get(artifact_name)
    if not filename:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown artifact: {artifact_name}. "
            f"Available: {', '.join(_ARTIFACT_FILENAMES)}",
        )

    filepath = output_dir / filename
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {filename}")

    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(path=filepath, filename=filename, media_type=content_type)


@router.get("/pipeline/{pipeline_id}/download/images")
async def download_images_zip(pipeline_id: str) -> StreamingResponse:
    """Download all pipeline images as a zip archive.

    Streams a zip of all image subdirectories in the output folder.
    Uses a temp file on disk to avoid high memory usage.

    Args:
        pipeline_id: Pipeline identifier

    Returns:
        Zip archive of all image directories
    """
    output_dir = _get_output_dir(pipeline_id)

    # Collect image directories (any subdirectory with files)
    image_dirs = [d for d in output_dir.iterdir() if d.is_dir() and any(d.iterdir())]
    if not image_dirs:
        raise HTTPException(status_code=404, detail="No images found for this pipeline")

    return _stream_zip(image_dirs, f"{pipeline_id}_images.zip")


@router.get("/pipeline/{pipeline_id}/download/all")
async def download_all_zip(pipeline_id: str) -> StreamingResponse:
    """Download the entire output directory as a zip archive.

    Streams a zip of all files and subdirectories in the output folder.
    Uses a temp file on disk to avoid high memory usage.

    Args:
        pipeline_id: Pipeline identifier

    Returns:
        Zip archive of the complete output directory
    """
    output_dir = _get_output_dir(pipeline_id)
    return _stream_zip([output_dir], f"{pipeline_id}_output.zip", base_dir=output_dir)


def _stream_zip(
    paths: list[Path],
    zip_filename: str,
    base_dir: Path | None = None,
) -> StreamingResponse:
    """Create a zip file on disk and stream it back.

    Uses a temp file instead of in-memory buffer to stay within
    Fly.io's 512MB RAM constraint.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in paths:
                if path.is_file():
                    arcname = path.name if not base_dir else path.relative_to(base_dir)
                    zf.write(path, arcname)
                elif path.is_dir():
                    for file in path.rglob("*"):
                        if file.is_file():
                            if base_dir:
                                arcname = file.relative_to(base_dir)
                            else:
                                arcname = Path(path.name) / file.relative_to(path)
                            zf.write(file, arcname)
        tmp.close()

        def iter_file():
            try:
                with open(tmp.name, "rb") as f:
                    while chunk := f.read(65536):
                        yield chunk
            finally:
                os.unlink(tmp.name)

        return StreamingResponse(
            iter_file(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
        )
    except Exception:
        tmp.close()
        os.unlink(tmp.name)
        raise


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
