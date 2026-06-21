"""Security: account deletion must scrub PII from snapshots + feedback, not just the profile."""
import json

from sqlmodel import Session, select

from app.main import app as fastapi_app
from app.auth.deps import get_current_user, get_db
from app.models import ClientProfile, ProfileSnapshot, Feedback


def _seed(engine, email="alice@example.com"):
    with Session(engine) as s:
        client = ClientProfile(client_id="cl_del", avatar="gen_pop", training_days=3,
                               name="Alice", email=email)
        s.add(client)
        s.add(ProfileSnapshot(client_id="cl_del",
                              snapshot_json=json.dumps({"email": email, "name": "Alice", "avatar": "gen_pop"}),
                              reason="initial"))
        s.add(Feedback(client_id="cl_del", email=email, message="great app"))
        s.commit()
        s.refresh(client)
    return client


def test_delete_scrubs_pii_everywhere(test_engine):
    from fastapi.testclient import TestClient
    email = "alice@example.com"
    client = _seed(test_engine)

    fastapi_app.dependency_overrides[get_current_user] = lambda: client
    fastapi_app.dependency_overrides[get_db] = lambda: (yield from _db_gen(test_engine))
    try:
        tc = TestClient(fastapi_app)
        r = tc.delete("/api/v1/profile")
        assert r.status_code == 200
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)
        fastapi_app.dependency_overrides.pop(get_db, None)

    with Session(test_engine) as s:
        for snap in s.exec(select(ProfileSnapshot).where(ProfileSnapshot.client_id == "cl_del")).all():
            assert email not in snap.snapshot_json
            assert "Alice" not in snap.snapshot_json
        for fb in s.exec(select(Feedback).where(Feedback.client_id == "cl_del")).all():
            assert fb.email != email


def _db_gen(engine):
    with Session(engine) as session:
        yield session
