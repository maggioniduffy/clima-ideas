from fastapi.testclient import TestClient

from clima_nqn.api.app import app


def test_health_returns_ok():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
