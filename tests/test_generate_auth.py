"""Security: /generate* must require authentication (no anonymous bodies)."""
from fastapi.testclient import TestClient

from app.main import app as fastapi_app


def test_generate_requires_auth():
    client = TestClient(fastapi_app)
    r = client.post(
        "/generate",
        json={"avatar": "gen_pop", "training_days": 3, "experience_level": "beginner"},
    )
    assert r.status_code in (401, 403)


def test_generate_and_coach_requires_auth():
    client = TestClient(fastapi_app)
    r = client.post(
        "/generate_and_coach",
        json={"avatar": "gen_pop", "training_days": 3, "experience_level": "beginner"},
    )
    assert r.status_code in (401, 403)
