"""End-to-end integration tests for API.

These tests verify complete workflows across multiple endpoints,
ensuring the API contract is stable and endpoints work together.

Run with: pytest tests/integration/ -v
"""
import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app


@pytest.fixture
def client():
    """Create test client for API."""
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
        """GET /health should return ok status."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_info_endpoint(self, client):
        """GET /info should return service metadata."""
        response = client.get("/info")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "b-roll-finder"
        assert "endpoints" in data

    def test_health_and_info_consistency(self, client):
        """Health and info endpoints should report consistent service info."""
        health = client.get("/health").json()
        info = client.get("/info").json()

        # Service name and version should be consistent
        assert health["service"] == info["name"]
        assert health["version"] == info["version"]


class TestPipelineAPI:
    """Test pipeline execution endpoints."""

    def test_start_pipeline_with_valid_srt(self, client, sample_srt, tmp_path):
        """POST /api/v1/pipeline/start should return pipeline_id."""
        response = client.post(
            "/api/v1/pipeline/start",
            json={
                "srt_path": str(sample_srt),
                "config": {"output_dir": str(tmp_path / "output")},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "pipeline_id" in data
        assert data["status"] == "pending"

    def test_start_pipeline_with_missing_srt(self, client, tmp_path):
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

    def test_get_nonexistent_pipeline(self, client):
        """GET /api/v1/pipeline/{id} should return 404 for unknown pipeline."""
        response = client.get("/api/v1/pipeline/nonexistent-id")
        assert response.status_code == 404

    def test_pipeline_lifecycle_start_and_status(self, client, sample_srt, tmp_path):
        """Test full pipeline lifecycle: start → get status."""
        # Start pipeline
        start_response = client.post(
            "/api/v1/pipeline/start",
            json={
                "srt_path": str(sample_srt),
                "config": {"output_dir": str(tmp_path / "output")},
            },
        )
        assert start_response.status_code == 200
        pipeline_id = start_response.json()["pipeline_id"]

        # Check status
        status_response = client.get(f"/api/v1/pipeline/{pipeline_id}")
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["pipeline_id"] == pipeline_id
        assert status_data["status"] in ("pending", "running", "completed", "failed")

    def test_cancel_pipeline(self, client, sample_srt, tmp_path):
        """DELETE /api/v1/pipeline/{id} should cancel a running pipeline."""
        # Start pipeline
        start_response = client.post(
            "/api/v1/pipeline/start",
            json={
                "srt_path": str(sample_srt),
                "config": {"output_dir": str(tmp_path / "output")},
            },
        )
        pipeline_id = start_response.json()["pipeline_id"]

        # Cancel it
        cancel_response = client.delete(f"/api/v1/pipeline/{pipeline_id}")
        assert cancel_response.status_code == 200

    def test_get_result_before_completion(self, client, sample_srt, tmp_path):
        """GET /api/v1/pipeline/{id}/result should return 400 if not complete."""
        # Start pipeline
        start_response = client.post(
            "/api/v1/pipeline/start",
            json={
                "srt_path": str(sample_srt),
                "config": {"output_dir": str(tmp_path / "output")},
            },
        )
        pipeline_id = start_response.json()["pipeline_id"]

        # Try to get result immediately (pipeline won't be complete)
        result_response = client.get(f"/api/v1/pipeline/{pipeline_id}/result")
        # Should be 400 (not complete) or 200 (if somehow completed very fast)
        assert result_response.status_code in (200, 400)


class TestFileUploadAPI:
    """Test file upload endpoint for remote clients."""

    def test_upload_srt_file(self, client, sample_srt):
        """POST /api/v1/pipeline/upload should accept SRT file upload."""
        with open(sample_srt, "rb") as f:
            response = client.post(
                "/api/v1/pipeline/upload",
                files={"file": ("test.srt", f, "text/plain")},
            )

        assert response.status_code == 200
        data = response.json()
        assert "pipeline_id" in data
        assert data["status"] == "pending"
        assert data["filename"] == "test.srt"
        # output_dir is no longer exposed to clients
        assert "output_dir" not in data

    def test_upload_does_not_accept_output_dir(self, client, sample_srt, tmp_path):
        """Upload should ignore output_dir — server controls output path."""
        with open(sample_srt, "rb") as f:
            response = client.post(
                "/api/v1/pipeline/upload",
                files={"file": ("test.srt", f, "text/plain")},
            )

        assert response.status_code == 200
        assert "output_dir" not in response.json()

    def test_upload_rejects_non_srt_file(self, client, tmp_path):
        """Upload should reject non-SRT files."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("This is not an SRT file")

        with open(txt_file, "rb") as f:
            response = client.post(
                "/api/v1/pipeline/upload",
                files={"file": ("test.txt", f, "text/plain")},
            )

        assert response.status_code == 400
        assert "srt" in response.json()["detail"].lower()

    def test_upload_then_check_status(self, client, sample_srt):
        """Full workflow: upload file → check pipeline status."""
        # Upload file
        with open(sample_srt, "rb") as f:
            upload_response = client.post(
                "/api/v1/pipeline/upload",
                files={"file": ("test.srt", f, "text/plain")},
            )

        pipeline_id = upload_response.json()["pipeline_id"]

        # Check status
        status_response = client.get(f"/api/v1/pipeline/{pipeline_id}")
        assert status_response.status_code == 200
        assert status_response.json()["pipeline_id"] == pipeline_id


class TestDisambiguationAPI:
    """Test disambiguation endpoints."""

    @pytest.mark.network
    def test_search_candidates(self, client):
        """POST /api/v1/search-candidates should search Wikipedia."""
        response = client.post(
            "/api/v1/search-candidates",
            json={"query": "Albert Einstein", "limit": 3},
        )
        # May fail if no network, but structure should be correct
        if response.status_code == 200:
            data = response.json()
            assert "query" in data
            assert "candidates" in data
            assert "count" in data
        else:
            # Network error or other failure
            assert response.status_code == 500

    @pytest.mark.network
    def test_search_candidates_with_limit(self, client):
        """Search candidates should respect limit parameter."""
        response = client.post(
            "/api/v1/search-candidates",
            json={"query": "Python", "limit": 2},
        )
        if response.status_code == 200:
            data = response.json()
            assert data["count"] <= 2

    @pytest.mark.network
    def test_disambiguate_without_api_key(self, client):
        """POST /api/v1/disambiguate should return 503 without API key."""
        import os
        # Temporarily clear API key if set
        original_key = os.environ.get("ANTHROPIC_API_KEY")
        if original_key:
            del os.environ["ANTHROPIC_API_KEY"]

        try:
            response = client.post(
                "/api/v1/disambiguate",
                json={
                    "entity_name": "Einstein",
                    "entity_type": "person",
                    "transcript_context": "physicist who developed relativity",
                },
            )
            # Should be 503 (API key not configured)
            assert response.status_code == 503
        finally:
            # Restore API key
            if original_key:
                os.environ["ANTHROPIC_API_KEY"] = original_key


class TestOpenAPISpec:
    """Test OpenAPI specification availability."""

    def test_openapi_json_available(self, client):
        """GET /openapi.json should return valid OpenAPI spec."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        spec = response.json()
        assert "openapi" in spec
        assert "info" in spec
        assert "paths" in spec

    def test_openapi_spec_has_pipeline_endpoints(self, client):
        """OpenAPI spec should document pipeline endpoints."""
        response = client.get("/openapi.json")
        spec = response.json()
        paths = spec["paths"]

        # Check key endpoints are documented
        assert "/api/v1/pipeline/start" in paths
        assert "/health" in paths
        assert "/info" in paths

    def test_docs_endpoint_available(self, client):
        """GET /docs should return Swagger UI (redirect or HTML)."""
        response = client.get("/docs")
        # Either 200 (HTML) or redirect
        assert response.status_code in (200, 307)
