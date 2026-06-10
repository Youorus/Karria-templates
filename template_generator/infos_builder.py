# template_generator/infos_builder.py
"""
InfosBuilder v3 — `infos.json` cohérent avec MachineFullSubmitMeta.

Changements vs v2 :
  * Le bloc CV n'est PLUS dupliqué à la racine (fini la double source).
    On garde un schéma propre : `cv` et `cover_letter` sont les seules sources.
    Le backend lit `cv.X` ; submit_template.py a déjà le fallback racine pour
    les anciens fichiers.
  * Schéma version bumped à v3.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from .pdf_analyzer import PDFAnalysis, ColorInfo, FontInfo
except ImportError:  # exécution directe: python template_generator/generate_templates.py
    from pdf_analyzer import PDFAnalysis, ColorInfo, FontInfo

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES MÉTIER
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_CATEGORIES = {
    "classic", "modern", "professional", "creative",
    "minimalist", "executive", "academic", "ats", "elegant",
}

ALLOWED_CV_LAYOUTS = {
    "single-column",
    "two-column-left-sidebar",
    "two-column-right-sidebar",
    "header-sidebar",
    "timeline",
    "card-based",
    "editorial",
    "compact",
}

ALLOWED_LM_LAYOUTS = {"standard-letter", "modern-letter", "compact-letter"}

FUN_LABEL_FALLBACKS = (
    "Rocket Line", "Neon Career", "Bold Move", "Pixel Pro", "Urban Flow",
    "Career Pop", "Fresh Start", "Nova Resume", "Vibe Pro", "Next Step",
    "Blue Spark", "Focus Club", "Studio Boss", "Level Up", "Glow Up Pro",
    "Pulse Resume", "Crystal Path", "Apex Career", "Velvet Edge", "Iron Resume",
)

GENERIC_LABEL_PATTERNS = (
    r"^cv( moderne| classique| professionnel)?$",
    r"^template( moderne| classique| professionnel)?$",
    r"^timeline verticale$",
    r"^deux colonnes$",
    r"^sidebar gauche$",
    r"^sidebar droite$",
    r"^minimaliste( .*)?$",
    r"^moderne( .*)?$",
    r"^classique( .*)?$",
    r"^professionnel( .*)?$",
    r"^modele avec photo$",
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def slugify(value: str) -> str:
    if not value:
        return "template"
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value or "template"


def is_generic_label(label: Optional[str]) -> bool:
    if not label or not str(label).strip():
        return True
    value = unicodedata.normalize("NFKD", str(label).strip().lower())
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"\s+", " ", value)
    return any(re.match(p, value) for p in GENERIC_LABEL_PATTERNS)


def primary_from_palette(colors: List[ColorInfo], fallback: str = "#1A73E8") -> str:
    for c in colors:
        if not isinstance(c, ColorInfo):
            continue
        r, g, b = c.rgb
        if r > 230 and g > 230 and b > 230:
            continue
        if r < 30 and g < 30 and b < 30:
            continue
        return c.hex
    return fallback


def main_font_from_analysis(fonts: List[FontInfo], fallback: str = "Inter") -> str:
    if not fonts:
        return fallback
    return _to_google_font(fonts[0].name)


def _to_google_font(detected: str) -> str:
    if not detected:
        return "Inter"

    aliases = {
        "Helvetica": "Inter", "Helvetica Neue": "Inter", "Arial": "Inter",
        "Calibri": "Lato",
        "Times": "Cormorant Garamond", "Times New Roman": "Cormorant Garamond",
        "Cormorant": "Cormorant Garamond", "Garamond": "Cormorant Garamond",
        "Georgia": "Lora", "Palatino": "Lora",
        "Verdana": "Open Sans", "Tahoma": "Open Sans",
        "Cambria": "Lora", "Constantia": "Cormorant Garamond",
        "Trebuchet": "Source Sans Pro", "Trebuchet MS": "Source Sans Pro",
        "Avenir": "Nunito", "Avenir Next": "Nunito",
        "Futura": "Jost", "Optima": "Cormorant Garamond",
    }
    if detected in aliases:
        return aliases[detected]

    google_fonts = {
        "Inter", "Roboto", "Lato", "Open Sans", "Montserrat", "Poppins",
        "Playfair Display", "Lora", "Cormorant Garamond", "Source Sans Pro",
        "Source Serif Pro", "Source Code Pro", "Nunito", "Barlow", "Anton",
        "Merriweather", "Raleway", "Oswald", "PT Sans", "PT Serif",
        "Crimson Text", "Crimson Pro", "Libre Baskerville", "Jost",
    }
    if detected in google_fonts:
        return detected
    return "Inter"


def detect_layout_key_cv(analysis: PDFAnalysis) -> str:
    if analysis.estimated_columns == 1:
        return "single-column"
    if analysis.sidebar_position == "right":
        return "two-column-right-sidebar"
    return "two-column-left-sidebar"


def fun_label_from_analysis(analysis: PDFAnalysis) -> str:
    primary = primary_from_palette(analysis.colors, fallback="#000000").lower()
    if primary.startswith("#") and len(primary) >= 7:
        try:
            r, g, b = int(primary[1:3], 16), int(primary[3:5], 16), int(primary[5:7], 16)
            if b > r and b > g and b > 120:
                return "Blue Spark"
            if r > 170 and g < 130:
                return "Bold Move"
            if g > r and g > b:
                return "Fresh Start"
            if r > 200 and g > 150 and b < 100:
                return "Velvet Edge"
        except ValueError:
            pass

    if analysis.estimated_columns == 1:
        return "Pulse Resume"
    if analysis.sidebar_position == "right":
        return "Studio Boss"
    return "Vibe Pro"


def _normalize_tags(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [t.strip() for t in raw.split(",")]
    if not isinstance(raw, list):
        return []
    seen, out = set(), []
    for t in raw:
        if t is None:
            continue
        s = str(t).strip().lower()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= 8:
            break
    return out


def _coerce_price(price: Any, is_premium: bool) -> Optional[float]:
    if not is_premium:
        return None
    if price is None or price == "" or price is False:
        return None
    try:
        val = float(price)
    except (TypeError, ValueError):
        logger.warning("⚠️ Prix non numérique '%s' — défini à None", price)
        return None
    if val < 0:
        return None
    return round(val, 2)


def _detect_has_photo(analysis: PDFAnalysis, ai_meta: Dict[str, Any]) -> bool:
    return bool(analysis.has_photo) or bool(ai_meta.get("has_photo", False))


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES DE PARAMÈTRES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CVHumanInputs:
    label: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    primary_color: Optional[str] = None
    font_family: Optional[str] = None
    is_premium: bool = False
    price: Optional[float] = None
    is_active: bool = True
    tags: Optional[List[str]] = None
    review_description: Optional[str] = None
    layout_key: Optional[str] = None


@dataclass
class LMHumanInputs:
    label: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    primary_color: Optional[str] = None
    font_family: Optional[str] = None
    layout_key: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# BUILDER
# ─────────────────────────────────────────────────────────────────────────────

class InfosBuilder:
    """
    Construit `infos.json` aligné EXACTEMENT avec MachineFullSubmitMeta.

    Sources (priorité décroissante) :
      1. Choix humain (CVHumanInputs / LMHumanInputs)
      2. Sortie IA (ai_meta)
      3. Analyse PDF (PDFAnalysis)
      4. Fallback déterministe
    """

    SCHEMA_VERSION = "v3"
    LANGUAGE = "fr"

    @staticmethod
    def build(
        *,
        cv_analysis: PDFAnalysis,
        cv_inputs: CVHumanInputs,
        ai_meta: Optional[Dict[str, Any]] = None,
        lm_analysis: Optional[PDFAnalysis] = None,
        lm_inputs: Optional[LMHumanInputs] = None,
    ) -> Dict[str, Any]:
        ai_meta = ai_meta or {}
        lm_inputs = lm_inputs or LMHumanInputs()

        cv_block = InfosBuilder._build_cv_block(cv_analysis, cv_inputs, ai_meta)
        lm_block = (
            InfosBuilder._build_lm_block(lm_analysis, lm_inputs, ai_meta, cv_block)
            if lm_analysis is not None else None
        )

        # ✅ Schéma propre : on N'écrase PAS la racine avec le bloc CV
        # (l'ancien code faisait result.update(cv_block) — incohérent).
        # `submit_template.py` a déjà le fallback `cv = raw.get("cv") or raw`
        # pour les fichiers v2, donc on n'a plus besoin de la duplication.
        return {
            "version": InfosBuilder.SCHEMA_VERSION,
            "language": InfosBuilder.LANGUAGE,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "with_cover_letter": lm_block is not None,
            "cv": cv_block,
            "cover_letter": lm_block,
            "paired_documents": {"cover_letter": lm_block},
            "_extraction_meta": {
                "cv": InfosBuilder._extraction_meta(cv_analysis),
                "lm": InfosBuilder._extraction_meta(lm_analysis) if lm_analysis else None,
            },
        }

    @staticmethod
    def _build_cv_block(
        analysis: PDFAnalysis,
        inputs: CVHumanInputs,
        ai_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Label : humain > IA > fun fallback
        label = inputs.label or ai_meta.get("label") or fun_label_from_analysis(analysis)
        if is_generic_label(label):
            label = fun_label_from_analysis(analysis)

        name = inputs.name or slugify(label)

        category = (inputs.category or ai_meta.get("category") or "modern").lower()
        if category not in ALLOWED_CATEGORIES:
            logger.warning("Catégorie '%s' non reconnue → fallback 'modern'", category)
            category = "modern"

        primary_color = (
            inputs.primary_color
            or ai_meta.get("primary_color")
            or primary_from_palette(analysis.colors)
        )
        font_family = _to_google_font(
            inputs.font_family
            or ai_meta.get("font_family")
            or main_font_from_analysis(analysis.fonts)
        )

        layout_key = (
            inputs.layout_key
            or ai_meta.get("layout_key")
            or ai_meta.get("layout")
            or detect_layout_key_cv(analysis)
        )
        if layout_key not in ALLOWED_CV_LAYOUTS:
            logger.warning("Layout CV '%s' non reconnu → two-column-left-sidebar", layout_key)
            layout_key = "two-column-left-sidebar"

        has_photo = _detect_has_photo(analysis, ai_meta)
        is_premium = bool(inputs.is_premium)
        price = _coerce_price(inputs.price, is_premium)
        tags = _normalize_tags(inputs.tags or ai_meta.get("tags") or _suggest_tags(analysis, category))

        description = (
            inputs.description or ai_meta.get("description")
            or f"Modèle {label} — {category} aux couleurs {primary_color}."
        )

        return {
            "name":               name,
            "label":              label,
            "category":           category,
            "description":        description,
            "primary_color":      primary_color,
            "font_family":        font_family,
            "is_premium":         is_premium,
            "price":              price,
            "is_active":          bool(inputs.is_active),
            "has_photo":          has_photo,
            "tags":               tags,
            "review_description": inputs.review_description or ai_meta.get("review_description") or "",
            "layout_key":         layout_key,
        }

    @staticmethod
    def _build_lm_block(
        analysis: PDFAnalysis,
        inputs: LMHumanInputs,
        ai_meta: Dict[str, Any],
        cv_block: Dict[str, Any],
    ) -> Dict[str, Any]:
        ai_lm = (ai_meta.get("paired_documents") or {}).get("cover_letter") \
            or ai_meta.get("cover_letter") or {}

        label = inputs.label or ai_lm.get("label") or f"Lettre — {cv_block['label']}"
        if is_generic_label(label):
            label = f"Lettre — {cv_block['label']}"
        name = inputs.name or slugify(label)

        category = (inputs.category or ai_lm.get("category") or cv_block["category"]).lower()
        if category not in ALLOWED_CATEGORIES:
            category = cv_block["category"]

        layout_key = inputs.layout_key or ai_lm.get("layout_key") or "standard-letter"
        if layout_key not in ALLOWED_LM_LAYOUTS:
            logger.warning("Layout LM '%s' non reconnu → standard-letter", layout_key)
            layout_key = "standard-letter"

        return {
            "name":          name,
            "label":         label,
            "category":      category,
            "description":   (
                inputs.description or ai_lm.get("description")
                or f"Lettre de motivation associée au modèle {cv_block['label']}."
            ),
            "primary_color": inputs.primary_color or ai_lm.get("primary_color") or cv_block["primary_color"],
            "font_family":   _to_google_font(
                inputs.font_family or ai_lm.get("font_family") or cv_block["font_family"]
            ),
            "layout_key":    layout_key,
        }

    @staticmethod
    def _extraction_meta(analysis: PDFAnalysis) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "fonts_detected": [
                {"name": f.name, "size": f.size, "weight": f.weight, "style": f.style}
                for f in analysis.fonts[:5]
            ],
            "color_palette": [
                {"hex": c.hex, "usage_pct": round(c.usage_pct, 1)}
                for c in analysis.colors[:6]
            ],
            "estimated_columns": analysis.estimated_columns,
            "sidebar_position": analysis.sidebar_position,
            "sidebar_color": analysis.sidebar_color_hex,
            "has_photo": analysis.has_photo,
            "photo_position": analysis.photo_position,
            "page_dimensions_mm": [round(analysis.width_mm, 1), round(analysis.height_mm, 1)],
            "is_a4": analysis.is_a4,
            "text_density_score": round(analysis.text_density_score, 3),
        }
        # NEW v3 : on remonte les mesures précises pour audit
        if analysis.margins:
            meta["margins_mm"] = {
                "top":    round(analysis.margins.top, 1),
                "bottom": round(analysis.margins.bottom, 1),
                "left":   round(analysis.margins.left, 1),
                "right":  round(analysis.margins.right, 1),
            }
        if analysis.sidebar:
            meta["sidebar_geometry"] = {
                "width_mm":      round(analysis.sidebar.width_mm, 1),
                "width_ratio":   round(analysis.sidebar.width_ratio, 3),
                "color":         analysis.sidebar.color_hex,
                "text_color":    analysis.sidebar.text_color_hex,
            }
        if analysis.header:
            meta["header_geometry"] = {
                "height_mm":      round(analysis.header.height_mm, 1),
                "background":     analysis.header.background_color_hex,
                "full_width_band": analysis.header.has_full_width_band,
            }
        if analysis.avg_section_gap_mm:
            meta["avg_section_gap_mm"] = round(analysis.avg_section_gap_mm, 1)
        return meta


# ─────────────────────────────────────────────────────────────────────────────
# Tags suggérés depuis l'analyse
# ─────────────────────────────────────────────────────────────────────────────

def _suggest_tags(analysis: PDFAnalysis, category: str) -> List[str]:
    tags = [category]

    primary_hex = primary_from_palette(analysis.colors).lower()
    if primary_hex.startswith("#"):
        try:
            r = int(primary_hex[1:3], 16)
            g = int(primary_hex[3:5], 16)
            b = int(primary_hex[5:7], 16)
            if b > r and b > g: tags.append("bleu")
            elif r > g and r > b and r > 150: tags.append("rouge")
            elif g > r and g > b: tags.append("vert")
            elif r > 200 and g > 200 and b > 200: tags.append("clair")
            elif r < 50 and g < 50 and b < 50: tags.append("sombre")
        except ValueError:
            pass

    if analysis.estimated_columns == 1:
        tags.append("une-colonne")
    else:
        tags.append("deux-colonnes")

    tags.append("avec-photo" if analysis.has_photo else "sans-photo")

    if analysis.sidebar_position:
        tags.append(f"sidebar-{analysis.sidebar_position}")

    seen, dedup = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            dedup.append(t)
    return dedup[:6]