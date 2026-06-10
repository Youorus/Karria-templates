# template_generator/quality_gate.py

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class QualityIssue:
    level: str  # "critical", "major", "minor"
    category: str
    message: str
    auto_fixable: bool = False


@dataclass
class QualityReport:
    score: int
    approved: bool
    needs_human_review: bool
    issues: List[QualityIssue]


def compute_quality_score(issues: List[QualityIssue]) -> int:
    score = 100

    for issue in issues:
        if issue.level == "critical":
            score -= 25
        elif issue.level == "major":
            score -= 12
        elif issue.level == "minor":
            score -= 5

    return max(score, 0)


def build_quality_report(issues: List[QualityIssue]) -> QualityReport:
    score = compute_quality_score(issues)

    return QualityReport(
        score=score,
        approved=score >= 90,
        needs_human_review=70 <= score < 90,
        issues=issues,
    )