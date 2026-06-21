"""Safety: coach-edit LLM output must validate as a WorkoutWeek before it can
overwrite a live plan."""
from unittest.mock import MagicMock

import pytest

from app.services.llm_service import FlashCommunicationService

_VALID = '{"week_number": 1, "days": []}'


def _svc(return_value: str) -> FlashCommunicationService:
    llm = MagicMock()
    llm.complete.return_value = return_value
    return FlashCommunicationService(llm_client=llm)


def test_valid_workoutweek_passes_through():
    svc = _svc(_VALID)
    out = svc.apply_coach_edits('{"week_number": 1, "days": []}', "make it easier")
    # round-trips to the same structure
    import json
    assert json.loads(out)["week_number"] == 1


def test_structurally_invalid_output_rejected():
    svc = _svc('{"totally": "wrong"}')
    with pytest.raises(ValueError):
        svc.apply_coach_edits('{"week_number": 1, "days": []}', "scramble it")


def test_non_json_output_rejected():
    svc = _svc("I cannot do that, sorry!")
    with pytest.raises(ValueError):
        svc.apply_coach_edits('{"week_number": 1, "days": []}', "break it")
