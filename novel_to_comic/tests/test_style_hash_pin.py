"""Style template hash pinning tests."""

from datetime import datetime, timezone

from novel_to_comic.state import (
    PipelineState,
    hash_style_template,
    style_template_drifted,
)


def _empty_state() -> PipelineState:
    return PipelineState(
        project_name="t",
        novel_path="t.txt",
        created_at=datetime.now(timezone.utc),
    )


def test_hash_is_whitespace_normalised():
    a = "Cinematic photorealistic, natural lighting, shallow DOF."
    b = "  Cinematic   photorealistic,\n natural   lighting, shallow DOF.\n"
    assert hash_style_template(a) == hash_style_template(b)


def test_hash_differs_when_template_changes():
    a = hash_style_template("Cinematic photorealistic, natural lighting.")
    b = hash_style_template("Oil painting, broad brushwork.")
    assert a != b


def test_drift_false_when_no_hash_pinned():
    state = _empty_state()
    assert state.style_template_hash is None
    assert style_template_drifted(state, "anything") is False


def test_drift_false_when_template_unchanged():
    state = _empty_state()
    state.style_template_hash = hash_style_template("X")
    assert style_template_drifted(state, "X") is False


def test_drift_true_when_template_changed():
    state = _empty_state()
    state.style_template_hash = hash_style_template("X")
    assert style_template_drifted(state, "Y") is True
