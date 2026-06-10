# template_generator/visual_validator.py

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class VisualIssue:
    level: str  # critical, major, minor
    category: str
    message: str


@dataclass
class VisualValidationReport:
    score: int
    passed: bool
    issues: List[VisualIssue]


def validate_visual_quality(
    rendered_metrics: Dict[str, Any],
    original_metrics: Dict[str, Any],
) -> VisualValidationReport:
    issues: List[VisualIssue] = []

    # Validation A4
    width = rendered_metrics.get("width")
    height = rendered_metrics.get("height")
    scroll_height = rendered_metrics.get("scroll_height")

    if abs(width - 794) > 20:
        issues.append(VisualIssue("major", "a4", f"Largeur incorrecte: {width}px"))

    if abs(height - 1123) > 30:
        issues.append(VisualIssue("major", "a4", f"Hauteur incorrecte: {height}px"))

    if scroll_height and scroll_height > 1123:
        issues.append(VisualIssue("critical", "overflow", "Le contenu dépasse la page A4"))

    # Layout
    sidebar_width = rendered_metrics.get("sidebar_width")
    original_sidebar_width = original_metrics.get("sidebar_width")

    if sidebar_width and original_sidebar_width:
        diff = abs(sidebar_width - original_sidebar_width)
        if diff > 40:
            issues.append(
                VisualIssue("major", "layout", f"Sidebar trop différente: écart {diff}px")
            )

    # Densité
    line_height = rendered_metrics.get("line_height")
    if line_height and line_height < 1.15:
        issues.append(
            VisualIssue("minor", "density", "Line-height trop serré")
        )

    overflowing_blocks = rendered_metrics.get("overflowing_blocks", 0)
    if overflowing_blocks > 0:
        issues.append(
            VisualIssue("critical", "overflow", f"{overflowing_blocks} bloc(s) dépassent")
        )

    score = 100
    for issue in issues:
        if issue.level == "critical":
            score -= 25
        elif issue.level == "major":
            score -= 12
        else:
            score -= 5

    score = max(score, 0)

    return VisualValidationReport(
        score=score,
        passed=score >= 90,
        issues=issues,
    )