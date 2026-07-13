from novel_to_comic.assembly.lettering_preflight import (
    PanelLetteringMetrics,
    classify_lettering_metrics,
    has_blocking_lettering_issues,
)


def _metrics(**overrides) -> PanelLetteringMetrics:
    values = {
        "page_number": 1,
        "panel_id": "scene_001-001",
        "panel_number": 1,
        "coverage_ratio": 0.12,
        "max_auto_stack_ratio": 0.18,
        "overflowing_bubble_ids": (),
        "unsafe_bubble_ids": (),
    }
    values.update(overrides)
    return PanelLetteringMetrics(**values)


def test_coverage_between_target_and_limit_is_a_warning():
    issues = classify_lettering_metrics([_metrics(coverage_ratio=0.25)])

    assert [(issue.code, issue.severity) for issue in issues] == [
        ("lettering_obscures_art", "warning"),
    ]


def test_coverage_over_limit_blocks_export():
    issues = classify_lettering_metrics([_metrics(coverage_ratio=0.33)])

    assert [(issue.code, issue.severity) for issue in issues] == [
        ("lettering_obscures_art", "error"),
    ]
    assert has_blocking_lettering_issues(issues) is True


def test_overflow_and_tall_auto_stack_are_blocking_errors():
    issues = classify_lettering_metrics([
        _metrics(
            max_auto_stack_ratio=0.41,
            overflowing_bubble_ids=("scene_001-p1-b0",),
        )
    ])

    assert {issue.code for issue in issues} == {
        "lettering_overflow",
        "lettering_stack_too_tall",
    }
    assert all(issue.severity == "error" for issue in issues)


def test_text_outside_shape_safe_area_blocks_export():
    issues = classify_lettering_metrics([
        _metrics(unsafe_bubble_ids=("scene_001-p1-b0",))
    ])

    assert [(issue.code, issue.severity, issue.bubble_ids) for issue in issues] == [
        ("lettering_unsafe_area", "error", ("scene_001-p1-b0",)),
    ]
