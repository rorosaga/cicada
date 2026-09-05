"""G117 — Task 4's install-gap fix: a byok install that never chose an
engine gets an honest reason, not a diagnosis of a key nobody entered."""
from api.services.sleep_cycle import _stage1_failure_message


def test_no_engine_chosen_reads_as_a_choice_not_a_diagnosis():
    msg = _stage1_failure_message("litellm", engine_detail="no Sleep engine chosen — using the configured API model")
    assert "no engine chosen" in msg.lower()
    assert "Settings" in msg and "Sleep" in msg
    assert "credit" not in msg.lower()


def test_a_real_key_failure_keeps_the_diagnostic_copy():
    msg = _stage1_failure_message("litellm", engine_detail=None)
    assert "credit" in msg.lower()
