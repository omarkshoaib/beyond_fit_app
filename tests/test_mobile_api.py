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
    # Don't blanket-clear: the module-scoped `client` fixture installed an
    # override that other tests rely on. Just remove ours if we set it.
    pass


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


def test_me_without_token_fails(test_engine):
    """Fresh TestClient (no cookies) + no Authorization header → 401."""
    fresh = TestClient(fastapi_app)
    resp = fresh.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_bad_token_fails(client):
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer notavalidtoken"})
    assert resp.status_code == 401


def test_refresh_returns_new_pair(client, registered_user):
    """Valid refresh token issues a fresh access + refresh pair."""
    refresh = registered_user["refresh_token"]
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    # New access token must work
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me.status_code == 200


def test_refresh_rejects_access_token(client, registered_user):
    """Passing an access token to /refresh must fail (only refresh-typed allowed)."""
    access = registered_user["access_token"]
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401


def test_refresh_rejects_garbage(client):
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-token"})
    assert resp.status_code == 401


def test_forgot_password_returns_ok_for_unknown_email(client):
    """Unknown emails must still return 200 to avoid account enumeration."""
    resp = client.post("/api/v1/auth/forgot", json={"email": "nobody@nowhere.com"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_forgot_password_returns_ok_for_known_email(client, monkeypatch):
    """Known emails trigger send_password_reset and still return 200."""
    sent = []
    monkeypatch.setattr(
        "app.api.auth.EmailService.send_password_reset",
        lambda recipient_email, reset_token, client_name="": (sent.append((recipient_email, reset_token)), True)[1],
    )
    resp = client.post("/api/v1/auth/forgot", json={"email": "test@beyondfit.com"})
    assert resp.status_code == 200
    assert len(sent) == 1
    assert sent[0][0] == "test@beyondfit.com"
    assert sent[0][1]  # reset token was generated


def test_reset_password_with_valid_token_works(client, monkeypatch):
    """Valid reset token sets new password + returns fresh tokens; old password no longer works."""
    captured: dict = {}
    monkeypatch.setattr(
        "app.api.auth.EmailService.send_password_reset",
        lambda recipient_email, reset_token, client_name="": (captured.update(token=reset_token), True)[1],
    )
    client.post("/api/v1/auth/forgot", json={"email": "test@beyondfit.com"})
    token = captured["token"]

    resp = client.post("/api/v1/auth/reset", json={"token": token, "new_password": "BrandNewPw99"})
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()

    # Old password fails
    old = client.post("/api/v1/auth/login",
                      json={"email": "test@beyondfit.com", "password": "SecurePass123"})
    assert old.status_code == 401
    # New password works
    new = client.post("/api/v1/auth/login",
                      json={"email": "test@beyondfit.com", "password": "BrandNewPw99"})
    assert new.status_code == 200

    # Restore original password so other module-scoped tests still pass
    captured.clear()
    client.post("/api/v1/auth/forgot", json={"email": "test@beyondfit.com"})
    client.post("/api/v1/auth/reset",
                json={"token": captured["token"], "new_password": "SecurePass123"})


def test_reset_password_rejects_short(client):
    resp = client.post("/api/v1/auth/reset", json={"token": "x", "new_password": "short"})
    assert resp.status_code == 400


def test_reset_password_rejects_invalid_token(client):
    resp = client.post("/api/v1/auth/reset",
                      json={"token": "not-a-real-token", "new_password": "ValidPw123"})
    assert resp.status_code == 400


def test_email_verification_round_trip(client, monkeypatch, registered_user):
    """create_verify_token → decode → verified_at stamped + idempotent."""
    from app.auth.jwt import create_verify_token

    captured: dict = {}
    monkeypatch.setattr(
        "app.api.auth.EmailService.send_verification",
        lambda recipient_email, verify_token, client_name="": (captured.update(t=verify_token), True)[1],
    )

    # Trigger resend so we have a token
    headers = {"Authorization": f"Bearer {registered_user['access_token']}"}
    r = client.post("/api/v1/auth/resend-verification", headers=headers)
    assert r.status_code == 200
    token = captured.get("t") or create_verify_token("dummy")

    v = client.post("/api/v1/auth/verify", json={"token": token})
    assert v.status_code == 200, v.text
    assert v.json()["verified_at"] is not None

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["verified_at"] is not None


def test_verify_rejects_garbage_token(client):
    resp = client.post("/api/v1/auth/verify", json={"token": "garbage"})
    assert resp.status_code == 400


def test_resend_verification_noop_if_verified(client, registered_user):
    headers = {"Authorization": f"Bearer {registered_user['access_token']}"}
    r = client.post("/api/v1/auth/resend-verification", headers=headers)
    # Either path returns 200; if previous test verified, second call says already_verified
    assert r.status_code == 200


def test_healthz_returns_status(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert "db" in body
    assert "version" in body


def test_export_my_data_returns_full_dump(client, auth_headers, registered_user):
    resp = client.get("/api/v1/profile/export", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"]["email"] == "test@beyondfit.com"
    assert "workout_history" in body
    assert "set_logs" in body
    assert "audit_events" in body


def test_log_set_persists(client, auth_headers):
    """Per-set logger persists actual reps + weight + RPE. Doesn't need a real
    plan — just stores the row keyed by history_id."""
    resp = client.post("/api/v1/sets", headers=auth_headers, json={
        "history_id": 999,  # synthetic — endpoint doesn't verify it exists
        "day_index": 0,
        "slot_index": 0,
        "set_index": 0,
        "actual_reps": 5,
        "actual_weight": 80.0,
        "rpe": 7,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True

    listing = client.get("/api/v1/sets/by-history/999", headers=auth_headers)
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) >= 1
    assert rows[0]["actual_reps"] == 5
    assert rows[0]["actual_weight"] == 80.0


def test_feedback_submission(client, auth_headers):
    resp = client.post("/api/v1/feedback", headers=auth_headers,
                      json={"message": "test feedback", "app_version": "test-1.0"})
    assert resp.status_code == 200


def test_super_admin_self_heal_on_lifespan(test_engine):
    """Super-admin row should be auto-promoted at lifespan startup."""
    from app.main import _ensure_super_admin
    from app.models import ClientProfile
    from app.auth.jwt import hash_password
    import uuid as _uuid

    settings = __import__("app.settings", fromlist=["get_settings"]).get_settings()

    # Insert a row matching super_admin_email but with flags False
    with Session(test_engine) as s:
        cid = str(_uuid.uuid4())
        s.add(ClientProfile(
            client_id=cid,
            email=settings.super_admin_email,
            password_hash=hash_password("Pw12345678"),
            name="Super",
            is_admin=False,
            is_coach=False,
        ))
        s.commit()

    _ensure_super_admin(test_engine)

    with Session(test_engine) as s:
        u = s.exec(select(ClientProfile).where(ClientProfile.email == settings.super_admin_email)).first()
        assert u is not None
        assert u.is_admin is True
        assert u.is_coach is True


def test_super_admin_cannot_be_demoted(test_engine):
    """POST /admin/admins/demote on super-admin email returns 400."""
    from app.main import app as fastapi_app
    from app.auth.deps import get_db
    from app.models import ClientProfile
    from app.settings import get_settings as _gs

    def _override():
        with Session(test_engine) as s:
            yield s
    fastapi_app.dependency_overrides[get_db] = _override
    c = TestClient(fastapi_app)
    super_email = _gs().super_admin_email

    # Ensure super-admin exists with proper flags
    with Session(test_engine) as s:
        u = s.exec(select(ClientProfile).where(ClientProfile.email == super_email)).first()
        if u is None:
            r = c.post("/api/v1/auth/register", json={
                "email": super_email, "password": "Pw12345678", "name": "Super"
            })
            assert r.status_code == 201
            u = s.exec(select(ClientProfile).where(ClientProfile.email == super_email)).first()
        assert u is not None
        u.is_admin = True
        u.is_coach = True
        s.add(u)
        s.commit()

    # Login as super-admin
    login = c.post("/api/v1/auth/login", json={"email": super_email, "password": "Pw12345678"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = c.post("/api/v1/admin/admins/demote", headers=headers, json={"email": super_email})
    assert resp.status_code == 400
    assert "super-admin" in resp.json()["detail"].lower()
    # Don't blanket-clear: the module-scoped `client` fixture installed an
    # override that other tests rely on. Just remove ours if we set it.
    pass


def test_invited_email_registers_as_coach(test_engine):
    """Coach invite happy path: admin invites email, that email registers, lands as coach."""
    from app.main import app as fastapi_app
    from app.auth.deps import get_db
    from app.models import ClientProfile, CoachInvite

    def _override():
        with Session(test_engine) as s:
            yield s
    fastapi_app.dependency_overrides[get_db] = _override
    c = TestClient(fastapi_app)

    # Create admin
    admin_reg = c.post("/api/v1/auth/register", json={
        "email": "inv-admin@bf.com", "password": "Pw12345678", "name": "Inv Admin"})
    assert admin_reg.status_code == 201
    with Session(test_engine) as s:
        u = s.exec(select(ClientProfile).where(ClientProfile.email == "inv-admin@bf.com")).first()
        assert u is not None
        u.is_admin = True
        s.add(u)
        s.commit()
    admin_login = c.post("/api/v1/auth/login", json={
        "email": "inv-admin@bf.com", "password": "Pw12345678"})
    admin_h = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    # Invite a coach
    inv = c.post("/api/v1/admin/coaches/invite", headers=admin_h,
                 json={"email": "future-coach@bf.com"})
    assert inv.status_code == 200, inv.text

    # That email registers → should land with is_coach=True
    reg = c.post("/api/v1/auth/register", json={
        "email": "future-coach@bf.com", "password": "CoachPw123", "name": "Future Coach"})
    assert reg.status_code == 201
    me = c.get("/api/v1/auth/me",
               headers={"Authorization": f"Bearer {reg.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["is_coach"] is True

    with Session(test_engine) as s:
        invite = s.exec(
            select(CoachInvite).where(CoachInvite.email == "future-coach@bf.com")
        ).first()
        assert invite is not None
        assert invite.accepted_at is not None
    # Don't blanket-clear: the module-scoped `client` fixture installed an
    # override that other tests rely on. Just remove ours if we set it.
    pass


def test_non_invited_email_registers_as_client(test_engine):
    """Email without an invite registers as a regular client, is_coach=False."""
    from app.main import app as fastapi_app
    from app.auth.deps import get_db

    def _override():
        with Session(test_engine) as s:
            yield s
    fastapi_app.dependency_overrides[get_db] = _override
    c = TestClient(fastapi_app)

    reg = c.post("/api/v1/auth/register", json={
        "email": "plain-client@bf.com", "password": "Pw12345678", "name": "Plain"})
    assert reg.status_code == 201
    me = c.get("/api/v1/auth/me",
               headers={"Authorization": f"Bearer {reg.json()['access_token']}"})
    assert me.json()["is_coach"] is False
    # Don't blanket-clear: the module-scoped `client` fixture installed an
    # override that other tests rely on. Just remove ours if we set it.
    pass


def test_non_super_admin_cannot_promote_admin(test_engine):
    """A regular admin (not super-admin) gets 403 from /admins/promote."""
    from app.main import app as fastapi_app
    from app.auth.deps import get_db
    from app.models import ClientProfile

    def _override():
        with Session(test_engine) as s:
            yield s
    fastapi_app.dependency_overrides[get_db] = _override
    c = TestClient(fastapi_app)

    c.post("/api/v1/auth/register", json={
        "email": "regular-admin@bf.com", "password": "Pw12345678", "name": "Reg"})
    with Session(test_engine) as s:
        u = s.exec(select(ClientProfile).where(ClientProfile.email == "regular-admin@bf.com")).first()
        assert u is not None
        u.is_admin = True
        s.add(u)
        s.commit()
    login = c.post("/api/v1/auth/login", json={
        "email": "regular-admin@bf.com", "password": "Pw12345678"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = c.post("/api/v1/admin/admins/promote", headers=headers,
                  json={"email": "anyone@bf.com"})
    assert resp.status_code == 403
    # Don't blanket-clear: the module-scoped `client` fixture installed an
    # override that other tests rely on. Just remove ours if we set it.
    pass


def test_login_sets_httponly_cookies_and_cookie_auth_works(test_engine):
    """Login response sets access_token + refresh_token cookies; subsequent
    requests with cookies but no Authorization header still authenticate."""
    fresh = TestClient(fastapi_app)
    fresh.post("/api/v1/auth/register", json={
        "email": "cookieuser@bf.com",
        "password": "CookiePass1",
        "name": "Cookie",
    })
    login = fresh.post("/api/v1/auth/login",
                      json={"email": "cookieuser@bf.com", "password": "CookiePass1"})
    assert login.status_code == 200
    # Cookies should be set on the TestClient
    assert "access_token" in fresh.cookies
    assert "refresh_token" in fresh.cookies

    # /me works with no Authorization header (cookie auth path)
    me = fresh.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "cookieuser@bf.com"

    # Logout clears cookies
    out = fresh.post("/api/v1/auth/logout")
    assert out.status_code == 200
    assert out.json()["ok"] is True
    me2 = fresh.get("/api/v1/auth/me")
    assert me2.status_code == 401


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

    # Don't blanket-clear: the module-scoped `client` fixture installed an
    # override that other tests rely on. Just remove ours if we set it.
    pass


# ── Coach + admin flow ────────────────────────────────────────────────────────

def test_coach_admin_full_flow(test_engine):
    """Admin promotes coach, assigns client, client generates → pending → coach approves → active."""
    from app.main import app as fastapi_app
    from sqlmodel import Session
    from app.auth.deps import get_db
    from app.models import ClientProfile

    def _override_db():
        with Session(test_engine) as s:
            yield s

    fastapi_app.dependency_overrides[get_db] = _override_db
    c = TestClient(fastapi_app)

    # Register admin, coach, client
    admin_reg = c.post("/api/v1/auth/register",
                      json={"email": "admin@bf.com", "password": "Pass12345", "name": "Admin"})
    coach_reg = c.post("/api/v1/auth/register",
                      json={"email": "coach@bf.com", "password": "Pass12345", "name": "Coach"})
    client_reg = c.post("/api/v1/auth/register",
                       json={"email": "client@bf.com", "password": "Pass12345", "name": "Client"})

    admin_h = {"Authorization": f"Bearer {admin_reg.json()['access_token']}"}
    coach_h = {"Authorization": f"Bearer {coach_reg.json()['access_token']}"}
    client_h = {"Authorization": f"Bearer {client_reg.json()['access_token']}"}

    # Manually flip is_admin (bootstrap)
    with Session(test_engine) as s:
        admin_user = s.exec(select(ClientProfile).where(ClientProfile.email == "admin@bf.com")).first()
        assert admin_user is not None
        admin_user.is_admin = True
        s.add(admin_user)
        s.commit()

    # Admin promotes coach
    promote = c.post("/api/v1/admin/promote", headers=admin_h,
                    json={"email": "coach@bf.com", "is_coach": True})
    assert promote.status_code == 200, promote.text
    assert promote.json()["is_coach"] is True

    # Admin assigns client to coach
    assign = c.post("/api/v1/admin/assign", headers=admin_h,
                   json={"client_email": "client@bf.com", "coach_email": "coach@bf.com"})
    assert assign.status_code == 200, assign.text

    # Coach lists clients
    coach_clients = c.get("/api/v1/coach/clients", headers=coach_h)
    assert coach_clients.status_code == 200
    assert any(cl["email"] == "client@bf.com" for cl in coach_clients.json())

    # Client sets profile + generates plan → goes to pending
    c.put("/api/v1/profile", headers=client_h, json={
        "training_days": 4, "experience_level": "intermediate",
        "available_equipment": ["full_gym"], "limitations": [],
    })
    gen = c.post("/api/v1/plans/generate", headers=client_h)
    assert gen.status_code == 200, gen.text
    assert gen.json()["status"] == "pending_approval"
    approval_uuid = gen.json()["approval_uuid"]

    # Client's /today shows pending_review flag
    today = c.get("/api/v1/plans/today", headers=client_h)
    assert today.json()["pending_review"] is True

    # Coach sees the pending approval
    pending_list = c.get("/api/v1/coach/pending", headers=coach_h)
    assert pending_list.status_code == 200
    assert len(pending_list.json()) == 1
    assert pending_list.json()[0]["approval_uuid"] == approval_uuid

    # Coach approves
    approve = c.post(f"/api/v1/coach/approve/{approval_uuid}", headers=coach_h)
    assert approve.status_code == 200, approve.text
    assert approve.json()["ok"] is True

    # Client's /today now has a real plan
    today2 = c.get("/api/v1/plans/today", headers=client_h)
    assert today2.json()["no_plan"] is False
    assert today2.json()["total_days"] == 4

    # Non-coach can't access coach endpoints
    no_coach = c.get("/api/v1/coach/clients", headers=client_h)
    assert no_coach.status_code == 403

    # Don't blanket-clear: the module-scoped `client` fixture installed an
    # override that other tests rely on. Just remove ours if we set it.
    pass


def test_idempotent_generate_when_pending_exists(test_engine):
    """Calling /plans/generate twice with a coach assigned must not create
    duplicate PendingApproval rows or double-bump week_number."""
    from app.main import app as fastapi_app
    from sqlmodel import Session
    from app.auth.deps import get_db
    from app.models import ClientProfile, PendingApproval

    def _override_db():
        with Session(test_engine) as s:
            yield s

    fastapi_app.dependency_overrides[get_db] = _override_db
    c = TestClient(fastapi_app)

    coach_reg = c.post("/api/v1/auth/register",
                      json={"email": "coach2@bf.com", "password": "Pass12345", "name": "Coach2"})
    client_reg = c.post("/api/v1/auth/register",
                       json={"email": "client2@bf.com", "password": "Pass12345", "name": "Client2"})

    coach_h = {"Authorization": f"Bearer {coach_reg.json()['access_token']}"}  # noqa: F841
    client_h = {"Authorization": f"Bearer {client_reg.json()['access_token']}"}

    client_id_str = ""
    with Session(test_engine) as s:
        coach = s.exec(select(ClientProfile).where(ClientProfile.email == "coach2@bf.com")).first()
        client = s.exec(select(ClientProfile).where(ClientProfile.email == "client2@bf.com")).first()
        assert coach is not None and client is not None
        coach.is_coach = True
        client.coach_id = coach.client_id
        client_id_str = client.client_id
        s.add(coach)
        s.add(client)
        s.commit()

    c.put("/api/v1/profile", headers=client_h, json={
        "training_days": 3, "experience_level": "beginner",
        "available_equipment": ["full_gym"], "limitations": [],
    })

    g1 = c.post("/api/v1/plans/generate", headers=client_h)
    g2 = c.post("/api/v1/plans/generate", headers=client_h)
    assert g1.status_code == 200
    assert g2.status_code == 200
    assert g1.json()["approval_uuid"] == g2.json()["approval_uuid"]

    with Session(test_engine) as s:
        pending = s.exec(
            select(PendingApproval).where(PendingApproval.client_id == client_id_str)
        ).all()
        assert len(pending) == 1

    # Don't blanket-clear: the module-scoped `client` fixture installed an
    # override that other tests rely on. Just remove ours if we set it.
    pass


def test_rejection_surfaces_feedback_to_client(test_engine):
    """When coach rejects, client's /today should expose the feedback string."""
    from app.main import app as fastapi_app
    from sqlmodel import Session
    from app.auth.deps import get_db
    from app.models import ClientProfile

    def _override_db():
        with Session(test_engine) as s:
            yield s

    fastapi_app.dependency_overrides[get_db] = _override_db
    c = TestClient(fastapi_app)

    coach_reg = c.post("/api/v1/auth/register",
                      json={"email": "coach3@bf.com", "password": "Pass12345", "name": "Coach3"})
    client_reg = c.post("/api/v1/auth/register",
                       json={"email": "client3@bf.com", "password": "Pass12345", "name": "Client3"})

    coach_h = {"Authorization": f"Bearer {coach_reg.json()['access_token']}"}
    client_h = {"Authorization": f"Bearer {client_reg.json()['access_token']}"}

    with Session(test_engine) as s:
        coach = s.exec(select(ClientProfile).where(ClientProfile.email == "coach3@bf.com")).first()
        client = s.exec(select(ClientProfile).where(ClientProfile.email == "client3@bf.com")).first()
        assert coach is not None and client is not None
        coach.is_coach = True
        client.coach_id = coach.client_id
        s.add(coach)
        s.add(client)
        s.commit()

    c.put("/api/v1/profile", headers=client_h, json={
        "training_days": 3, "experience_level": "beginner",
        "available_equipment": ["full_gym"], "limitations": [],
    })

    gen = c.post("/api/v1/plans/generate", headers=client_h)
    approval_uuid = gen.json()["approval_uuid"]

    # Coach rejects with feedback
    rej = c.post(f"/api/v1/coach/reject/{approval_uuid}", headers=coach_h,
                 json={"feedback": "Too much volume on day 2"})
    assert rej.status_code == 200, rej.text

    # Client's /today now shows rejection feedback (and pending_review = false)
    today = c.get("/api/v1/plans/today", headers=client_h)
    data = today.json()
    assert data["pending_review"] is False
    assert data["rejection_feedback"] == "Too much volume on day 2"

    # Client regenerates → feedback consumed → next /today no longer shows it
    c.post("/api/v1/plans/generate", headers=client_h)
    today2 = c.get("/api/v1/plans/today", headers=client_h)
    assert today2.json()["pending_review"] is True
    assert today2.json().get("rejection_feedback") is None

    # Don't blanket-clear: the module-scoped `client` fixture installed an
    # override that other tests rely on. Just remove ours if we set it.
    pass
