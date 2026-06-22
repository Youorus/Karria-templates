#!/usr/bin/env python3
# template_generator/generate_templates.py
"""
Karria — Générateur de templates depuis PDF  (v4)
==================================================

Pipeline complet :
  PDF CV (+ optionnel PDF LM)
        ↓
  PDFAnalyzer v3 (marges, sidebar, header, gaps, couleurs, fonts)
        ↓
  Prompt chirurgical → Gemini  [passe 1]
        ↓
  Extraction (template.html, style.css, schema.json, data.json)
        ↓
  Validations multi-niveaux + retry auto (max 2)
        ↓
  Rendu Jinja2 → PNG  →  Gemini [passe 2 visual critic]  ← NOUVEAU
        ↓  corrections si nécessaire
  Construction infos.json
        ↓
  Écriture dossier (structure backend)

Structure produite :
  outputs/{cv_name}/
  ├── template.html
  ├── style.css
  ├── preview.pdf
  ├── schema.json
  ├── data.json
  └── infos.json
  └── lm/  (si LM fournie)
      ├── lm_template.html
      ├── lm_style.css
      ├── lm_preview.pdf
      ├── lm_schema.json
      └── lm_data.json

Usage CLI :
  python -m template_generator.generate_templates --cv ./inputs/cv.pdf
  python -m template_generator.generate_templates  # mode interactif
  python -m template_generator.generate_templates --batch
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
from io import BytesIO
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    from .pdf_analyzer import PDFAnalysis, PDFAnalyzer
except ImportError:  # exécution directe: python template_generator/generate_templates.py
    from pdf_analyzer import PDFAnalysis, PDFAnalyzer

# ── Imports locaux ──────────────────────────────────────────────────────────
# config.py est à la RACINE du projet (un niveau au-dessus de template_generator/)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings

try:
    from .prompts import (
        build_cv_prompt, build_lm_prompt,
        build_infos_prompt, build_visual_critic_prompt,
    )
    from .validators import (
        extract_files_from_response, extract_lm_files_from_response,
        validate_all,
    )
    from .infos_builder import InfosBuilder, CVHumanInputs, LMHumanInputs
    try:
        from .schema_limits import SchemaLimitsCalculator
    except ImportError:
        SchemaLimitsCalculator = None
except ImportError:  # exécution directe: python template_generator/generate_templates.py
    from prompts import (
        build_cv_prompt, build_lm_prompt,
        build_infos_prompt, build_visual_critic_prompt,
    )
    from validators import (
        extract_files_from_response, extract_lm_files_from_response,
        validate_all,
    )
    from infos_builder import InfosBuilder, CVHumanInputs, LMHumanInputs
    try:
        from schema_limits import SchemaLimitsCalculator
    except ImportError:
        SchemaLimitsCalculator = None


logger = logging.getLogger(__name__)


@dataclass
class VisualIssue:
    level: str  # "critical", "major", "minor"
    category: str
    message: str
    auto_fixable: bool = True


@dataclass
class VisualValidationReport:
    score: int
    passed: bool
    issues: List[VisualIssue]


def _px_from_mm(value_mm: Optional[float]) -> Optional[float]:
    """Convertit des millimètres PDF en pixels CSS à 96 dpi."""
    if value_mm is None:
        return None
    return value_mm * 96 / 25.4


def _extract_analysis_visual_metrics(analysis: PDFAnalysis) -> Dict[str, Any]:
    """Transforme PDFAnalysis en métriques visuelles comparables au rendu HTML."""
    metrics: Dict[str, Any] = {
        "width": 794,
        "height": 1123,
        "columns": getattr(analysis, "estimated_columns", None),
        "has_photo": getattr(analysis, "has_photo", False),
        "colors": getattr(analysis, "colors", []) or [],
    }

    sidebar = getattr(analysis, "sidebar", None)
    if sidebar:
        metrics["sidebar_width"] = _px_from_mm(getattr(sidebar, "width_mm", None))
        metrics["sidebar_position"] = getattr(sidebar, "position", None)

    margins = getattr(analysis, "margins", None)
    if margins:
        metrics["margin_left"] = _px_from_mm(getattr(margins, "left", None))
        metrics["margin_top"] = _px_from_mm(getattr(margins, "top", None))

    header = getattr(analysis, "header", None)
    if header:
        metrics["header_height"] = _px_from_mm(getattr(header, "height_mm", None))

    return metrics


def _score_visual_issues(issues: List[VisualIssue]) -> int:
    score = 100
    for issue in issues:
        if issue.level == "critical":
            score -= 25
        elif issue.level == "major":
            score -= 12
        else:
            score -= 5
    return max(score, 0)


def validate_visual_quality(
    rendered_metrics: Dict[str, Any],
    original_metrics: Dict[str, Any],
) -> VisualValidationReport:
    """
    Valide le rendu HTML par rapport aux contraintes A4 et aux métriques extraites du PDF.
    Cette validation ne remplace pas Gemini : elle sert de garde-fou mesurable avant/après correction.
    """
    issues: List[VisualIssue] = []

    width = rendered_metrics.get("width") or 0
    height = rendered_metrics.get("height") or 0
    scroll_width = rendered_metrics.get("scroll_width") or width
    scroll_height = rendered_metrics.get("scroll_height") or height
    overflowing_blocks = int(rendered_metrics.get("overflowing_blocks") or 0)
    min_line_height = rendered_metrics.get("min_line_height")
    avg_font_size = rendered_metrics.get("avg_font_size")

    # Validation A4 stricte à 96 dpi : 210x297mm ≈ 794x1123px.
    if abs(width - 794) > 20:
        issues.append(VisualIssue("major", "a4", f"Largeur A4 incorrecte : {width}px au lieu d'environ 794px"))
    if abs(height - 1123) > 30:
        issues.append(VisualIssue("major", "a4", f"Hauteur A4 incorrecte : {height}px au lieu d'environ 1123px"))
    if scroll_width > width + 5:
        issues.append(VisualIssue("critical", "overflow", f"Scroll horizontal détecté : {scroll_width}px > {width}px"))
    if scroll_height > height + 10:
        issues.append(VisualIssue("critical", "overflow", f"Scroll vertical détecté : {scroll_height}px > {height}px"))
    if overflowing_blocks > 0:
        issues.append(VisualIssue("critical", "overflow", f"{overflowing_blocks} bloc(s) sortent de la page"))

    # Validation layout : sidebar, header, marges.
    expected_sidebar_width = original_metrics.get("sidebar_width")
    rendered_sidebar_width = rendered_metrics.get("sidebar_width")
    if expected_sidebar_width and not rendered_sidebar_width:
        issues.append(VisualIssue("major", "layout", "Sidebar attendue dans le PDF mais non détectée dans le rendu"))
    elif expected_sidebar_width and rendered_sidebar_width:
        diff = abs(rendered_sidebar_width - expected_sidebar_width)
        if diff > 45:
            issues.append(VisualIssue("major", "layout", f"Sidebar trop différente : écart d'environ {diff:.0f}px"))

    expected_header_height = original_metrics.get("header_height")
    rendered_header_height = rendered_metrics.get("header_height")
    if expected_header_height and rendered_header_height:
        diff = abs(rendered_header_height - expected_header_height)
        if diff > 45:
            issues.append(VisualIssue("major", "layout", f"Header trop différent : écart d'environ {diff:.0f}px"))

    expected_margin_left = original_metrics.get("margin_left")
    rendered_margin_left = rendered_metrics.get("margin_left")
    if expected_margin_left and rendered_margin_left:
        diff = abs(rendered_margin_left - expected_margin_left)
        if diff > 35:
            issues.append(VisualIssue("minor", "layout", f"Marge gauche différente : écart d'environ {diff:.0f}px"))

    # Validation densité.
    if min_line_height and min_line_height < 1.10:
        issues.append(VisualIssue("minor", "density", f"Line-height trop serré : {min_line_height:.2f}"))
    if avg_font_size and avg_font_size < 8:
        issues.append(VisualIssue("major", "density", f"Texte trop petit en moyenne : {avg_font_size:.1f}px"))

    # Validation fidélité globale.
    expected_columns = original_metrics.get("columns")
    rendered_columns = rendered_metrics.get("columns")
    if expected_columns and rendered_columns and abs(int(rendered_columns) - int(expected_columns)) >= 1:
        issues.append(VisualIssue("major", "fidelity", f"Nombre de colonnes différent : attendu {expected_columns}, rendu {rendered_columns}"))

    score = _score_visual_issues(issues)
    return VisualValidationReport(score=score, passed=score >= 90, issues=issues)


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS JSON
# ═════════════════════════════════════════════════════════════════════════════

def extract_json_object(raw: str) -> Dict[str, Any]:
    """Extrait le 1er objet JSON d'une réponse IA (gère les fences Markdown)."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end   = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Impossible d'extraire un objet JSON depuis la réponse IA")
        text = text[start:end + 1]
    return json.loads(text)


# ═════════════════════════════════════════════════════════════════════════════
# GEMINI CALLER
# ═════════════════════════════════════════════════════════════════════════════

class GeminiCaller:
    """Wrapper Gemini avec retry + envoi PDF en images."""

    def __init__(self) -> None:
        settings.validate()
        from google import genai
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.model  = settings.MODEL

    # ── Envoi principal ──────────────────────────────────────────────────

    def call(self, pdf_path: str, prompt: str, *, retries: int = 2) -> str:
        """Appelle Gemini avec PDF converti en images + prompt textuel."""
        from google.genai import types

        parts: List[Any] = self._pdf_to_image_parts(pdf_path)
        parts.append(prompt)
        return self._call_parts(parts, retries=retries)

    def call_with_two_images(
        self,
        pdf_path: str,
        render_png_bytes: bytes,
        prompt: str,
        *,
        retries: int = 2,
    ) -> str:
        """
        Passe 2 — Visual critic.
        Envoie dans l'ordre :
          [images PDF original] [image rendu HTML] [prompt]
        Gemini voit le PDF d'abord (référence), puis le rendu actuel.
        """
        from google.genai import types

        parts: List[Any] = self._pdf_to_image_parts(pdf_path)
        parts.append(
            types.Part.from_bytes(data=render_png_bytes, mime_type="image/png")
        )
        parts.append(prompt)
        return self._call_parts(parts, retries=retries)

    # ── Internals ────────────────────────────────────────────────────────

    def _call_parts(self, parts: List[Any], *, retries: int) -> str:
        from google.genai import types

        for attempt in range(retries + 1):
            try:
                resp = self.client.models.generate_content(
                    model=self.model,
                    contents=parts,
                    config=types.GenerateContentConfig(
                        temperature=settings.TEMPERATURE,
                        max_output_tokens=settings.MAX_OUTPUT_TOKENS,
                    ),
                )

                if resp.candidates:
                    finish = resp.candidates[0].finish_reason
                    if finish and str(finish).endswith("MAX_TOKENS"):
                        raise ValueError("Réponse tronquée (MAX_TOKENS) — essaie de réduire le prompt")

                if not resp.text or not resp.text.strip():
                    raise ValueError("Réponse Gemini vide")

                return resp.text

            except Exception as e:
                logger.warning("⚠️  Gemini tentative %d/%d : %s", attempt + 1, retries + 1, e)
                if attempt == retries:
                    raise
                time.sleep(2 + attempt * 2)

        raise RuntimeError("Échec Gemini après tous les retries")

    def _pdf_to_image_parts(self, pdf_path: str) -> List[Any]:
        """Convertit un PDF en liste de Part Gemini (1 image PNG par page)."""
        from pdf2image    import convert_from_path
        from google.genai import types

        images = convert_from_path(pdf_path, dpi=settings.DPI, fmt="png")
        parts  = []
        for img in images:
            buf = BytesIO()
            img.save(buf, format="PNG")
            parts.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png"))
        return parts


# ═════════════════════════════════════════════════════════════════════════════
# RENDERER HTML → PNG  (pour la passe 2 visual critic)
# ═════════════════════════════════════════════════════════════════════════════

def render_html_to_png(html_content: str) -> Optional[bytes]:
    """
    Rend le template.html (avec data.json injectées) en PNG A4.
    Utilise playwright si disponible, sinon weasyprint, sinon None.
    Retourne les bytes PNG ou None si aucun renderer disponible.
    """
    # Tente playwright (meilleur rendu CSS)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 794, "height": 1123})  # A4 96dpi
            page.set_content(html_content, wait_until="networkidle")
            png = page.screenshot(full_page=False)
            browser.close()
            return png
    except ImportError:
        pass
    except Exception as e:
        logger.debug("playwright error: %s", e)

    # Fallback: weasyprint
    try:
        from weasyprint import HTML
        buf = BytesIO()
        HTML(string=html_content).write_png(buf)
        return buf.getvalue()
    except ImportError:
        pass
    except Exception as e:
        logger.debug("weasyprint error: %s", e)

    logger.warning(
        "⚠️  Aucun renderer HTML→PNG disponible. "
        "Installe playwright (`pip install playwright && playwright install chromium`) "
        "ou weasyprint pour activer la 2e passe visual critic."
    )
    return None


def extract_render_metrics(html_content: str) -> Optional[Dict[str, Any]]:
    """
    Mesure le rendu HTML réel dans Chromium : dimensions A4, overflow, sidebar, header,
    densité typographique et estimation du nombre de colonnes.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("⚠️  Playwright absent : métriques visuelles indisponibles.")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 794, "height": 1123})
            page.set_content(html_content, wait_until="networkidle")
            metrics = page.evaluate(
                """
                () => {
                  const pageEl = document.querySelector('.page') || document.body;
                  const pageRect = pageEl.getBoundingClientRect();
                  const all = Array.from(document.body.querySelectorAll('*'));

                  const visible = all.filter((el) => {
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 2 && r.height > 2 && s.display !== 'none' && s.visibility !== 'hidden';
                  });

                  const overflowing = visible.filter((el) => {
                    const r = el.getBoundingClientRect();
                    return r.right > 794 + 2 || r.bottom > 1123 + 2 || r.left < -2 || r.top < -2;
                  });

                  const sidebar = document.querySelector('.sidebar, aside, [class*="sidebar"], [class*="side-bar"], [class*="left-column"], [class*="right-column"]');
                  const sidebarRect = sidebar ? sidebar.getBoundingClientRect() : null;

                  const header = document.querySelector('header, .header, [class*="header"], .hero, [class*="profile"]');
                  const headerRect = header ? header.getBoundingClientRect() : null;

                  const textEls = visible.filter((el) => (el.innerText || '').trim().length > 0);
                  const fontSizes = [];
                  const lineHeights = [];
                  for (const el of textEls) {
                    const s = window.getComputedStyle(el);
                    const fs = parseFloat(s.fontSize || '0');
                    let lh = parseFloat(s.lineHeight || '0');
                    if (!lh || Number.isNaN(lh)) lh = fs * 1.2;
                    if (fs > 0) fontSizes.push(fs);
                    if (fs > 0 && lh > 0) lineHeights.push(lh / fs);
                  }

                  const leftBuckets = new Set(
                    visible
                      .filter((el) => el.getBoundingClientRect().width > 80 && el.getBoundingClientRect().height > 40)
                      .map((el) => Math.round(el.getBoundingClientRect().left / 80))
                  );

                  return {
                    width: Math.round(pageRect.width || 794),
                    height: Math.round(pageRect.height || 1123),
                    scroll_width: Math.round(document.documentElement.scrollWidth || document.body.scrollWidth || 794),
                    scroll_height: Math.round(document.documentElement.scrollHeight || document.body.scrollHeight || 1123),
                    margin_left: Math.round(pageRect.left || 0),
                    margin_top: Math.round(pageRect.top || 0),
                    sidebar_width: sidebarRect ? Math.round(sidebarRect.width) : null,
                    sidebar_left: sidebarRect ? Math.round(sidebarRect.left) : null,
                    header_height: headerRect ? Math.round(headerRect.height) : null,
                    overflowing_blocks: overflowing.length,
                    min_line_height: lineHeights.length ? Math.min(...lineHeights) : null,
                    avg_font_size: fontSizes.length ? fontSizes.reduce((a, b) => a + b, 0) / fontSizes.length : null,
                    columns: leftBuckets.size >= 2 ? 2 : 1,
                  };
                }
                """
            )
            browser.close()
            return metrics
    except Exception as e:
        logger.warning("⚠️  Extraction métriques visuelles échouée : %s", e)
        return None


def _inject_data_into_template(html: str, data_json: str) -> str:
    """Rend le template Jinja2 avec les données du data.json."""
    try:
        from jinja2 import Environment, Undefined

        def make_bars(level: int):
            return range(1, 6)  # itérable simple pour les barres

        env = Environment(undefined=Undefined)
        env.filters["make_bars"] = make_bars

        data = json.loads(data_json)
        rendered = env.from_string(html).render(**data)
        return rendered
    except Exception as e:
        logger.warning("⚠️  Rendu Jinja2 échoué : %s", e)
        return html  # fallback : HTML brut sans injection


# ═════════════════════════════════════════════════════════════════════════════
# VISUAL CRITIC — PASSE 2
# ═════════════════════════════════════════════════════════════════════════════

def _parse_critic_response(raw: str) -> Tuple[bool, List[str], Optional[str], Optional[str]]:
    """
    Parse la réponse du visual critic.
    Retourne (is_ok, diagnosis_lines, corrected_html, corrected_css).
    is_ok = True si le diagnosis dit "OK".
    """
    # Extrait le bloc diagnosis
    diag_match = re.search(r"```diagnosis\s*(.*?)\s*```", raw, re.S)
    diagnosis_raw = diag_match.group(1).strip() if diag_match else ""

    is_ok = "OK —" in diagnosis_raw or diagnosis_raw.strip().startswith("OK")
    diagnosis_lines = [l.strip("- ").strip() for l in diagnosis_raw.splitlines() if l.strip()]

    if is_ok:
        return True, diagnosis_lines, None, None

    # Extrait HTML et CSS corrigés
    html_match = re.search(r"```html\s*(.*?)\s*```", raw, re.S)
    css_match  = re.search(r"```css\s*(.*?)\s*```",  raw, re.S)

    corrected_html = html_match.group(1).strip() if html_match else None
    corrected_css = css_match.group(1).strip() if css_match else None

    return False, diagnosis_lines, corrected_html, corrected_css


def run_visual_critic(
    ai:        GeminiCaller,
    pdf_path:  str,
    files:     Dict[str, str],
    analysis:  PDFAnalysis,
    doc_type:  str = "CV",
) -> Dict[str, str]:
    """
    Passe 2 : rend le HTML → PNG, envoie PDF + PNG + prompt à Gemini,
    et remplace le HTML/CSS si des corrections sont nécessaires.
    Retourne le dict `files` potentiellement mis à jour.
    """
    html_key = "template.html" if doc_type == "CV" else "lm_template.html"
    css_key  = "style.css"     if doc_type == "CV" else "lm_style.css"
    data_key = "data.json"     if doc_type == "CV" else "lm_data.json"

    html = files.get(html_key, "")
    css  = files.get(css_key, "")
    data = files.get(data_key, "{}")

    logger.info("🎨 Passe 2 : rendu HTML → PNG pour visual critic…")
    html_for_render = html
    if css and "</head>" in html_for_render:
        html_for_render = html_for_render.replace("</head>", f"<style>\n{css}\n</style>\n</head>")
    elif css:
        html_for_render = f"<style>\n{css}\n</style>\n" + html_for_render

    rendered_html = _inject_data_into_template(html_for_render, data)
    rendered_metrics = extract_render_metrics(rendered_html)
    original_metrics = _extract_analysis_visual_metrics(analysis)

    visual_report: Optional[VisualValidationReport] = None
    if rendered_metrics:
        visual_report = validate_visual_quality(
            rendered_metrics=rendered_metrics,
            original_metrics=original_metrics,
        )
        logger.info("📏 Score visuel mesurable %s : %s/100", doc_type, visual_report.score)
        for issue in visual_report.issues:
            logger.warning("   • [%s/%s] %s", issue.level, issue.category, issue.message)

    png_bytes = render_html_to_png(rendered_html)

    if png_bytes is None:
        logger.warning("⚠️  Passe 2 skippée — pas de renderer HTML→PNG disponible.")
        return files

    logger.info("🤖 Passe 2 : envoi PDF + rendu PNG à Gemini pour critique visuelle…")
    metric_context = ""
    if visual_report and visual_report.issues:
        metric_context = "\n\nCONTRAINTES MESURÉES À CORRIGER EN PRIORITÉ :\n" + "\n".join(
            f"- [{issue.level}/{issue.category}] {issue.message}"
            for issue in visual_report.issues
        )

    prompt = build_visual_critic_prompt(analysis, html, css) + metric_context

    try:
        raw = ai.call_with_two_images(pdf_path, png_bytes, prompt, retries=1)
    except Exception as e:
        logger.warning("⚠️  Passe 2 échouée : %s — on garde la passe 1.", e)
        return files

    is_ok, diagnosis, corrected_html, corrected_css = _parse_critic_response(raw)

    if is_ok:
        logger.info("✅ Passe 2 : rendu fidèle, aucune correction nécessaire.")
        return files

    logger.info("🔧 Passe 2 : corrections détectées :")
    for line in diagnosis:
        logger.info("   • %s", line)

    updated = dict(files)
    if corrected_html:
        updated[html_key] = corrected_html
        logger.info("   → HTML mis à jour")
    if corrected_css:
        updated[css_key] = corrected_css
        logger.info("   → CSS mis à jour")

    ok, errors = validate_all(updated, doc_type=doc_type)
    if not ok:
        logger.warning(
            "⚠️  Passe 2 : les corrections visuelles ont produit un template invalide. "
            "On conserve la version précédente. Erreurs :\n  %s",
            "\n  ".join(errors),
        )
        return files

    return updated


# ═════════════════════════════════════════════════════════════════════════════
# VISUAL QUALITY LOOP
# ═════════════════════════════════════════════════════════════════════════════
def run_visual_quality_loop(
    ai: GeminiCaller,
    pdf_path: str,
    files: Dict[str, str],
    analysis: PDFAnalysis,
    doc_type: str = "CV",
    max_rounds: int = 3,
) -> Dict[str, str]:
    """
    Boucle qualité visuelle :
      1. rend le template,
      2. demande une critique visuelle,
      3. applique les corrections uniquement si elles restent techniquement valides,
      4. recommence au maximum `max_rounds` fois.
    """
    current = dict(files)

    for round_index in range(max_rounds):
        logger.info(
            "🎯 Quality loop %s — passe visuelle %d/%d",
            doc_type,
            round_index + 1,
            max_rounds,
        )
        before_html = current.get("template.html" if doc_type == "CV" else "lm_template.html", "")
        before_css = current.get("style.css" if doc_type == "CV" else "lm_style.css", "")

        updated = run_visual_critic(
            ai=ai,
            pdf_path=pdf_path,
            files=current,
            analysis=analysis,
            doc_type=doc_type,
        )

        after_html = updated.get("template.html" if doc_type == "CV" else "lm_template.html", "")
        after_css = updated.get("style.css" if doc_type == "CV" else "lm_style.css", "")

        if before_html == after_html and before_css == after_css:
            logger.info("✅ Quality loop %s : aucune nouvelle correction nécessaire.", doc_type)
            return updated

        current = updated

    logger.info("🏁 Quality loop %s terminée après %d passe(s).", doc_type, max_rounds)
    return current


# ═════════════════════════════════════════════════════════════════════════════
# TEMPLATE GENERATOR — PASSE 1
# ═════════════════════════════════════════════════════════════════════════════

class TemplateGenerator:
    """
    Orchestre la génération d'un template (passe 1 : Gemini → extraction → validation).
    La passe 2 (visual critic) est gérée séparément dans `generate()`.
    """

    def __init__(self, ai: GeminiCaller) -> None:
        self.ai       = ai
        self.analyzer = PDFAnalyzer()

    def generate_cv(
        self,
        pdf_path:   str,
        layout_key: Optional[str] = None,
    ) -> Tuple[Dict[str, str], PDFAnalysis]:
        return self._generate(pdf_path, doc_type="CV", layout_key=layout_key)

    def generate_lm(
        self,
        pdf_path:   str,
        layout_key: str = "standard-letter",
    ) -> Tuple[Dict[str, str], PDFAnalysis]:
        return self._generate(pdf_path, doc_type="LM", layout_key=layout_key)

    def _generate(
        self,
        pdf_path:   str,
        doc_type:   str,
        layout_key: Optional[str],
    ) -> Tuple[Dict[str, str], PDFAnalysis]:
        # 1. Pré-analyse PDF (v3 avec mesures précises)
        logger.info("🔍 Analyse PDF %s : %s", doc_type, pdf_path)
        analysis = self.analyzer.analyze(pdf_path)

        # Détermination automatique du layout si non fourni
        if not layout_key and doc_type == "CV":
            try:
                from .infos_builder import detect_layout_key_cv
            except ImportError:  # exécution directe
                from infos_builder import detect_layout_key_cv
            layout_key = detect_layout_key_cv(analysis)

        logger.info(
            "  → %d fonts, %d couleurs, photo=%s, %d colonnes, "
            "marges=%s, sidebar=%s",
            len(analysis.fonts), len(analysis.colors),
            analysis.has_photo, analysis.estimated_columns,
            f"{analysis.margins.left:.0f}/{analysis.margins.top:.0f}mm" if analysis.margins else "?",
            f"{analysis.sidebar.width_mm:.0f}mm {analysis.sidebar.position}" if analysis.sidebar else "aucune",
        )

        # 2. Calcul des limites physiques réelles du template.
        # Le schema.json reste le contrat de données, mais ces limites deviennent
        # le budget physique maximal autorisé pour éviter les débordements A4.
        schema_limits = None
        if doc_type == "CV":
            if SchemaLimitsCalculator is None:
                logger.warning(
                    "⚠️  SchemaLimitsCalculator indisponible : fallback vers les limites du prompt. "
                    "Ajoute template_generator/schema_limits.py pour activer les limites dynamiques."
                )
            else:
                schema_limits = SchemaLimitsCalculator.from_analysis(
                    analysis,
                    layout_key=layout_key or "two-column-left-sidebar",
                    target_pages=1,
                )
                logger.info(
                    "📐 Limites physiques CV calculées : summary≤%d, exp≤%d, desc≤%d, "
                    "edu≤%d, skills≤%d, langs≤%d, refs≤%d — %s",
                    schema_limits.summary_max_length,
                    schema_limits.experiences_max_items,
                    schema_limits.experience_description_max_length,
                    schema_limits.education_max_items,
                    schema_limits.skills_max_items,
                    schema_limits.languages_max_items,
                    schema_limits.references_max_items,
                    schema_limits.reason,
                )

        # 3. Prompt
        if doc_type == "CV":
            try:
                prompt = build_cv_prompt(
                    analysis,
                    expected_layout=layout_key or "two-column-left-sidebar",
                    schema_limits=schema_limits,
                )
            except TypeError:
                prompt = build_cv_prompt(analysis, expected_layout=layout_key or "two-column-left-sidebar")
                if schema_limits and hasattr(schema_limits, "to_prompt_block"):
                    prompt += "\n\n" + schema_limits.to_prompt_block()
        else:
            prompt = build_lm_prompt(analysis, expected_layout=layout_key or "standard-letter")

        # 3. Boucle génération + validation
        last_errors: List[str] = []
        last_response: str     = ""

        for attempt in range(settings.MAX_RETRIES + 1):
            full_prompt = prompt
            if attempt > 0 and last_errors:
                full_prompt = self._build_correction_prompt(prompt, last_errors, last_response)

            logger.info(
                "🤖 Génération IA %s — tentative %d/%d",
                doc_type, attempt + 1, settings.MAX_RETRIES + 1,
            )
            raw           = self.ai.call(pdf_path, full_prompt, retries=2)
            last_response = raw

            extractor = extract_files_from_response if doc_type == "CV" else extract_lm_files_from_response
            files = extractor(raw)

            # Auto-correct common Gemini mistakes before formal validation
            if doc_type == "CV":
                files = _normalize_cv_generated_files(files, schema_limits=schema_limits)

            try:
                ok, errors = validate_all(files, doc_type=doc_type, schema_limits=schema_limits)
            except TypeError:
                # Compatibilité avec une ancienne version de validators.py
                ok, errors = validate_all(files, doc_type=doc_type)

            if ok:
                logger.info("✅ %s validé en %d tentative(s)", doc_type, attempt + 1)
                return files, analysis

            last_errors = errors
            logger.warning(
                "❌ Validation %s échouée :\n  %s", doc_type, "\n  ".join(errors)
            )

        # Toutes les tentatives ont échoué
        raise RuntimeError(
            f"Génération {doc_type} échouée après {settings.MAX_RETRIES + 1} tentatives.\n"
            "Dernières erreurs :\n  - " + "\n  - ".join(last_errors)
        )

    @staticmethod
    def _build_correction_prompt(
        original_prompt: str,
        errors:          List[str],
        last_response:   str,
    ) -> str:
        errors_str        = "\n  - ".join(errors)
        truncated_response = last_response[:1500] + ("…" if len(last_response) > 1500 else "")

        return original_prompt + f"""

═══════════════════════════════════════════════════════════════════════
🚨 ÉCHEC VALIDATION — CORRIGE CES ERREURS PRÉCISES
═══════════════════════════════════════════════════════════════════════
Ta réponse précédente a échoué :

  - {errors_str}

Extrait :
{truncated_response}

Corrige UNIQUEMENT ces erreurs. Réémets les 4 blocs COMPLETS.
"""


# ═════════════════════════════════════════════════════════════════════════════
# NORMALISATION POST-IA — CV
# ═════════════════════════════════════════════════════════════════════════════

def _normalize_cv_generated_files(files: Dict[str, str], schema_limits=None) -> Dict[str, str]:
    """
    Corrige automatiquement les erreurs récurrentes de Gemini avant validation :
      1. Noms de variables incorrects (ex: exp.details → exp.description)
      2. maxItems/maxLength trop grands dans schema.json (cap aux limites physiques)
      3. Valeurs trop longues dans data.json (troncature au maxLength du schema)

    Appelée après chaque extraction Gemini, avant validate_all().
    """
    if not files:
        return files

    html       = files.get("template.html", "")
    data_raw   = files.get("data.json", "{}")
    schema_raw = files.get("schema.json", "{}")

    try:
        data = json.loads(data_raw)
    except Exception:
        data = {}

    try:
        schema = json.loads(schema_raw)
    except Exception:
        schema = {}

    # ── 1. Noms de variables — remplace les alias Gemini par les noms canoniques ──
    exp_list = data.get("experiences", [])
    if exp_list and isinstance(exp_list[0], dict):
        exp_keys = set(exp_list[0].keys())
        for alias in ("details", "detail", "desc", "content", "body", "text", "tasks"):
            if "description" in exp_keys and alias not in exp_keys:
                html = re.sub(
                    r'\{{\s*(\w+)\.' + re.escape(alias) + r'\s*}}',
                    r'{{ \1.description }}',
                    html,
                )
    files["template.html"] = html

    # ── 2. Cap schema.json maxItems/maxLength aux limites physiques ──────────
    if schema_limits:
        fields = schema.get("fields", {})

        def _cap_items(field_name: str, limit_attr: str, default: int):
            f = fields.get(field_name)
            if not isinstance(f, dict):
                return
            limit = getattr(schema_limits, limit_attr, default)
            current = f.get("maxItems")
            if current is None or current > limit:
                f["maxItems"] = limit

        def _cap_length(field_name: str, limit_attr: str, default: int):
            f = fields.get(field_name)
            if not isinstance(f, dict):
                return
            limit = getattr(schema_limits, limit_attr, default)
            current = f.get("maxLength")
            if current is None or current > limit:
                f["maxLength"] = limit

        _cap_items("experiences",  "experiences_max_items",  4)
        _cap_items("education",    "education_max_items",    3)
        _cap_items("skills",       "skills_max_items",      10)
        _cap_items("languages",    "languages_max_items",    4)
        _cap_items("interests",    "interests_max_items",    4)
        _cap_items("references",   "references_max_items",   0)
        _cap_length("summary",     "summary_max_length",   300)

        # Cap experience description maxLength (nested path)
        exp_field = fields.get("experiences")
        if isinstance(exp_field, dict):
            item = exp_field.get("item", {})
            if isinstance(item, dict):
                desc = item.get("fields", {}).get("description", {})
                if isinstance(desc, dict):
                    dl = getattr(schema_limits, "experience_description_max_length", 200)
                    if desc.get("maxLength") is None or desc["maxLength"] > dl:
                        desc["maxLength"] = dl

        schema["fields"] = fields
        files["schema.json"] = json.dumps(schema, ensure_ascii=False, indent=2)

    # ── 3. Tronque data.json aux limites du schema (évite les erreurs data↔schema) ─
    schema_fields = schema.get("fields", {})

    def _max_length(field_name: str) -> Optional[int]:
        f = schema_fields.get(field_name)
        return f.get("maxLength") if isinstance(f, dict) else None

    def _max_items(field_name: str) -> Optional[int]:
        f = schema_fields.get(field_name)
        return f.get("maxItems") if isinstance(f, dict) else None

    def _trunc(s: str, limit: int) -> str:
        return s[:limit - 1] + "…" if len(s) > limit else s

    summary_limit = _max_length("summary")
    if summary_limit and isinstance(data.get("summary"), str):
        data["summary"] = _trunc(data["summary"], summary_limit)

    # Truncate experience descriptions
    exp_desc_limit = None
    exp_field = schema_fields.get("experiences")
    if isinstance(exp_field, dict):
        desc_field = exp_field.get("item", {}).get("fields", {}).get("description", {})
        exp_desc_limit = desc_field.get("maxLength") if isinstance(desc_field, dict) else None

    if exp_desc_limit:
        for exp in data.get("experiences", []):
            if isinstance(exp, dict) and isinstance(exp.get("description"), str):
                exp["description"] = _trunc(exp["description"], exp_desc_limit)

    # Truncate arrays to maxItems
    for arr_name in ("experiences", "education", "skills", "languages", "interests", "references"):
        limit = _max_items(arr_name)
        if limit is not None and isinstance(data.get(arr_name), list):
            data[arr_name] = data[arr_name][:limit]

    files["data.json"] = json.dumps(data, ensure_ascii=False, indent=2)

    return files


# ═════════════════════════════════════════════════════════════════════════════
# NORMALISATION POST-IA — LM
# ═════════════════════════════════════════════════════════════════════════════

def normalize_lm_template_files(files: Dict[str, str]) -> Dict[str, str]:
    """Filet de sécurité : injecte un CSS A4 strict dans les templates LM trop hauts."""
    if not files:
        return files

    safety_css = """
/* Karria LM safety — A4 strict */
@page { size: A4; margin: 0; }
html, body {
  width: 210mm !important; height: 297mm !important;
  margin: 0 !important; padding: 0 !important;
  overflow: hidden !important; background: white !important;
}
.page {
  width: 210mm !important; height: 297mm !important;
  max-height: 297mm !important; margin: 0 !important;
  padding: 16mm 18mm !important; overflow: hidden !important;
  box-shadow: none !important; background: white !important;
  display: flex !important; flex-direction: column !important;
}
.header, .letter-header, .lm-header, [class*="header"] {
  margin-top: 0 !important; margin-bottom: 10mm !important;
  padding-top: 0 !important; max-height: 48mm !important;
}
.sender-info .full-name, .sender-info h1, .full-name, h1 {
  font-size: 30pt !important; line-height: 1 !important;
  margin-top: 0 !important; margin-bottom: 6px !important;
}
.content, .letter-body, .lm-body, main {
  flex: 1 1 auto !important; overflow: hidden !important;
  font-size: 10pt !important; line-height: 1.36 !important;
}
p, .paragraph { line-height: 1.36 !important; }
.paragraph { margin-top: 0 !important; margin-bottom: 7px !important; }
.closing { margin-top: 10px !important; margin-bottom: 10px !important; }
"""

    css  = files.get("lm_style.css", "")
    html = files.get("lm_template.html", "")

    if css:
        files["lm_style.css"] = css + "\n\n" + safety_css

    if html:
        if "</style>" in html:
            html = html.replace("</style>", f"\n{safety_css}\n</style>")
        elif "</head>" in html:
            html = html.replace("</head>", f"<style>{safety_css}</style>\n</head>")
        else:
            html = f"<style>{safety_css}</style>\n" + html
        files["lm_template.html"] = html

    return files


# ═════════════════════════════════════════════════════════════════════════════
# FOLDER WRITER
# ═════════════════════════════════════════════════════════════════════════════

class FolderWriter:
    """Écrit la structure de dossier attendue par le backend."""

    @staticmethod
    def write(
        output_root:    Path,
        cv_name:        str,
        cv_files:       Dict[str, str],
        cv_pdf_source:  str,
        infos:          Dict[str, Any],
        lm_files:       Optional[Dict[str, str]] = None,
        lm_pdf_source:  Optional[str] = None,
    ) -> Path:
        root = output_root / cv_name
        root.mkdir(parents=True, exist_ok=True)

        for fname, content in cv_files.items():
            (root / fname).write_text(content, encoding="utf-8")

        if cv_pdf_source and Path(cv_pdf_source).is_file():
            shutil.copy2(cv_pdf_source, root / "preview.pdf")
        else:
            logger.warning("⚠️  PDF source manquant — preview.pdf non copié")

        (root / "infos.json").write_text(
            json.dumps(infos, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        if lm_files:
            lm_dir = root / "lm"
            lm_dir.mkdir(exist_ok=True)
            for fname, content in lm_files.items():
                (lm_dir / fname).write_text(content, encoding="utf-8")
            if lm_pdf_source and Path(lm_pdf_source).is_file():
                shutil.copy2(lm_pdf_source, lm_dir / "lm_preview.pdf")

        return root.resolve()


# ═════════════════════════════════════════════════════════════════════════════
# PIPELINE PUBLIC
# ═════════════════════════════════════════════════════════════════════════════

def generate(
    cv_pdf_path:        str,
    label:              Optional[str]  = None,
    output_dir:         Optional[Path] = None,
    *,
    name:               Optional[str]  = None,
    category:           Optional[str]  = None,
    description:        Optional[str]  = None,
    primary_color:      Optional[str]  = None,
    font_family:        Optional[str]  = None,
    is_premium:         bool           = False,
    price:              Optional[float]= None,
    is_active:          bool           = True,
    tags:               Optional[List[str]] = None,
    review_description: Optional[str]  = None,
    layout_key:         Optional[str]  = None,
    lm_pdf_path:        Optional[str]  = None,
    lm_label:           Optional[str]  = None,
    lm_layout_key:      str            = "standard-letter",
    skip_visual_critic: bool           = False,
) -> Path:
    """
    Génération complète d'un template Karria depuis un PDF CV (+ optionnel LM).

    Returns:
        Path absolu du dossier créé dans output_dir.
    """
    settings.validate()
    output_dir = output_dir or settings.OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if not Path(cv_pdf_path).is_file():
        raise FileNotFoundError(f"CV PDF introuvable : {cv_pdf_path}")
    if lm_pdf_path and not Path(lm_pdf_path).is_file():
        raise FileNotFoundError(f"LM PDF introuvable : {lm_pdf_path}")

    ai        = GeminiCaller()
    generator = TemplateGenerator(ai)

    # ── 1. Génération CV (passe 1) ───────────────────────────────────────
    print(f"\n📄 [1/5] Génération CV  : {Path(cv_pdf_path).name}")
    cv_files, cv_analysis = generator.generate_cv(cv_pdf_path, layout_key=layout_key)

    # ── 2. Passe 2 visual critic CV ──────────────────────────────────────
    use_critic = settings.ENABLE_VISUAL_CRITIC and not skip_visual_critic
    if use_critic:
        print("🎨 [2/5] Quality loop visuelle CV…")
        cv_files = run_visual_quality_loop(ai, cv_pdf_path, cv_files, cv_analysis, doc_type="CV")
    else:
        print("⏭️  [2/5] Visual critic désactivé.")

    # ── 3. Génération LM ─────────────────────────────────────────────────
    lm_files    = None
    lm_analysis = None

    if lm_pdf_path:
        print(f"\n✉️  [3/5] Génération LM  : {Path(lm_pdf_path).name}")
        lm_files, lm_analysis = generator.generate_lm(lm_pdf_path, layout_key=lm_layout_key)
        lm_files = normalize_lm_template_files(lm_files)

        if use_critic:
            print("🎨      Quality loop visuelle LM…")
            lm_files = run_visual_quality_loop(ai, lm_pdf_path, lm_files, lm_analysis, doc_type="LM")
    else:
        print("⏭️  [3/5] Pas de LM.")

    # ── 4. Métadonnées (infos.json) ──────────────────────────────────────
    print("\n🧠 [4/5] Génération métadonnées infos.json…")
    infos_prompt = build_infos_prompt(
        analysis=cv_analysis,
        cv_files=cv_files,
        lm_analysis=lm_analysis,
        lm_files=lm_files,
    )
    ai_meta = extract_json_object(ai.call(cv_pdf_path, infos_prompt, retries=2))

    cv_inputs = CVHumanInputs(
        label=label, name=name, category=category,
        description=description, primary_color=primary_color,
        font_family=font_family, is_premium=is_premium,
        price=price, is_active=is_active, tags=tags,
        review_description=review_description, layout_key=layout_key,
    )
    lm_inputs = LMHumanInputs(label=lm_label, layout_key=lm_layout_key)

    infos = InfosBuilder.build(
        cv_analysis=cv_analysis,
        cv_inputs=cv_inputs,
        ai_meta=ai_meta,
        lm_analysis=lm_analysis,
        lm_inputs=lm_inputs,
    )

    # ── 5. Écriture dossier ──────────────────────────────────────────────
    cv_name_final = infos["cv"]["name"]
    print(f"\n💾 [5/5] Écriture : {output_dir}/{cv_name_final}/")

    final_path = FolderWriter.write(
        output_root=output_dir,
        cv_name=cv_name_final,
        cv_files=cv_files,
        cv_pdf_source=cv_pdf_path,
        infos=infos,
        lm_files=lm_files,
        lm_pdf_source=lm_pdf_path,
    )

    print(f"\n🎉 Template généré : {final_path}")
    return final_path


# ═════════════════════════════════════════════════════════════════════════════
# SÉLECTION INTERACTIVE DE PDF
# ═════════════════════════════════════════════════════════════════════════════

def _browse_for_pdf(prompt_text: str, start_dir: Optional[str] = None, *, allow_skip: bool = False) -> str:
    """
    Navigation interactive dans le filesystem pour choisir un PDF.
    Retourne le chemin absolu du PDF choisi, ou "" si skip.
    """
    candidates = [
        Path(start_dir).expanduser() if start_dir else None,
        settings.PDF_SEARCH_DIR.expanduser(),
        Path.home() / "Documents" / "Karria_templates" / "templates",
        Path.cwd() / "templates",
        Path.cwd(),
    ]
    root = next((c for c in candidates if c and c.exists() and c.is_dir()), Path.cwd())
    current = root.resolve()

    while True:
        dirs = sorted(
            [p for p in current.iterdir() if p.is_dir() and not p.name.startswith(".")],
            key=lambda p: p.name.lower(),
        )
        pdfs = sorted(
            [p for p in current.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"],
            key=lambda p: p.name.lower(),
        )

        print(f"\n{'─' * 68}")
        print(f"📂 {current}")
        print("─" * 68)

        entries: List[Tuple[str, Path]] = []
        if dirs:
            print("📁 Dossiers :")
            for d in dirs:
                entries.append(("dir", d))
                print(f"  [{len(entries):2d}] 📁 {d.name}/")
        if pdfs:
            print("📄 PDFs :")
            for p in pdfs:
                entries.append(("pdf", p))
                print(f"  [{len(entries):2d}] 📄 {p.name}")
        if not entries:
            print("  (dossier vide)")

        cmds = "[n] ouvrir/choisir  [..] parent  [/] racine  [q] quitter"
        if allow_skip:
            cmds += "  [skip] passer"
        print(f"\n{cmds}")

        choice = input(f"{prompt_text} > ").strip()
        low    = choice.lower()

        if low == "q":
            sys.exit("Annulé.")
        if allow_skip and low in ("skip", "s", ""):
            return ""
        if choice == "/":
            current = root; continue
        if choice == "..":
            current = current.parent; continue
        if low == "pdf" and len(pdfs) == 1:
            return str(pdfs[0].resolve())
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(entries):
                kind, path = entries[idx]
                if kind == "dir":
                    current = path.resolve(); continue
                return str(path.resolve())
        # chemin direct
        if choice:
            cand = Path(choice).expanduser()
            if not cand.is_absolute():
                cand = current / choice
            cand = cand.resolve()
            if cand.is_dir():
                current = cand; continue
            if cand.is_file() and cand.suffix.lower() == ".pdf":
                return str(cand)
        print("❌ Choix invalide.")


# ═════════════════════════════════════════════════════════════════════════════
# MODES INTERACTIFS
# ═════════════════════════════════════════════════════════════════════════════

def _ask_premium() -> Tuple[bool, Optional[float]]:
    is_prem = input("Premium ? [y/N] ").strip().lower() in ("y", "yes", "o", "oui")
    price   = None
    if is_prem:
        while True:
            raw = input("Prix (ex: 4.99, Entrée = aucun) : ").strip().replace(",", ".")
            if not raw:
                break
            try:
                price = float(raw); break
            except ValueError:
                print("❌ Prix invalide.")
    return is_prem, price


def _interactive_single() -> argparse.Namespace:
    """Mode simple : 1 CV + LM optionnelle."""
    print("=" * 60)
    print("  Karria — Générateur de templates")
    print("=" * 60)

    cv = _browse_for_pdf("CV")
    if not cv:
        sys.exit("PDF CV obligatoire.")
    print(f"✅ CV : {cv}")

    lm = None
    if input("\nAjouter une lettre de motivation ? [y/N] ").strip().lower() in ("y", "yes", "o", "oui"):
        lm = _browse_for_pdf("Lettre", start_dir=str(Path(cv).parent), allow_skip=True) or None
        if lm:
            print(f"✅ LM : {lm}")

    premium, price = _ask_premium()

    out = input(f"\nDossier de sortie [{settings.OUTPUT_DIR}] : ").strip()
    return argparse.Namespace(
        cv=cv, lm=lm, label=None, name=None, category=None,
        description=None, primary_color=None, font_family=None,
        premium=premium, price=price, inactive=False,
        tags=None, review_description=None, layout=None,
        lm_label=None, lm_layout="standard-letter",
        output=out or str(settings.OUTPUT_DIR),
        batch=False, verbose=False, no_critic=False,
    )


def _interactive_batch() -> argparse.Namespace:
    """Mode batch : file d'attente de plusieurs CV+LM."""
    print("=" * 60)
    print("  Karria — Mode batch")
    print("=" * 60)
    print("Ajoute autant de paires CV+LM que tu veux.\n")

    out   = input(f"Dossier de sortie [{settings.OUTPUT_DIR}] : ").strip() or str(settings.OUTPUT_DIR)
    jobs: List[Dict[str, Any]] = []

    while True:
        print(f"\n➕ Job #{len(jobs) + 1}")
        cv = _browse_for_pdf("CV")
        if not cv:
            print("PDF CV obligatoire."); continue

        lm = None
        if input("Ajouter une LM pour ce CV ? [y/N] ").strip().lower() in ("y", "yes", "o", "oui"):
            lm = _browse_for_pdf("Lettre", start_dir=str(Path(cv).parent), allow_skip=True) or None

        premium, price = _ask_premium()
        jobs.append({"cv": cv, "lm": lm, "premium": premium, "price": price})

        print("\n📦 File :")
        for i, j in enumerate(jobs, 1):
            lm_name    = Path(j["lm"]).name if j.get("lm") else "—"
            price_txt  = j["price"] if j.get("premium") else "gratuit"
            print(f"  [{i}] CV={Path(j['cv']).name}  LM={lm_name}  prix={price_txt}")

        if input("\nAjouter un autre CV ? [Y/n] ").strip().lower() in ("n", "no", "non"):
            break

    if not jobs:
        sys.exit("File vide.")

    return argparse.Namespace(
        batch=True, jobs=jobs, output=out,
        inactive=False, verbose=False, no_critic=False,
    )


# ═════════════════════════════════════════════════════════════════════════════
# BATCH RUNNER
# ═════════════════════════════════════════════════════════════════════════════

def _run_batch(args: argparse.Namespace, output_dir: Path) -> None:
    jobs    = getattr(args, "jobs", [])
    total   = len(jobs)
    success: List[Path]                = []
    failed:  List[Tuple[int, str]]     = []

    print(f"\n🚀 Batch : {total} template(s)")
    for idx, job in enumerate(jobs, 1):
        print(f"\n{'═' * 68}")
        print(f"▶️  Job {idx}/{total} — {Path(job['cv']).name}")
        print("═" * 68)
        try:
            path = generate(
                cv_pdf_path=job["cv"],
                output_dir=output_dir,
                is_premium=bool(job.get("premium")),
                price=job.get("price"),
                is_active=not getattr(args, "inactive", False),
                lm_pdf_path=job.get("lm"),
                skip_visual_critic=getattr(args, "no_critic", False),
            )
            success.append(path)
            print(f"✅ Job {idx} terminé : {path}")
        except Exception as e:
            failed.append((idx, str(e)))
            print(f"❌ Job {idx} échoué : {e}")

    print(f"\n{'=' * 68}")
    print(f"📊 Batch terminé — ✅ {len(success)}  ❌ {len(failed)}")
    for p in success:
        print(f"  ✅ {p}")
    for i, err in failed:
        print(f"  ❌ Job {i} : {err}")


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Générateur de templates Karria depuis PDF",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("--cv",                 help="Chemin du PDF CV")
    p.add_argument("--lm",                 default=None, help="Chemin du PDF LM (optionnel)")
    p.add_argument("--label",              help="Label (sinon IA le choisit)")
    p.add_argument("--name",               default=None, help="Slug (auto si absent)")
    p.add_argument("--category",           default=None)
    p.add_argument("--description",        default=None)
    p.add_argument("--primary-color",      dest="primary_color", default=None)
    p.add_argument("--font-family",        dest="font_family", default=None)
    p.add_argument("--premium",            action="store_true")
    p.add_argument("--price",              type=float, default=None)
    p.add_argument("--inactive",           action="store_true")
    p.add_argument("--tags",               default=None, help="Tags séparés par virgule")
    p.add_argument("--review-description", dest="review_description", default=None)
    p.add_argument("--layout",             default=None, help="Layout key (auto si absent)")
    p.add_argument("--lm-label",           dest="lm_label", default=None)
    p.add_argument("--lm-layout",          dest="lm_layout", default="standard-letter")
    p.add_argument("--output", "-o",       default=None)
    p.add_argument("--batch",              action="store_true", help="Mode file d'attente interactif")
    p.add_argument("--no-critic",          dest="no_critic", action="store_true",
                   help="Désactiver la passe 2 visual critic")
    p.add_argument("--verbose", "-v",      action="store_true")
    return p


def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    if args.batch:
        args = _interactive_batch()
    elif not args.cv:
        args = _interactive_single()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    output_dir = Path(args.output or str(settings.OUTPUT_DIR)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if getattr(args, "batch", False):
        try:
            _run_batch(args, output_dir)
        except Exception as e:
            logger.error("💥 ÉCHEC BATCH : %s", e, exc_info=args.verbose)
            sys.exit(1)
        return

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None

    try:
        generate(
            cv_pdf_path=args.cv,
            label=args.label,
            output_dir=output_dir,
            name=args.name,
            category=args.category,
            description=args.description,
            primary_color=args.primary_color,
            font_family=args.font_family,
            is_premium=args.premium,
            price=args.price,
            is_active=not args.inactive,
            tags=tags,
            review_description=args.review_description,
            layout_key=args.layout,
            lm_pdf_path=args.lm,
            lm_label=args.lm_label,
            lm_layout_key=args.lm_layout,
            skip_visual_critic=getattr(args, "no_critic", False),
        )
    except Exception as e:
        logger.error("💥 ÉCHEC : %s", e, exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()