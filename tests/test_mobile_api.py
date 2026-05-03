"""Tests for the mobile REST API endpoints (auth, plans, profile, checkin, progress)."""
from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.main import app as fastapi_app
from app.auth.deps import get_db, get_current_user
from app.auth.jwt import create_access_token, hash_password
from app.models import ClientProfile, WorkoutHistory


@pytest.fixture(scope="module")
def test_engine(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("data") / "test_api.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="module")
def client(test_engine):
    def _get_test_db():
        with Session(test_engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = _get_test_db
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def registered_user(client):
    resp = client.post("/api/v1/auth/register", json={
        "email": "test@beyondfit.com",
        "password": "SecurePass123",
        "name": "Test User",
    })
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture(scope="module")
def auth_headers(registered_user):
    return {"Authorization": f"Bearer {registered_user['access_token']}"}


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_register_returns_tokens(registered_user):
    assert "access_token" in registered_user
    assert "refresh_token" in registered_user
    assert registered_user["token_type"] == "bearer"


def test_register_duplicate_email_fails(client):
    resp = client.post("/api/v1/auth/register", json={
        "email": "test@beyondfit.com",
        "password": "AnotherPass",
        "name": "Dupe",
    })
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"]


def test_login_valid(client):
    resp = client.post("/api/v1/auth/login", json={
        "email": "test@beyondfit.com",
        "password": "SecurePass123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password(client):
    resp = client.post("/api/v1/auth/login", json={
        "email": "test@beyondfit.com",
        "password": "wrongpass",
    })
    assert resp.status_code == 401


def test_me_returns_profile(client, auth_headers):
    resp = client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@beyondfit.com"
    assert data["name"] == "Test User"


def test_me_without_token_fails(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 403


def test_me_bad_token_fails(client):
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer notavalidtoken"})
    assert resp.status_code == 401


# ── Plans ─────────────────────────────────────────────────────────────────────

def test_plans_current_no_plan(client, auth_headers):
    resp = client.get("/api/v1/plans/current", headers=auth_headers)
    assert resp.status_code == 404


def test_plans_today_no_plan_returns_empty(client, auth_headers):
    """No active plan should return 200 with no_plan flag, not 404."""
    resp = client.get("/api/v1/plans/today", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["no_plan"] is True
    assert data["day"] is None


def test_plans_history_empty(client, auth_headers):
    resp = client.get("/api/v1/plans/history", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.fixture(scope="module")
def seeded_plan(test_engine, registered_user):
    """Insert a fake WorkoutHistory row for the registered user."""
    plan_data = {
        "week_number": 1,
        "days": [
            {
                "day_name": "Upper",
                "slots": [
                    {
                        "slot_type": "main_compound",
                        "exercise": {"name": "Bench Press"},
                        "sets": 4,
                        "reps": 5,
                        "target_weight": 80.0,
                        "rpe": 7,
                    }
                ],
            }
        ],
    }
    with Session(test_engine) as session:
        user = session.exec(
            select(ClientProfile).where(ClientProfile.email == "test@beyondfit.com")
        ).first()
        row = WorkoutHistory(
            client_id=user.client_id,
            week_number=1,
            block_number=1,
            status="active",
            workout_json=json.dumps(plan_data),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.history_id


def test_plans_current_with_plan(client, auth_headers, seeded_plan):
    resp = client.get("/api/v1/plans/current", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["week_number"] == 1
    assert "workout" in data


def test_plans_today_with_plan(client, auth_headers, seeded_plan):
    resp = client.get("/api/v1/plans/today", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "day" in data
    assert "day_index" in data
    assert data["total_days"] == 1


def test_plans_history_with_plan(client, auth_headers, seeded_plan):
    resp = client.get("/api/v1/plans/history", headers=auth_headers)
    assert resp.status_code == 200
    history = resp.json()
    assert len(history) >= 1
    assert history[0]["week_number"] == 1


# ── Profile ───────────────────────────────────────────────────────────────────

def test_get_profile(client, auth_headers):
    resp = client.get("/api/v1/profile", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "email" in data
    assert "client_id" in data


def test_update_profile(client, auth_headers):
    resp = client.put("/api/v1/profile", headers=auth_headers, json={
        "training_days": 4,
        "experience_level": "intermediate",
        "limitations": ["lower_back_pain"],
        "available_equipment": ["full_gym"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "updated" in data
    assert set(data["updated"]) == {"training_days", "experience_level", "limitations", "available_equipment"}

    # verify changes persisted
    profile_resp = client.get("/api/v1/profile", headers=auth_headers)
    profile = profile_resp.json()
    assert profile["training_days"] == 4
    assert profile["experience_level"] == "intermediate"


# ── Progress ──────────────────────────────────────────────────────────────────

def test_progress_returns_trends(client, auth_headers, seeded_plan):
    resp = client.get("/api/v1/progress", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "rpe_trend" in data
    assert "weight_trend" in data
    assert isinstance(data["rpe_trend"], list)


# ── Plan generation (end-to-end onboarding flow) ──────────────────────────────

def test_generate_plan_for_fresh_user(test_engine):
    """A fresh user with default profile should be able to generate a first plan."""
    from app.main import app as fastapi_app
    from sqlmodel import Session
    from app.auth.deps import get_db

    def _override_db():
        with Session(test_engine) as s:
            yield s

    fastapi_app.dependency_overrides[get_db] = _override_db
    c = TestClient(fastapi_app)

    reg = c.post("/api/v1/auth/register", json={
        "email": "fresh@beyondfit.com",
        "password": "Pass12345",
        "name": "Fresh User",
    })
    assert reg.status_code == 201
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    # Update profile to set onboarding choices
    c.put("/api/v1/profile", headers=headers, json={
        "training_days": 4,
        "experience_level": "intermediate",
        "available_equipment": ["full_gym"],
        "limitations": [],
    })

    # Generate first plan
    gen = c.post("/api/v1/plans/generate", headers=headers)
    assert gen.status_code == 200, gen.text
    plan = gen.json()
    assert plan["status"] == "active"
    assert plan["week_number"] == 1
    assert len(plan["workout"]["days"]) == 4

    # Today's session now returns a real plan
    today = c.get("/api/v1/plans/today", headers=headers)
    assert today.status_code == 200
    assert today.json()["no_plan"] is False
    assert today.json()["total_days"] == 4

    fastapi_app.dependency_overrides.clear()
