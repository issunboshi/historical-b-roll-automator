"""Tests for pipeline API routes."""
import json
import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.api.routes.pipeline import _pipeline_store, UPLOAD_DIR
from src.models.pipeline import PipelineStatus


@pytest.fixture
def client():
    app = create_app()
    _pipeline_store.clear()
    return TestClient(app)


# ── Start / Status ────────────────────────────────────────────────


def test_start_pipeline_returns_job_id(client, tmp_path):
    """POST /api/v1/pipeline/start should return job ID."""
    srt_file = tmp_path / "test.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n")

    response = client.post(
        "/api/v1/pipeline/start",
        json={"srt_path": str(srt_file)},
    )

    assert response.status_code == 200
    data = response.json()
    assert "pipeline_id" in data
    assert data["status"] == "pending"


def test_get_pipeline_status_returns_status(client, tmp_path):
    """GET /api/v1/pipeline/{id} should return status without output_dir."""
    srt_file = tmp_path / "test.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n")

    start_response = client.post(
        "/api/v1/pipeline/start",
        json={"srt_path": str(srt_file)},
    )
    pipeline_id = start_response.json()["pipeline_id"]

    response = client.get(f"/api/v1/pipeline/{pipeline_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["pipeline_id"] == pipeline_id
    assert "status" in data
    # output_dir must NOT be exposed to clients
    assert "output_dir" not in data


def test_start_pipeline_with_missing_srt_returns_400(client, tmp_path):
    """POST /api/v1/pipeline/start should return 400 for missing SRT file."""
    response = client.post(
        "/api/v1/pipeline/start",
        json={"srt_path": "/nonexistent/file.srt"},
    )

    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


def test_get_nonexistent_pipeline_returns_404(client):
    """GET /api/v1/pipeline/{id} should return 404 for unknown pipeline."""
    response = client.get("/api/v1/pipeline/nonexistent-id")
    assert response.status_code == 404


# ── Upload ─────────────────────────────────────────────────────────


def test_upload_endpoint_no_output_dir(client, tmp_path):
    """POST /pipeline/upload should not accept or return output_dir."""
    srt_content = b"1\n00:00:00,000 --> 00:00:01,000\nTest\n"

    response = client.post(
        "/api/v1/pipeline/upload",
        files={"file": ("test.srt", srt_content, "application/octet-stream")},
    )

    assert response.status_code == 200
    data = response.json()
    assert "pipeline_id" in data
    assert "output_dir" not in data
    assert data["filename"] == "test.srt"


def test_upload_rejects_non_srt(client):
    """POST /pipeline/upload should reject non-SRT files."""
    response = client.post(
        "/api/v1/pipeline/upload",
        files={"file": ("test.txt", b"not an srt", "text/plain")},
    )
    assert response.status_code == 400
    assert "srt" in response.json()["detail"].lower()


# ── Result / Artifacts ─────────────────────────────────────────────


def _seed_completed_pipeline(client, tmp_path, pipeline_id="test-pipeline-123"):
    """Helper: seed a completed pipeline with artifacts on disk."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # Create known artifact files
    (output_dir / "entities_map.json").write_text(json.dumps({"entities": []}))
    (output_dir / "broll_timeline.xml").write_text("<timeline/>")

    # Create an image directory with a file
    img_dir = output_dir / "images_people"
    img_dir.mkdir()
    (img_dir / "photo.jpg").write_bytes(b"\xff\xd8fake-jpeg")

    # Seed internal store directly
    _pipeline_store[pipeline_id] = PipelineStatus(
        pipeline_id=pipeline_id,
        status="completed",
        progress=1.0,
        steps_completed=["extract", "enrich", "download", "xml"],
        output_dir=str(output_dir),
        entities_count=5,
        images_downloaded=3,
    )
    return output_dir


def test_result_returns_artifacts(client, tmp_path):
    """GET /pipeline/{id}/result should list downloadable artifacts."""
    pid = "result-test-1"
    _seed_completed_pipeline(client, tmp_path, pid)

    response = client.get(f"/api/v1/pipeline/{pid}/result")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["entities_count"] == 5
    assert data["images_count"] == 3

    names = [a["name"] for a in data["artifacts"]]
    assert "entities_map" in names
    assert "broll_timeline" in names
    assert "images" in names
    assert "all" in names

    # Each artifact should have a download_url
    for artifact in data["artifacts"]:
        assert artifact["download_url"].startswith(f"/api/v1/pipeline/{pid}/download/")


def test_result_not_ready(client, tmp_path):
    """GET /pipeline/{id}/result should 400 if pipeline still running."""
    pid = "running-1"
    _pipeline_store[pid] = PipelineStatus(
        pipeline_id=pid,
        status="running",
        output_dir=str(tmp_path),
    )
    response = client.get(f"/api/v1/pipeline/{pid}/result")
    assert response.status_code == 400


# ── Download Endpoints ─────────────────────────────────────────────


def test_download_individual_artifact(client, tmp_path):
    """GET /pipeline/{id}/download/{name} should serve the file."""
    pid = "dl-test-1"
    _seed_completed_pipeline(client, tmp_path, pid)

    response = client.get(f"/api/v1/pipeline/{pid}/download/entities_map")

    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    body = response.json()
    assert "entities" in body


def test_download_xml_artifact(client, tmp_path):
    """GET /pipeline/{id}/download/broll_timeline should serve XML."""
    pid = "dl-test-2"
    _seed_completed_pipeline(client, tmp_path, pid)

    response = client.get(f"/api/v1/pipeline/{pid}/download/broll_timeline")

    assert response.status_code == 200
    assert "<timeline/>" in response.text


def test_download_unknown_artifact_404(client, tmp_path):
    """GET /pipeline/{id}/download/{unknown} should 404."""
    pid = "dl-test-3"
    _seed_completed_pipeline(client, tmp_path, pid)

    response = client.get(f"/api/v1/pipeline/{pid}/download/nonexistent")
    assert response.status_code == 404


def test_download_images_zip(client, tmp_path):
    """GET /pipeline/{id}/download/images should return a zip."""
    pid = "dl-test-4"
    _seed_completed_pipeline(client, tmp_path, pid)

    response = client.get(f"/api/v1/pipeline/{pid}/download/images")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    # Zip files start with PK magic bytes
    assert response.content[:2] == b"PK"


def test_download_all_zip(client, tmp_path):
    """GET /pipeline/{id}/download/all should return a zip of everything."""
    pid = "dl-test-5"
    _seed_completed_pipeline(client, tmp_path, pid)

    response = client.get(f"/api/v1/pipeline/{pid}/download/all")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.content[:2] == b"PK"


def test_download_nonexistent_pipeline_404(client):
    """Download from unknown pipeline should 404."""
    response = client.get("/api/v1/pipeline/no-such-id/download/entities_map")
    assert response.status_code == 404
