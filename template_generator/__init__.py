# template_generator/__init__.py
"""
Package template_generator — Karria.

Entrées principales :
  • generate()                 → génération depuis PDF
  • run_pipeline()             → génération + preview/review + submit
  • action_submit()            → soumission directe
  • run_preview()              → preview standalone avec validation qualité
  • validate_all()             → validations techniques template
"""

from .infos_builder import CVHumanInputs, InfosBuilder, LMHumanInputs
from .pdf_analyzer import PDFAnalysis, PDFAnalyzer
from .validators import validate_all


def generate(*args, **kwargs):
    from .generate_templates import generate as _generate
    return _generate(*args, **kwargs)


def run_pipeline(*args, **kwargs):
    from .pipeline import run_pipeline as _run_pipeline
    return _run_pipeline(*args, **kwargs)


def action_submit(*args, **kwargs):
    from .submit_template import action_submit as _action_submit
    return _action_submit(*args, **kwargs)


def run_preview(*args, **kwargs):
    from .preview_renderer import run_preview as _run_preview
    return _run_preview(*args, **kwargs)


def validate_visual_quality(*args, **kwargs):
    from .generate_templates import validate_visual_quality as _validate_visual_quality
    return _validate_visual_quality(*args, **kwargs)


def __getattr__(name: str):
    if name in {"VisualIssue", "VisualValidationReport"}:
        from .generate_templates import VisualIssue, VisualValidationReport
        return {"VisualIssue": VisualIssue, "VisualValidationReport": VisualValidationReport}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")