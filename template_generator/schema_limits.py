# template_generator/schema_limits.py
"""
SchemaLimitsCalculator
======================

Transforme les mesures réelles extraites par PDFAnalyzer en limites de contenu
utilisables dans schema.json et dans les prompts IA.

Objectif : éviter que schema.json contienne des limites théoriques trop larges
pour la géométrie réelle du template A4 analysé.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

try:
    from .pdf_analyzer import PDFAnalysis
except ImportError:  # exécution directe
    from pdf_analyzer import PDFAnalysis


@dataclass(frozen=True)
class SchemaLimits:
    """Budget physique maximal conseillé pour un template CV."""

    summary_max_length: int
    experiences_max_items: int
    experience_description_max_length: int
    education_max_items: int
    skills_max_items: int
    languages_max_items: int
    interests_max_items: int
    references_max_items: int

    reason: str
    density_factor: float
    main_width_mm: float
    main_height_mm: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_prompt_block(self) -> str:
        return (
            "LIMITES PHYSIQUES CALCULÉES POUR CE TEMPLATE A4\n"
            "────────────────────────────────────────────────\n"
            "Ces limites remplacent les constantes génériques. Elles sont calculées depuis "
            "la géométrie PDF réelle : marges, sidebar, photo, header, densité texte.\n"
            f"• summary.maxLength: {self.summary_max_length}\n"
            f"• experiences.maxItems: {self.experiences_max_items}\n"
            f"• experiences[].description.maxLength: {self.experience_description_max_length}\n"
            f"• education.maxItems: {self.education_max_items}\n"
            f"• skills.maxItems: {self.skills_max_items}\n"
            f"• languages.maxItems: {self.languages_max_items}\n"
            f"• interests.maxItems: {self.interests_max_items}\n"
            f"• references.maxItems: {self.references_max_items}\n"
            f"• largeur utile estimée main: {self.main_width_mm:.1f}mm\n"
            f"• hauteur utile estimée main: {self.main_height_mm:.1f}mm\n"
            f"• facteur densité: {self.density_factor:.2f}\n"
            f"• justification: {self.reason}\n"
            "Règle bloquante : schema.json et data.json ne doivent jamais dépasser ces limites."
        )


class SchemaLimitsCalculator:
    """Calcule un budget de contenu à partir d'un PDFAnalysis."""

    @staticmethod
    def from_analysis(
        analysis: PDFAnalysis,
        layout_key: Optional[str] = None,
        target_pages: int = 1,
    ) -> SchemaLimits:
        layout = (layout_key or "").lower()
        page_width = float(getattr(analysis, "width_mm", 210) or 210)
        page_height = float(getattr(analysis, "height_mm", 297) or 297)

        margins = getattr(analysis, "margins", None)
        margin_left = float(getattr(margins, "left", 14) or 14)
        margin_right = float(getattr(margins, "right", 14) or 14)
        margin_top = float(getattr(margins, "top", 18) or 18)
        margin_bottom = float(getattr(margins, "bottom", 16) or 16)

        sidebar = getattr(analysis, "sidebar", None)
        sidebar_width = float(getattr(sidebar, "width_mm", 0) or 0)
        has_sidebar = bool(sidebar_width > 20 or "sidebar" in layout or "two-column" in layout)
        has_photo = bool(getattr(analysis, "has_photo", False))
        header = getattr(analysis, "header", None)
        header_height = float(getattr(header, "height_mm", 0) or 0)
        density = float(getattr(analysis, "text_density_score", 0.25) or 0.25)
        columns = int(getattr(analysis, "estimated_columns", 1) or 1)

        main_width = page_width - margin_left - margin_right - (sidebar_width if has_sidebar else 0)
        main_height = page_height - margin_top - margin_bottom - min(header_height, 60)
        main_width = max(main_width, 80)
        main_height = max(main_height, 120)

        # Base pour A4 1 page. Les valeurs sont volontairement conservatrices :
        # le rendu final reste contrôlé par Playwright/overflow validator.
        if has_sidebar:
            summary = 320
            exp_items = 4
            exp_desc = 160
            edu = 2
            skills = 8
            langs = 3
            interests = 3
        else:
            summary = 420
            exp_items = 5
            exp_desc = 210
            edu = 3
            skills = 10
            langs = 4
            interests = 4

        reasons = []
        if has_sidebar:
            reasons.append("sidebar détectée")
        if has_photo:
            reasons.append("photo détectée")
        if columns >= 2:
            reasons.append(f"{columns} colonnes détectées")

        # Pénalités de géométrie.
        if has_photo:
            summary -= 40
            skills -= 1
            reasons.append("photo consomme de la hauteur")

        if sidebar_width and sidebar_width / page_width >= 0.32:
            skills -= 1
            edu -= 1
            exp_desc -= 20
            reasons.append("sidebar large")

        if header_height >= 50:
            summary -= 40
            exp_desc -= 20
            reasons.append("header haut")

        if density >= 0.34:
            exp_items -= 1
            exp_desc -= 30
            summary -= 50
            skills -= 1
            reasons.append("densité texte élevée")

        if main_width < 105:
            exp_desc -= 25
            summary -= 30
            reasons.append("colonne principale étroite")

        if main_height < 190:
            exp_items -= 1
            exp_desc -= 25
            edu -= 1
            reasons.append("hauteur utile faible")

        # Bornes minimales / maximales raisonnables pour préserver la qualité.
        summary = max(220, min(summary, 500))
        exp_items = max(2, min(exp_items, 6))
        exp_desc = max(100, min(exp_desc, 350))
        edu = max(1, min(edu, 4))
        skills = max(5, min(skills, 12))
        langs = max(2, min(langs, 5))
        interests = max(0, min(interests, 6))

        # Les références sont très coûteuses sur un CV 1 page sidebar.
        references = 0 if has_sidebar or target_pages == 1 else 2

        return SchemaLimits(
            summary_max_length=summary,
            experiences_max_items=exp_items,
            experience_description_max_length=exp_desc,
            education_max_items=edu,
            skills_max_items=skills,
            languages_max_items=langs,
            interests_max_items=interests,
            references_max_items=references,
            reason=", ".join(reasons) or "géométrie standard A4",
            density_factor=density,
            main_width_mm=main_width,
            main_height_mm=main_height,
        )
