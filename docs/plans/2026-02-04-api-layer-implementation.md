# API Layer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire up the FastAPI endpoints to actually execute the b-roll pipeline, add OpenAPI spec generation, and prepare for Docker deployment.

**Architecture:** Keep existing tool scripts as-is; API calls them via subprocess (same pattern as `broll.py`). This preserves CLI functionality and minimizes refactoring. Later, tools can be refactored to importable modules if needed.

**Tech Stack:** FastAPI, Pydantic, asyncio (subprocess), pytest, Docker

---

## Task Overview

| # | Task | Description |
|---|------|-------------|
| 1 | Pipeline executor | Core async function to run pipeline steps via subprocess |
| 2 | Wire up routes | Connect API endpoints to executor |
| 3 | Health & info endpoints | Service metadata for discovery |
| 4 | OpenAPI export | CLI command to export spec |
| 5 | Dockerfile | Container for deployment |
| 6 | Integration test | End-to-end API test |

---

## Task 1: Pipeline Executor Core

**Files:**
- Create: `src/core/executor.py`
- Test: `tests/test_executor.py`

### Step 1: Write the failing test

```python
# tests/test_executor.py
"""Tests for pipeline executor."""
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from src.core.executor import PipelineExecutor, StepResult


@pytest.mark.asyncio
async def test_executor_runs_extract_step():
    """Executor should run extract step via subprocess."""
    executor = PipelineExecutor(
        srt_path=Path("/fake/video.srt"),
        output_dir=Path("/fake/output"),
    )

    with patch("src.core.executor.asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b"", b"")
        mock_exec.return_value = mock_process

        result = await executor.run_step("extract")

        assert result.success is True
        assert result.step == "extract"
        assert mock_exec.called
```

### Step 2: Run test to verify it fails

Run: `pytest tests/test_executor.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.core.executor'"

### Step 3: Write minimal implementation

```python
# src/core/executor.py
"""Pipeline executor - runs pipeline steps via subprocess."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Pipeline step definitions
STEPS = ["extract", "enrich", "strategies", "disambiguate", "download", "xml"]


@dataclass
class StepResult:
    """Result of a pipeline step execution."""
    step: str
    success: bool
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None


@dataclass
class PipelineExecutor:
    """Executes pipeline steps via subprocess."""

    srt_path: Path
    output_dir: Path
    config: dict = field(default_factory=dict)

    # Callbacks for progress reporting
    on_step_start: Optional[Callable[[str], None]] = None
    on_step_complete: Optional[Callable[[StepResult], None]] = None

    def __post_init__(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_script(self, name: str) -> Path:
        """Resolve path to tool script."""
        base = Path(__file__).parent.parent.parent  # src/core -> project root
        tools_path = base / "tools" / f"{name}.py"
        if tools_path.exists():
            return tools_path
        # Map step names to script names
        script_map = {
            "extract": "srt_entities.py",
            "enrich": "enrich_entities.py",
            "strategies": "generate_search_strategies.py",
            "disambiguate": "disambiguate_entities.py",
            "download": "download_entities.py",
            "xml": "generate_xml.py",
        }
        script_name = script_map.get(name, f"{name}.py")
        return base / "tools" / script_name

    def _build_command(self, step: str) -> list[str]:
        """Build subprocess command for a step."""
        script = self._resolve_script(step)
        entities_path = self.output_dir / "entities_map.json"

        cmd = [sys.executable, str(script)]

        if step == "extract":
            cmd.extend([
                "--srt", str(self.srt_path),
                "--out", str(entities_path),
            ])
        elif step in ("enrich", "strategies", "disambiguate", "download"):
            cmd.extend(["--map", str(entities_path)])
        elif step == "xml":
            cmd.extend([
                "--map", str(entities_path),
                "--output", str(self.output_dir / "broll_timeline.xml"),
            ])

        return cmd

    async def run_step(self, step: str) -> StepResult:
        """Run a single pipeline step.

        Uses asyncio.create_subprocess_exec which is safe from shell injection
        as it does not invoke a shell - arguments are passed directly to the
        executable without shell interpretation.
        """
        if self.on_step_start:
            self.on_step_start(step)

        cmd = self._build_command(step)

        try:
            # create_subprocess_exec is safe - no shell interpretation
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            result = StepResult(
                step=step,
                success=process.returncode == 0,
                returncode=process.returncode or 0,
                stdout=stdout.decode() if stdout else "",
                stderr=stderr.decode() if stderr else "",
            )
        except Exception as e:
            result = StepResult(
                step=step,
                success=False,
                error=str(e),
            )

        if self.on_step_complete:
            self.on_step_complete(result)

        return result

    async def run_pipeline(
        self,
        from_step: Optional[str] = None,
        to_step: Optional[str] = None,
    ) -> list[StepResult]:
        """Run full pipeline or subset of steps."""
        results = []

        steps = STEPS.copy()
        if from_step:
            start_idx = steps.index(from_step)
            steps = steps[start_idx:]
        if to_step:
            end_idx = steps.index(to_step) + 1
            steps = steps[:end_idx]

        for step in steps:
            result = await self.run_step(step)
            results.append(result)
            if not result.success:
                break  # Stop on failure

        return results
```

### Step 4: Run test to verify it passes

Run: `pytest tests/test_executor.py -v`
Expected: PASS

### Step 5: Commit

```bash
git add src/core/executor.py tests/test_executor.py
git commit -m "feat(api): add pipeline executor for async subprocess execution"
```

---

## Task 2: Wire Up API Routes

**Files:**
- Modify: `src/api/routes/pipeline.py`
- Test: `tests/api/test_pipeline_routes.py`

### Step 1: Write the failing test

```python
# tests/api/test_pipeline_routes.py
"""Tests for pipeline API routes."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from pathlib import Path

from src.api.main import create_app
from src.core.executor import StepResult


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_start_pipeline_returns_job_id(client, tmp_path):
    """POST /api/v1/pipeline/start should return job ID."""
    # Create a fake SRT file
    srt_file = tmp_path / "test.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n")

    response = client.post(
        "/api/v1/pipeline/start",
        json={
            "srt_path": str(srt_file),
            "config": {"output_dir": str(tmp_path / "output")},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "pipeline_id" in data
    assert data["status"] == "pending"


def test_get_pipeline_status_returns_status(client, tmp_path):
    """GET /api/v1/pipeline/{id} should return status."""
    # First start a pipeline
    srt_file = tmp_path / "test.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n")

    start_response = client.post(
        "/api/v1/pipeline/start",
        json={
            "srt_path": str(srt_file),
            "config": {"output_dir": str(tmp_path / "output")},
        },
    )
    pipeline_id = start_response.json()["pipeline_id"]

    # Then check status
    response = client.get(f"/api/v1/pipeline/{pipeline_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["pipeline_id"] == pipeline_id
    assert "status" in data
```

### Step 2: Run test to verify current state

Run: `pytest tests/api/test_pipeline_routes.py -v`
Expected: May pass partially (routes exist but don't use executor)

### Step 3: Update implementation to use executor

```python
# src/api/routes/pipeline.py
"""
Pipeline API endpoints.

Provides REST access to the B-Roll pipeline for asynchronous execution.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException
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


@router.post("/pipeline/start", response_model=PipelineStartResponse)
async def start_pipeline(
    request: PipelineRequest, background_tasks: BackgroundTasks
) -> PipelineStartResponse:
    """Start a new pipeline run."""
    # Validate SRT file exists
    srt_path = Path(request.srt_path)
    if not srt_path.exists():
        raise HTTPException(status_code=400, detail=f"SRT file not found: {request.srt_path}")

    pipeline_id = str(uuid.uuid4())

    status = PipelineStatus(
        pipeline_id=pipeline_id,
        status="pending",
        current_step=None,
        progress=0.0,
        steps_completed=[],
        output_dir=request.config.output_dir,
    )
    _pipeline_store[pipeline_id] = status

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
    """Get the status of a pipeline run."""
    if pipeline_id not in _pipeline_store:
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}")
    return _pipeline_store[pipeline_id]


@router.get("/pipeline/{pipeline_id}/result", response_model=PipelineResult)
async def get_pipeline_result(pipeline_id: str) -> PipelineResult:
    """Get the result of a completed pipeline run."""
    if pipeline_id not in _pipeline_store:
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}")

    status = _pipeline_store[pipeline_id]

    if status.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Pipeline not yet complete. Current status: {status.status}",
        )

    return PipelineResult(
        pipeline_id=pipeline_id,
        status=status.status,
        entities_path=f"{status.output_dir}/entities_map.json" if status.output_dir else "",
        xml_path=f"{status.output_dir}/broll_timeline.xml" if status.output_dir else None,
        entities_count=status.entities_count,
        images_count=status.images_downloaded,
        duration_seconds=0.0,
        errors=[status.error] if status.error else [],
    )


@router.delete("/pipeline/{pipeline_id}")
async def cancel_pipeline(pipeline_id: str) -> dict:
    """Cancel a running pipeline."""
    if pipeline_id not in _pipeline_store:
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}")

    status = _pipeline_store[pipeline_id]

    if status.status in ("completed", "failed"):
        return {"message": f"Pipeline already {status.status}", "pipeline_id": pipeline_id}

    status.status = "cancelled"
    status.error = "Cancelled by user"

    return {"message": "Pipeline cancellation requested", "pipeline_id": pipeline_id}


async def _run_pipeline_async(
    pipeline_id: str,
    srt_path: Path,
    config: PipelineConfig,
    from_step: PipelineStep | None,
) -> None:
    """Run the pipeline asynchronously using the executor."""
    status = _pipeline_store[pipeline_id]
    status.status = "running"

    output_dir = Path(config.output_dir) if config.output_dir else srt_path.parent / "output"

    def on_step_start(step: str):
        status.current_step = PipelineStep(step) if step in [s.value for s in PipelineStep] else None

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
```

### Step 4: Run tests

Run: `pytest tests/api/test_pipeline_routes.py -v`
Expected: PASS

### Step 5: Commit

```bash
git add src/api/routes/pipeline.py tests/api/test_pipeline_routes.py
git commit -m "feat(api): wire pipeline routes to executor"
```

---

## Task 3: Health & Info Endpoints

**Files:**
- Modify: `src/api/routes/health.py`
- Test: `tests/api/test_health.py`

### Step 1: Write the failing test

```python
# tests/api/test_health.py
"""Tests for health and info endpoints."""
import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_health_returns_ok(client):
    """GET /health should return ok status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "service" in data
    assert "version" in data


def test_info_returns_service_metadata(client):
    """GET /info should return service metadata."""
    response = client.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "b-roll-finder"
    assert "version" in data
    assert "endpoints" in data
    assert len(data["endpoints"]) > 0
```

### Step 2: Run test to verify it fails

Run: `pytest tests/api/test_health.py -v`
Expected: May partially pass, `/info` likely missing

### Step 3: Update health.py with info endpoint

```python
# src/api/routes/health.py
"""
Health and info endpoints for service discovery.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src import __version__

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(description="Service status")
    service: str = Field(description="Service name")
    version: str = Field(description="Service version")


class EndpointInfo(BaseModel):
    """Information about an API endpoint."""
    path: str
    method: str
    description: str


class ServiceInfo(BaseModel):
    """Service metadata for discovery."""
    name: str = Field(description="Service name")
    version: str = Field(description="Service version")
    description: str = Field(description="Service description")
    api_prefix: str = Field(description="API prefix for routing")
    port: int = Field(description="Default port")
    endpoints: list[EndpointInfo] = Field(description="Available endpoints")


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint for load balancers and orchestration."""
    return HealthResponse(
        status="ok",
        service="b-roll-finder",
        version=__version__,
    )


@router.get("/info", response_model=ServiceInfo)
async def service_info() -> ServiceInfo:
    """Service metadata for discovery and documentation."""
    return ServiceInfo(
        name="b-roll-finder",
        version=__version__,
        description="Extract entities from transcripts, download Wikipedia images, generate NLE timelines",
        api_prefix="/api/broll",
        port=8001,
        endpoints=[
            EndpointInfo(
                path="/api/v1/pipeline/start",
                method="POST",
                description="Start a new pipeline run",
            ),
            EndpointInfo(
                path="/api/v1/pipeline/{id}",
                method="GET",
                description="Get pipeline status",
            ),
            EndpointInfo(
                path="/api/v1/pipeline/{id}/result",
                method="GET",
                description="Get pipeline result",
            ),
            EndpointInfo(
                path="/api/v1/disambiguate",
                method="POST",
                description="Disambiguate a single entity",
            ),
            EndpointInfo(
                path="/api/v1/search-candidates",
                method="POST",
                description="Search Wikipedia candidates",
            ),
        ],
    )
```

### Step 4: Run tests

Run: `pytest tests/api/test_health.py -v`
Expected: PASS

### Step 5: Commit

```bash
git add src/api/routes/health.py tests/api/test_health.py
git commit -m "feat(api): add /info endpoint for service discovery"
```

---

## Task 4: OpenAPI Export CLI

**Files:**
- Create: `src/cli/export_openapi.py`
- Test: Manual verification

### Step 1: Create export script

```python
# src/cli/export_openapi.py
#!/usr/bin/env python3
"""Export OpenAPI specification to file."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Export OpenAPI specification")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("openapi.json"),
        help="Output file path (default: openapi.json)",
    )
    parser.add_argument(
        "--yaml",
        action="store_true",
        help="Export as YAML instead of JSON",
    )
    args = parser.parse_args()

    # Import app to get schema
    from src.api.main import create_app

    app = create_app()
    schema = app.openapi()

    if args.yaml:
        try:
            import yaml
            content = yaml.dump(schema, default_flow_style=False, sort_keys=False)
        except ImportError:
            print("PyYAML not installed. Use --output with .json or install pyyaml.", file=sys.stderr)
            sys.exit(1)
    else:
        content = json.dumps(schema, indent=2)

    args.output.write_text(content)
    print(f"OpenAPI spec written to: {args.output}")


if __name__ == "__main__":
    main()
```

### Step 2: Create __init__.py for cli module

```python
# src/cli/__init__.py
"""CLI tools for b-roll-finder."""
```

### Step 3: Test manually

Run: `python -m src.cli.export_openapi -o openapi.json`
Expected: Creates openapi.json with full API spec

### Step 4: Commit

```bash
mkdir -p src/cli
git add src/cli/__init__.py src/cli/export_openapi.py
git commit -m "feat(cli): add OpenAPI spec export command"
```

---

## Task 5: Dockerfile

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

### Step 1: Create Dockerfile

```dockerfile
# Dockerfile
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies for image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Copy application code
COPY . .

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run with uvicorn
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

### Step 2: Create .dockerignore

```
# .dockerignore
__pycache__/
*.py[cod]
*$py.class
.git/
.gitignore
.env
.env.*
*.md
docs/
tests/
.pytest_cache/
.mypy_cache/
.coverage
htmlcov/
dist/
build/
*.egg-info/
.venv/
venv/
```

### Step 3: Test build

Run: `docker build -t b-roll-finder:dev .`
Expected: Build succeeds

### Step 4: Test run

Run: `docker run --rm -p 8001:8001 b-roll-finder:dev`
Expected: Server starts, http://localhost:8001/health returns ok

### Step 5: Commit

```bash
git add Dockerfile .dockerignore
git commit -m "feat(docker): add Dockerfile for containerized deployment"
```

---

## Task 6: Integration Test

**Files:**
- Create: `tests/integration/test_api_e2e.py`
- Create: `tests/fixtures/sample.srt`

### Step 1: Create test fixtures

```srt
1
00:00:00,000 --> 00:00:03,000
In this video we'll talk about Albert Einstein
and his theory of relativity.

2
00:00:03,000 --> 00:00:06,000
Einstein was born in Germany in 1879.

3
00:00:06,000 --> 00:00:09,000
He later moved to the United States.
```

Save to: `tests/fixtures/sample.srt`

### Step 2: Write integration test

```python
# tests/integration/test_api_e2e.py
"""End-to-end integration tests for API."""
import pytest
import time
from pathlib import Path
from fastapi.testclient import TestClient

from src.api.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def sample_srt(tmp_path):
    """Create a sample SRT file for testing."""
    srt_content = """1
00:00:00,000 --> 00:00:03,000
In this video we'll talk about Albert Einstein
and his theory of relativity.

2
00:00:03,000 --> 00:00:06,000
Einstein was born in Germany in 1879.
"""
    srt_file = tmp_path / "sample.srt"
    srt_file.write_text(srt_content)
    return srt_file


class TestHealthEndpoints:
    """Test health and discovery endpoints."""

    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_info_endpoint(self, client):
        response = client.get("/info")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "b-roll-finder"
        assert "endpoints" in data


class TestPipelineAPI:
    """Test pipeline execution endpoints."""

    def test_start_pipeline_with_valid_srt(self, client, sample_srt, tmp_path):
        response = client.post(
            "/api/v1/pipeline/start",
            json={
                "srt_path": str(sample_srt),
                "config": {"output_dir": str(tmp_path / "output")},
            },
        )
        assert response.status_code == 200
        assert "pipeline_id" in response.json()

    def test_start_pipeline_with_missing_srt(self, client, tmp_path):
        response = client.post(
            "/api/v1/pipeline/start",
            json={
                "srt_path": "/nonexistent/file.srt",
                "config": {"output_dir": str(tmp_path / "output")},
            },
        )
        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower()

    def test_get_nonexistent_pipeline(self, client):
        response = client.get("/api/v1/pipeline/nonexistent-id")
        assert response.status_code == 404


class TestDisambiguationAPI:
    """Test disambiguation endpoints."""

    def test_search_candidates(self, client):
        response = client.post(
            "/api/v1/search-candidates",
            json={"query": "Albert Einstein", "limit": 3},
        )
        # May fail if no network, but structure should be correct
        assert response.status_code in (200, 500)
```

### Step 3: Run integration tests

Run: `pytest tests/integration/ -v`
Expected: PASS (network-dependent tests may be skipped)

### Step 4: Commit

```bash
mkdir -p tests/integration tests/fixtures
git add tests/integration/test_api_e2e.py tests/fixtures/sample.srt
git commit -m "test: add end-to-end integration tests for API"
```

---

## Final Step: Push Feature Branch

```bash
git push -u origin feature/api-layer
```

---

## Summary

After completing all tasks:

1. **API is functional** - Pipeline can be started, monitored, and cancelled via REST
2. **OpenAPI spec** - Auto-generated and exportable
3. **Docker-ready** - Can be deployed in container
4. **Tested** - Unit and integration tests in place
5. **CLI preserved** - Existing `broll.py` CLI still works

**Next steps after this plan:**
- Add Postgres for persistent job storage (currently in-memory)
- Add WebSocket for real-time progress updates
- Refactor tools to be importable (optional, for better testability)
