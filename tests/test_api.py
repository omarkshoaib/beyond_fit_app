from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from app.main import app as fastapi_app
from app.settings import get_settings
from app.auth.deps import get_current_user
from app.models import ClientProfile


def _make_mock_container():
    """Build a fake Container with a no-op session factory and mocked LLM."""
    settings = get_settings()

    mock_llm = MagicMock()
    mock_llm.complete.return_value = "**Here is your tailored workout plan!** \\n You'll crush it."

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    container = MagicMock()
    container.settings = settings
    container.llm_client = mock_llm
    container.session_factory.return_value = mock_session

    return container


def test_generate_and_coach_endpoint():
    payload = {
        "client_id": "999",
        "avatar": "powerbuilder",
        "training_days": 4,
        "experience_level": "intermediate",
        "limitations": [],
        "available_equipment": ["full_gym"]
    }

    # Inject a fake container so the route never touches a real DB or LLM
    fastapi_app.state.container = _make_mock_container()
    # Authenticate as a fake user (route requires auth post-hardening).
    fastapi_app.dependency_overrides[get_current_user] = lambda: ClientProfile(
        client_id="999", avatar="powerbuilder", training_days=4,
        experience_level="intermediate",
    )

    try:
        client = TestClient(fastapi_app)
        response = client.post("/generate_and_coach", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "workout" in data
        assert "coaching_message" in data
        assert data["coaching_message"] == "**Here is your tailored workout plan!** \\n You'll crush it."
        assert data["workout"]["week_number"] == 1

        # LLM was called exactly once (coaching message generation)
        fastapi_app.state.container.llm_client.complete.assert_called_once()
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)
