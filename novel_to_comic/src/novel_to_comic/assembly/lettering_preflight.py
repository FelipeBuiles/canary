"""Rendered lettering checks used by the export preflight.

Character counts are only a rough proxy for a comic letterer's real concern:
how much of a particular panel is covered after its font, wrapping, and layout
are resolved.  This module classifies the DOM measurements collected by the
shared HTML renderer and exposes a project-level preflight for exports.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.models.comic_page import ComicPage

from .html_renderer import browser_context, build_page_html, inspect_html_lettering_metrics
from .lettering_style import load_lettering_style


WARNING_COVERAGE_RATIO = 0.25
MAX_COVERAGE_RATIO = 0.32
MAX_AUTO_STACK_RATIO = 0.40


@dataclass(frozen=True)
class PanelLetteringMetrics:
    page_number: int
    panel_id: str
    panel_number: int
    coverage_ratio: float
    max_auto_stack_ratio: float
    overflowing_bubble_ids: tuple[str, ...]
    unsafe_bubble_ids: tuple[str, ...]


@dataclass(frozen=True)
class LetteringPreflightIssue:
    code: str
    severity: str
    page_number: int
    panel_id: str
    panel_number: int
    bubble_ids: tuple[str, ...]
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "page_number": self.page_number,
            "panel_id": self.panel_id,
            "panel_number": self.panel_number,
            "bubble_ids": list(self.bubble_ids),
            "message": self.message,
        }


def classify_lettering_metrics(
    metrics: list[PanelLetteringMetrics],
) -> list[LetteringPreflightIssue]:
    """Classify rendered panel measurements into actionable export findings."""
    issues: list[LetteringPreflightIssue] = []
    for panel in metrics:
        base = {
            "page_number": panel.page_number,
            "panel_id": panel.panel_id,
            "panel_number": panel.panel_number,
        }
        if panel.overflowing_bubble_ids:
            issues.append(
                LetteringPreflightIssue(
                    code="lettering_overflow",
                    severity="error",
                    bubble_ids=panel.overflowing_bubble_ids,
                    message=(
                        f"Panel {panel.panel_number} has lettering outside its panel bounds. "
                        "Shorten, split, or reposition the text before export."
                    ),
                    **base,
                )
            )
        if panel.unsafe_bubble_ids:
            issues.append(
                LetteringPreflightIssue(
                    code="lettering_unsafe_area",
                    # SVG perimeter sampling is deliberately conservative and
                    # can flag visually sound auto-sized balloons at scalloped
                    # corners. Keep it visible for review, but reserve export
                    # blocking for objective overflow/coverage failures.
                    severity="warning",
                    bubble_ids=panel.unsafe_bubble_ids,
                    message=(
                        f"Panel {panel.panel_number} may have text close to its balloon edge. "
                        "Review the rendered lettering before export."
                    ),
                    **base,
                )
            )
        if panel.coverage_ratio > MAX_COVERAGE_RATIO:
            issues.append(
                LetteringPreflightIssue(
                    code="lettering_obscures_art",
                    severity="error",
                    bubble_ids=(),
                    message=(
                        f"Panel {panel.panel_number} lettering covers "
                        f"{panel.coverage_ratio:.0%} of the art area (maximum {MAX_COVERAGE_RATIO:.0%})."
                    ),
                    **base,
                )
            )
        elif panel.coverage_ratio >= WARNING_COVERAGE_RATIO:
            issues.append(
                LetteringPreflightIssue(
                    code="lettering_obscures_art",
                    severity="warning",
                    bubble_ids=(),
                    message=(
                        f"Panel {panel.panel_number} lettering covers "
                        f"{panel.coverage_ratio:.0%} of the art area. Consider tightening the copy."
                    ),
                    **base,
                )
            )
        if panel.max_auto_stack_ratio > MAX_AUTO_STACK_RATIO:
            issues.append(
                LetteringPreflightIssue(
                    code="lettering_stack_too_tall",
                    severity="error",
                    bubble_ids=(),
                    message=(
                        f"Panel {panel.panel_number} automatic lettering stack uses "
                        f"{panel.max_auto_stack_ratio:.0%} of the panel height (maximum {MAX_AUTO_STACK_RATIO:.0%})."
                    ),
                    **base,
                )
            )
    return issues


def has_blocking_lettering_issues(issues: list[LetteringPreflightIssue]) -> bool:
    return any(issue.severity == "error" for issue in issues)


async def inspect_project_lettering(project_dir: Path) -> list[LetteringPreflightIssue]:
    """Measure every composed page with the same Chromium renderer as export."""
    page_paths = sorted(artifacts.compose_pages_dir(project_dir).glob("page_*.json"))
    if not page_paths:
        return []

    lettering = load_lettering_style(project_dir)
    metrics: list[PanelLetteringMetrics] = []
    async with browser_context() as browser:
        for path in page_paths:
            comic_page = ComicPage.model_validate_json(path.read_text())
            html = build_page_html(comic_page, project_dir, lettering=lettering)
            rendered = await inspect_html_lettering_metrics(html, browser=browser)
            panel_numbers = {panel.id: panel.panel_number for panel in comic_page.panels}
            metrics.extend(
                PanelLetteringMetrics(
                    page_number=comic_page.page_number,
                    panel_id=str(item["panel_id"]),
                    panel_number=panel_numbers.get(str(item["panel_id"]), 0),
                    coverage_ratio=float(item["coverage_ratio"]),
                    max_auto_stack_ratio=float(item["max_auto_stack_ratio"]),
                    overflowing_bubble_ids=tuple(str(value) for value in item["overflowing_bubble_ids"]),
                    unsafe_bubble_ids=tuple(str(value) for value in item["unsafe_bubble_ids"]),
                )
                for item in rendered
            )
    return classify_lettering_metrics(metrics)
