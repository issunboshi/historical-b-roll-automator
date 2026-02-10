"""Tests for pipeline API routes."""
import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app


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


def test_start_pipeline_with_missing_srt_returns_400(client, tmp_path):
    """POST /api/v1/pipeline/start should return 400 for missing SRT file."""
    response = client.post(
        "/api/v1/pipeline/start",
        json={
            "srt_path": "/nonexistent/file.srt",
            "config": {"output_dir": str(tmp_path / "output")},
        },
    )

    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


def test_get_nonexistent_pipeline_returns_404(client):
    """GET /api/v1/pipeline/{id} should return 404 for unknown pipeline."""
    response = client.get("/api/v1/pipeline/nonexistent-id")
    assert response.status_code == 404
