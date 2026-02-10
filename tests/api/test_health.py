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


def test_detailed_health_returns_environment_info(client):
    """GET /health/detailed should return detailed health with environment info."""
    response = client.get("/health/detailed")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data
    assert "environment" in data


def test_ready_returns_readiness_status(client):
    """GET /ready should return readiness status."""
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert "ready" in data
    assert "checks" in data
