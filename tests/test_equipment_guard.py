from app.domain.workout import equipment as eq


def test_equipment_gap_note_for_no_bar_bodyweight():
    note = eq.equipment_gap_note(["bodyweight"])
    assert note and "pull" in note.lower()


def test_no_gap_note_with_bar():
    assert eq.equipment_gap_note(["bodyweight", "pull_up_bar"]) is None
    assert eq.equipment_gap_note(["full_gym"]) is None
