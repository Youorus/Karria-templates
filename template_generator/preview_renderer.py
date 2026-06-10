# template_generator/preview_renderer.py
"""
preview_renderer.py — Preview côte-à-côte PDF original / HTML rendu.

Fonctionnement :
  1. Rend le template.html avec les fake data (ou les data.json IA)
  2. Lance un mini serveur HTTP local
  3. Ouvre le navigateur sur une page côte-à-côte :
       GAUCHE  : PDF original affiché en <iframe> / <embed>
       DROITE  : template.html rendu avec fake data
  4. Surveille les modifications sur template.html et style.css
     → hot-reload automatique côté droite (WebSocket)
  5. Deux boutons dans la page :
       [✅ Valider]  → signal au CLI que le template est OK → pipeline continue
       [✏️  Éditer]  → ouvre template.html dans $EDITOR (si défini)

Usage programmatique (appelé par pipeline.py) :
    from template_generator.preview_renderer import run_preview
    approved = run_preview(template_dir, pdf_path)
    # approved = True  → on continue vers submit
    # approved = False → on abandonne

Usage direct :
    python -m template_generator.preview_renderer ./outputs/blue-spark
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings

from .fake_data import merge_with_data_json, get_cv_fake_data, get_lm_fake_data


logger = logging.getLogger(__name__)


def _score_preview_issues(issues: List[Dict[str, Any]]) -> int:
    score = 100
    for issue in issues:
        level = issue.get("level")
        if level == "critical":
            score -= 25
        elif level == "major":
            score -= 12
        else:
            score -= 5
    return max(score, 0)


def _validate_preview_html(rendered_html: str) -> Dict[str, Any]:
    """
    Validation légère côté preview : A4, overflow, densité, sidebar/header.
    Cette validation est volontairement autonome pour éviter de bloquer la preview
    si le pipeline complet n'est pas importable.
    """
    issues: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "score": 0,
            "passed": False,
            "issues": [
                {
                    "level": "major",
                    "category": "setup",
                    "message": "Playwright n'est pas installé : pip install playwright && playwright install chromium",
                }
            ],
            "metrics": metrics,
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 794, "height": 1123})
            page.set_content(rendered_html, wait_until="networkidle")
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
                  return {
                    width: Math.round(pageRect.width || 794),
                    height: Math.round(pageRect.height || 1123),
                    scroll_width: Math.round(document.documentElement.scrollWidth || document.body.scrollWidth || 794),
                    scroll_height: Math.round(document.documentElement.scrollHeight || document.body.scrollHeight || 1123),
                    sidebar_width: sidebarRect ? Math.round(sidebarRect.width) : null,
                    header_height: headerRect ? Math.round(headerRect.height) : null,
                    overflowing_blocks: overflowing.length,
                    min_line_height: lineHeights.length ? Math.min(...lineHeights) : null,
                    avg_font_size: fontSizes.length ? fontSizes.reduce((a, b) => a + b, 0) / fontSizes.length : null,
                  };
                }
                """
            )
            browser.close()
    except Exception as e:
        return {
            "score": 0,
            "passed": False,
            "issues": [
                {
                    "level": "major",
                    "category": "renderer",
                    "message": f"Impossible de mesurer le rendu : {e}",
                }
            ],
            "metrics": metrics,
        }

    width = metrics.get("width") or 0
    height = metrics.get("height") or 0
    scroll_width = metrics.get("scroll_width") or width
    scroll_height = metrics.get("scroll_height") or height
    overflowing_blocks = int(metrics.get("overflowing_blocks") or 0)
    min_line_height = metrics.get("min_line_height")
    avg_font_size = metrics.get("avg_font_size")

    if abs(width - 794) > 20:
        issues.append({"level": "major", "category": "a4", "message": f"Largeur A4 incorrecte : {width}px au lieu d'environ 794px"})
    if abs(height - 1123) > 30:
        issues.append({"level": "major", "category": "a4", "message": f"Hauteur A4 incorrecte : {height}px au lieu d'environ 1123px"})
    if scroll_width > width + 5:
        issues.append({"level": "critical", "category": "overflow", "message": f"Scroll horizontal détecté : {scroll_width}px > {width}px"})
    if scroll_height > height + 10:
        issues.append({"level": "critical", "category": "overflow", "message": f"Scroll vertical détecté : {scroll_height}px > {height}px"})
    if overflowing_blocks > 0:
        issues.append({"level": "critical", "category": "overflow", "message": f"{overflowing_blocks} bloc(s) sortent de la page"})
    if min_line_height and min_line_height < 1.10:
        issues.append({"level": "minor", "category": "density", "message": f"Line-height trop serré : {min_line_height:.2f}"})
    if avg_font_size and avg_font_size < 8:
        issues.append({"level": "major", "category": "density", "message": f"Texte trop petit en moyenne : {avg_font_size:.1f}px"})

    score = _score_preview_issues(issues)
    return {
        "score": score,
        "passed": score >= 90,
        "issues": issues,
        "metrics": metrics,
    }


# ─────────────────────────────────────────────────────────────────────────────
# RENDU JINJA2
# ─────────────────────────────────────────────────────────────────────────────

def _render_template(html_path: Path, data: Dict[str, Any]) -> str:
    """Rend un template Jinja2 avec les données fournies."""
    try:
        from jinja2 import Environment, Undefined

        def make_bars(level: int):
            return range(1, 6)

        env = Environment(undefined=Undefined)
        env.filters["make_bars"] = make_bars

        html_source = html_path.read_text(encoding="utf-8")
        return env.from_string(html_source).render(**data)
    except ImportError:
        raise RuntimeError("jinja2 requis : pip install jinja2")
    except Exception as e:
        logger.warning("⚠️  Rendu Jinja2 incomplet : %s", e)
        return html_path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# GÉNÉRATION DU HTML CÔTE-À-CÔTE
# ─────────────────────────────────────────────────────────────────────────────

_SIDE_BY_SIDE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🔍 Karria Preview — {template_name}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: system-ui, -apple-system, sans-serif;
    background: #0f0f13;
    color: #e0e0e0;
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }}

  /* ── TOPBAR ── */
  .topbar {{
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 10px 20px;
    background: #1a1a24;
    border-bottom: 1px solid #2e2e3e;
    flex-shrink: 0;
  }}
  .topbar-title {{
    font-size: 15px;
    font-weight: 600;
    color: #fff;
    flex: 1;
  }}
  .topbar-subtitle {{
    font-size: 12px;
    color: #888;
  }}

  /* ── BOUTONS ── */
  .btn {{
    padding: 8px 18px;
    border-radius: 8px;
    border: none;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    transition: opacity .15s;
  }}
  .btn:hover {{ opacity: .85; }}
  .btn-validate {{
    background: #22c55e;
    color: #fff;
  }}
  .btn-reject {{
    background: #ef4444;
    color: #fff;
  }}
  .btn-edit {{
    background: #3b82f6;
    color: #fff;
  }}
  .btn-reload {{
    background: #6b7280;
    color: #fff;
  }}

  .btn-quality {{
    background: #a855f7;
    color: #fff;
  }}

  /* ── QUALITY PANEL ── */
  .quality-panel {{
    width: 360px;
    flex-shrink: 0;
    background: #11111a;
    border-left: 2px solid #2e2e3e;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }}
  .quality-header {{
    padding: 14px 16px;
    border-bottom: 1px solid #272738;
    background: #181824;
  }}
  .quality-title {{
    color: #fff;
    font-size: 13px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: .08em;
  }}
  .quality-score {{
    margin-top: 10px;
    font-size: 34px;
    font-weight: 900;
    color: #fff;
  }}
  .quality-status {{
    margin-top: 4px;
    font-size: 12px;
    color: #aaa;
  }}
  .quality-body {{
    flex: 1;
    overflow: auto;
    padding: 12px;
  }}
  .quality-empty {{
    color: #22c55e;
    font-size: 13px;
    line-height: 1.45;
    padding: 12px;
    background: rgba(34,197,94,.08);
    border: 1px solid rgba(34,197,94,.18);
    border-radius: 10px;
  }}
  .quality-issue {{
    padding: 10px 12px;
    margin-bottom: 8px;
    border-radius: 10px;
    background: #181824;
    border: 1px solid #2c2c3c;
  }}
  .quality-issue.critical {{ border-color: rgba(239,68,68,.45); }}
  .quality-issue.major {{ border-color: rgba(245,158,11,.45); }}
  .quality-issue.minor {{ border-color: rgba(59,130,246,.45); }}
  .issue-meta {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: #888;
    margin-bottom: 6px;
    font-weight: 800;
  }}
  .issue-message {{
    font-size: 12px;
    color: #ddd;
    line-height: 1.4;
  }}
  .metrics-box {{
    margin-top: 12px;
    padding: 10px 12px;
    border-radius: 10px;
    background: #0c0c12;
    border: 1px solid #252536;
    color: #aaa;
    font-size: 11px;
    line-height: 1.6;
  }}

  /* ── LABELS ── */
  .col-label {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: #888;
    padding: 6px 20px;
    background: #16161e;
    border-bottom: 1px solid #23232e;
    flex-shrink: 0;
  }}

  /* ── SPLIT VIEW ── */
  .split {{
    display: flex;
    flex: 1;
    overflow: hidden;
  }}
  .pane {{
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }}
  .pane + .pane {{
    border-left: 2px solid #2e2e3e;
  }}
  iframe {{
    flex: 1;
    border: none;
    background: #fff;
  }}

  /* ── STATUS BAR ── */
  .statusbar {{
    padding: 6px 20px;
    font-size: 11px;
    color: #666;
    background: #0f0f13;
    border-top: 1px solid #1e1e2e;
    display: flex;
    gap: 20px;
  }}
  #status-msg {{
    color: #a78bfa;
    font-weight: 600;
  }}

  /* ── OVERLAY VALIDATION ── */
  .overlay {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,.7);
    z-index: 100;
    align-items: center;
    justify-content: center;
  }}
  .overlay.active {{ display: flex; }}
  .overlay-box {{
    background: #1e1e2e;
    border: 1px solid #3b3b5e;
    border-radius: 16px;
    padding: 40px 48px;
    text-align: center;
    max-width: 480px;
  }}
  .overlay-icon {{ font-size: 56px; margin-bottom: 16px; }}
  .overlay-title {{ font-size: 22px; font-weight: 700; color: #fff; margin-bottom: 8px; }}
  .overlay-sub {{ font-size: 14px; color: #aaa; }}
</style>
</head>
<body>

<!-- TOPBAR -->
<div class="topbar">
  <div>
    <div class="topbar-title">🔍 Karria Preview — {template_name}</div>
    <div class="topbar-subtitle">Comparez le PDF original (gauche) avec le rendu HTML (droite)</div>
  </div>
  <button class="btn btn-reload"   onclick="reloadRight()">🔄 Recharger</button>
  <button class="btn btn-quality"  onclick="runQualityCheck()">📏 Revalider</button>
  <button class="btn btn-edit"     onclick="requestEdit()">✏️ Éditer HTML</button>
  <button class="btn btn-reject"   onclick="reject()">❌ Rejeter</button>
  <button class="btn btn-validate" onclick="validate()">✅ Valider &amp; Continuer</button>
</div>

<!-- SPLIT VIEW -->
<div class="split">
  <!-- GAUCHE : PDF original -->
  <div class="pane">
    <div class="col-label">📄 PDF ORIGINAL</div>
    <iframe id="pdf-frame" src="/_pdf"></iframe>
  </div>

  <!-- DROITE : HTML rendu -->
  <div class="pane">
    <div class="col-label">🌐 RENDU HTML (fake data)</div>
    <iframe id="html-frame" src="/_rendered"></iframe>
  </div>

  <!-- PANEL : validations -->
  <aside class="quality-panel">
    <div class="quality-header">
      <div class="quality-title">📏 Validation qualité</div>
      <div class="quality-score" id="quality-score">--/100</div>
      <div class="quality-status" id="quality-status">Clique sur “Revalider” ou modifie le template.</div>
    </div>
    <div class="quality-body" id="quality-body">
      <div class="quality-empty">En attente de validation automatique…</div>
    </div>
  </aside>
</div>

<!-- STATUSBAR -->
<div class="statusbar">
  <span id="status-msg">En attente de ta décision…</span>
  <span>Hot-reload: <span id="ws-status">⚪</span></span>
  <span>Template: <code>{template_name}</code></span>
</div>

<!-- OVERLAY -->
<div class="overlay" id="overlay">
  <div class="overlay-box">
    <div class="overlay-icon" id="overlay-icon">✅</div>
    <div class="overlay-title" id="overlay-title">Template validé !</div>
    <div class="overlay-sub" id="overlay-sub">La pipeline va continuer…</div>
  </div>
</div>

<script>
const port = {port};

function reloadRight() {{
  document.getElementById("html-frame").src = "/_rendered?" + Date.now();
}}

function renderQualityReport(report) {{
  const scoreEl = document.getElementById("quality-score");
  const statusEl = document.getElementById("quality-status");
  const bodyEl = document.getElementById("quality-body");
  const score = report.score ?? 0;
  const issues = report.issues || [];
  const metrics = report.metrics || {{}};

  scoreEl.textContent = score + "/100";
  statusEl.textContent = report.passed
    ? "✅ Template conforme aux règles principales."
    : "⚠️ Corrections recommandées avant validation.";

  if (!issues.length) {{
    bodyEl.innerHTML = `
      <div class="quality-empty">✅ Aucun problème critique détecté. Tu peux comparer visuellement puis valider.</div>
      <div class="metrics-box">
        Largeur: ${{metrics.width ?? "?"}}px<br>
        Hauteur: ${{metrics.height ?? "?"}}px<br>
        Scroll H/V: ${{metrics.scroll_width ?? "?"}}px / ${{metrics.scroll_height ?? "?"}}px<br>
        Sidebar: ${{metrics.sidebar_width ?? "non détectée"}}px<br>
        Header: ${{metrics.header_height ?? "non détecté"}}px
      </div>
    `;
    return;
  }}

  bodyEl.innerHTML = issues.map((issue) => `
    <div class="quality-issue ${{issue.level}}">
      <div class="issue-meta">${{issue.level}} / ${{issue.category}}</div>
      <div class="issue-message">${{issue.message}}</div>
    </div>
  `).join("") + `
    <div class="metrics-box">
      Largeur: ${{metrics.width ?? "?"}}px<br>
      Hauteur: ${{metrics.height ?? "?"}}px<br>
      Scroll H/V: ${{metrics.scroll_width ?? "?"}}px / ${{metrics.scroll_height ?? "?"}}px<br>
      Blocs hors page: ${{metrics.overflowing_blocks ?? "?"}}<br>
      Sidebar: ${{metrics.sidebar_width ?? "non détectée"}}px<br>
      Header: ${{metrics.header_height ?? "non détecté"}}px<br>
      Font avg: ${{metrics.avg_font_size ? metrics.avg_font_size.toFixed(1) : "?"}}px
    </div>
  `;
}}

async function runQualityCheck() {{
  document.getElementById("quality-status").textContent = "Analyse du rendu en cours…";
  try {{
    const r = await fetch("/_quality?" + Date.now());
    const report = await r.json();
    renderQualityReport(report);
  }} catch (e) {{
    renderQualityReport({{
      score: 0,
      passed: false,
      issues: [{{ level: "major", category: "preview", message: "Impossible de lancer la validation qualité." }}],
      metrics: {{}},
    }});
  }}
}}

function requestEdit() {{
  fetch("/_edit").then(() => document.getElementById("status-msg").textContent = "Éditeur ouvert.");
}}

function validate() {{
  document.getElementById("overlay-icon").textContent  = "✅";
  document.getElementById("overlay-title").textContent = "Template validé !";
  document.getElementById("overlay-sub").textContent   = "Ferme cette fenêtre — la pipeline continue…";
  document.getElementById("overlay").classList.add("active");
  fetch("/_validate?action=approve").then(() => {{
    document.getElementById("status-msg").textContent = "✅ Validé — pipeline continue.";
  }});
}}

function reject() {{
  if (!confirm("Rejeter ce template ?\\nLa pipeline sera annulée.")) return;
  document.getElementById("overlay-icon").textContent  = "❌";
  document.getElementById("overlay-title").textContent = "Template rejeté.";
  document.getElementById("overlay-sub").textContent   = "Ferme cette fenêtre.";
  document.getElementById("overlay").classList.add("active");
  fetch("/_validate?action=reject").then(() => {{
    document.getElementById("status-msg").textContent = "❌ Rejeté.";
  }});
}}

/* ── Hot-reload via polling ── */
let lastMod = null;
const ws_indicator = document.getElementById("ws-status");
ws_indicator.textContent = "🟢 polling";

setInterval(async () => {{
  try {{
    const r  = await fetch("/_mtime");
    const d  = await r.json();
    if (lastMod && d.mtime !== lastMod) {{
      reloadRight();
      runQualityCheck();
      document.getElementById("status-msg").textContent = "🔄 Template mis à jour — rechargé et revalidé";
    }}
    lastMod = d.mtime;
  }} catch (e) {{}}
}}, 1200);
</script>

runQualityCheck();
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# SERVEUR HTTP
# ─────────────────────────────────────────────────────────────────────────────

class _PreviewState:
    """État partagé entre le serveur HTTP et le thread principal."""
    decision:         Optional[str] = None   # "approve" | "reject"
    template_dir:     Path          = Path(".")
    pdf_path:         Optional[Path] = None
    rendered_html:    str           = ""
    template_name:    str           = ""
    port:             int           = 8765


_state = _PreviewState()


class _Handler(BaseHTTPRequestHandler):
    """Handler HTTP minimaliste pour le preview."""

    def log_message(self, fmt, *args):
        pass  # Silence les logs HTTP dans la console

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path

        if path == "/":
            self._serve_text(
                _SIDE_BY_SIDE_TEMPLATE.format(
                    template_name=_state.template_name,
                    port=_state.port,
                ),
                "text/html",
            )

        elif path == "/_pdf":
            pdf = _state.pdf_path
            if pdf and pdf.is_file():
                data = pdf.read_bytes()
                self._serve_bytes(data, "application/pdf")
            else:
                self._serve_text("<p>PDF non trouvé</p>", "text/html", 404)

        elif path == "/_rendered":
            # Re-rend à chaque appel pour refléter les modifications
            _state.rendered_html = _rebuild_rendered(_state.template_dir)
            self._serve_text(_state.rendered_html, "text/html")

        elif path == "/_mtime":
            mtime = _get_mtime(_state.template_dir)
            self._serve_text(json.dumps({"mtime": mtime}), "application/json")

        elif path == "/_quality":
            _state.rendered_html = _rebuild_rendered(_state.template_dir)
            report = _validate_preview_html(_state.rendered_html)
            self._serve_text(json.dumps(report, ensure_ascii=False), "application/json")

        elif path == "/_edit":
            _open_in_editor(_state.template_dir / "template.html")
            self._serve_text("{}", "application/json")

        elif path.startswith("/_validate"):
            params = parse_qs(parsed.query)
            action = (params.get("action") or ["approve"])[0]
            _state.decision = action
            self._serve_text(json.dumps({"ok": True}), "application/json")

        else:
            self._serve_text("Not found", "text/plain", 404)

    # ── helpers ──

    def _serve_text(self, body: str, content_type: str, code: int = 200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_bytes(self, data: bytes, content_type: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNES
# ─────────────────────────────────────────────────────────────────────────────

def _rebuild_rendered(template_dir: Path) -> str:
    """Reconstruit le HTML rendu avec les dernières modifications sur disque."""
    html_path = template_dir / "template.html"
    data_path = template_dir / "data.json"

    if not html_path.exists():
        # LM ?
        html_path = template_dir / "lm_template.html"

    if not html_path.exists():
        return "<p>template.html introuvable</p>"

    # Fusionne data.json IA + fake data pour un rendu réaliste
    if data_path.exists():
        try:
            ai_data = json.loads(data_path.read_text(encoding="utf-8"))
        except Exception:
            ai_data = {}
        fake = get_cv_fake_data()
        data = merge_with_data_json(json.dumps(ai_data), fake)
    else:
        lm_data = template_dir / "lm_data.json"
        if lm_data.exists():
            try:
                ai_lm = json.loads(lm_data.read_text(encoding="utf-8"))
            except Exception:
                ai_lm = {}
            data = {**get_lm_fake_data(), **ai_lm}
        else:
            data = get_cv_fake_data()

    return _render_template(html_path, data)


def _get_mtime(template_dir: Path) -> float:
    """Retourne le timestamp de modification le plus récent parmi HTML+CSS."""
    files = [
        template_dir / "template.html",
        template_dir / "style.css",
        template_dir / "lm_template.html",
        template_dir / "lm_style.css",
    ]
    times = [f.stat().st_mtime for f in files if f.exists()]
    return max(times) if times else 0.0


def _open_in_editor(path: Path) -> None:
    """Ouvre le fichier dans l'éditeur défini par $EDITOR ou $VISUAL."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ""
    if not editor:
        logger.warning(
            "⚠️  $EDITOR non défini. Ouvre manuellement : %s", path
        )
        return
    try:
        subprocess.Popen([editor, str(path)])
    except Exception as e:
        logger.warning("⚠️  Impossible d'ouvrir l'éditeur : %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# API PUBLIQUE
# ─────────────────────────────────────────────────────────────────────────────

def run_preview(
    template_dir: Path,
    pdf_path:     Optional[Path] = None,
    *,
    port:         int  = 0,
    auto_open:    bool = True,
    lm_subdir:    bool = False,
) -> bool:
    """
    Lance le serveur de preview et attend la décision de l'utilisateur.

    Args:
        template_dir : dossier contenant template.html, style.css, data.json
        pdf_path     : PDF original (affiché à gauche). Cherche preview.pdf
                       dans template_dir si non fourni.
        port         : port HTTP (0 = utilise settings.PREVIEW_PORT)
        auto_open    : ouvrir automatiquement le navigateur
        lm_subdir    : True pour prévisualiser le sous-dossier lm/

    Returns:
        True si l'utilisateur a cliqué "Valider", False sinon.
    """
    # Résolution chemins
    if lm_subdir:
        template_dir = template_dir / "lm"

    if not template_dir.exists():
        raise FileNotFoundError(f"Dossier template introuvable : {template_dir}")

    if pdf_path is None:
        for candidate in (
            template_dir / "preview.pdf",
            template_dir.parent / "preview.pdf",
            template_dir / "lm_preview.pdf",
        ):
            if candidate.exists():
                pdf_path = candidate
                break

    use_port = port or settings.PREVIEW_PORT

    # Configure l'état partagé
    _state.template_dir  = template_dir
    _state.pdf_path      = pdf_path
    _state.template_name = template_dir.name
    _state.port          = use_port
    _state.decision      = None
    _state.rendered_html = _rebuild_rendered(template_dir)

    # Démarre le serveur dans un thread daemon
    server = HTTPServer(("127.0.0.1", use_port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{use_port}/"
    print(f"\n🌐 Preview disponible : {url}")
    print("   GAUCHE  = PDF original  |  DROITE  = HTML rendu avec fake data")
    print("   ✅ Valider → pipeline continue    ❌ Rejeter → pipeline annulée")
    print("   ✏️  Édite template.html/style.css → hot-reload automatique\n")

    if auto_open:
        time.sleep(0.4)  # Laisse le serveur démarrer
        webbrowser.open(url)

    # Boucle d'attente décision
    print("⏳ En attente de ta décision dans le navigateur…")
    try:
        while _state.decision is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n⚠️  Interruption clavier — template NON validé.")
        server.shutdown()
        return False

    server.shutdown()

    approved = _state.decision == "approve"
    if approved:
        print("✅ Template validé.")
    else:
        print("❌ Template rejeté.")

    return approved


# ─────────────────────────────────────────────────────────────────────────────
# ENTRÉE CLI DIRECTE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    p = argparse.ArgumentParser(description="Preview côte-à-côte d'un template Karria")
    p.add_argument("folder", help="Dossier du template (contient template.html)")
    p.add_argument("--pdf",  default=None, help="PDF original (sinon preview.pdf dans le dossier)")
    p.add_argument("--lm",   action="store_true", help="Prévisualiser le sous-dossier lm/")
    p.add_argument("--port", type=int, default=0)
    a = p.parse_args()

    folder  = Path(a.folder).resolve()
    pdf     = Path(a.pdf).resolve() if a.pdf else None
    result  = run_preview(folder, pdf_path=pdf, port=a.port, lm_subdir=a.lm)
    sys.exit(0 if result else 1)