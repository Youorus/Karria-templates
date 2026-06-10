# template_generator/pdf_analyzer.py
"""
PDFAnalyzer v3 — extraction structurée + mesures GÉOMÉTRIQUES précises.

Ajouts vs v2 (objectif fidélité pixel-perfect) :
  * Marges réelles (top/bottom/left/right) en mm depuis les bbox texte
  * Largeur exacte sidebar en mm + ratio sidebar/page
  * Hauteur du bloc header (top de page → 1er gros gap vertical)
  * Gaps verticaux moyens entre sections détectés
  * Position Y de chaque section principale (top, contact, summary, ...)
  * Anchor lines (lignes horizontales de séparation) si présentes
  * Tout est exprimé en mm pour aller direct dans le CSS
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# Conversion 1 pt = 0.3528 mm (standard PDF)
PT_TO_MM = 0.3528


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FontInfo:
    name: str
    size: float
    weight: str
    style: str
    usage: int


@dataclass
class ColorInfo:
    hex: str
    rgb: Tuple[int, int, int]
    usage_pct: float


@dataclass
class ImageInfo:
    width_px: int
    height_px: int
    bbox: Tuple[float, float, float, float]
    is_likely_photo: bool
    score: float = 0.0


@dataclass
class Margins:
    """Marges réelles du contenu en mm."""
    top: float
    bottom: float
    left: float
    right: float

    def to_css(self) -> str:
        return f"padding: {self.top:.1f}mm {self.right:.1f}mm {self.bottom:.1f}mm {self.left:.1f}mm;"


@dataclass
class SidebarGeometry:
    """Géométrie précise de la sidebar si détectée."""
    position: str               # "left" | "right"
    width_mm: float             # largeur exacte
    width_ratio: float          # 0.0–1.0 (portion de la page width)
    color_hex: str
    text_color_hex: str         # couleur dominante du texte sidebar
    bbox_mm: Tuple[float, float, float, float]  # (x0, y0, x1, y1) en mm


@dataclass
class HeaderGeometry:
    """Géométrie du header (zone identité top-of-page)."""
    height_mm: float            # depuis top page jusqu'au début du corps
    background_color_hex: Optional[str] = None
    has_full_width_band: bool = False   # bandeau pleine largeur ?


@dataclass
class PDFAnalysis:
    page_count: int
    width_mm: float
    height_mm: float
    is_a4: bool

    fonts: List[FontInfo]
    colors: List[ColorInfo]
    images: List[ImageInfo]

    has_photo: bool
    photo_position: Optional[str] = None

    estimated_columns: int = 1
    sidebar_position: Optional[str] = None
    sidebar_color_hex: Optional[str] = None

    text_blocks_count: int = 0
    text_density_score: float = 0.0

    # ── NOUVEAU v3 — géométrie précise ─────────────────────────────────────
    margins: Optional[Margins] = None
    sidebar: Optional[SidebarGeometry] = None
    header: Optional[HeaderGeometry] = None
    avg_section_gap_mm: float = 0.0   # gap vertical moyen entre blocs
    horizontal_rules: List[float] = field(default_factory=list)  # lignes h. en mm (y)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_prompt_summary(self) -> str:
        # Top fonts dédupliqués
        fonts_by_name: dict[str, FontInfo] = {}
        for f in self.fonts:
            if f.name not in fonts_by_name or fonts_by_name[f.name].usage < f.usage:
                fonts_by_name[f.name] = f
        top_fonts = sorted(fonts_by_name.values(), key=lambda f: -f.usage)[:5]

        font_lines = [
            f"  • {f.name} ({f.size:.1f}pt, {f.weight}, {f.style})"
            for f in top_fonts
        ]
        color_lines = [
            f"  • {c.hex} (rgb={c.rgb}, ~{c.usage_pct:.1f}% de la page)"
            for c in self.colors[:8]
        ]

        photo_str = f"OUI ({self.photo_position})" if self.has_photo else "NON"

        density_label = (
            "saturé" if self.text_density_score > 0.75
            else "élevé" if self.text_density_score > 0.55
            else "moyen" if self.text_density_score > 0.35
            else "aéré"
        )

        # ── Mesures précises (NOUVEAU) ──
        margins_block = (
            f"  • TOP    : {self.margins.top:.1f}mm\n"
            f"  • BOTTOM : {self.margins.bottom:.1f}mm\n"
            f"  • LEFT   : {self.margins.left:.1f}mm\n"
            f"  • RIGHT  : {self.margins.right:.1f}mm\n"
            f"  → CSS direct : {self.margins.to_css()}"
        ) if self.margins else "  (non mesurées — fallback 18mm partout)"

        sidebar_block = (
            f"  • POSITION  : {self.sidebar.position}\n"
            f"  • LARGEUR   : {self.sidebar.width_mm:.1f}mm "
            f"(soit {self.sidebar.width_ratio*100:.0f}% de la page)\n"
            f"  • COULEUR   : {self.sidebar.color_hex}\n"
            f"  • TEXTE     : {self.sidebar.text_color_hex}\n"
            f"  → grid-template-columns suggéré : "
            f"{'1fr ' + str(round(self.sidebar.width_mm)) + 'mm' if self.sidebar.position=='right' else str(round(self.sidebar.width_mm)) + 'mm 1fr'}"
        ) if self.sidebar else "  (aucune sidebar détectée)"

        header_block = (
            f"  • HAUTEUR    : {self.header.height_mm:.1f}mm\n"
            f"  • BACKGROUND : {self.header.background_color_hex or '(transparent)'}\n"
            f"  • BANDEAU PLEINE LARGEUR : {'OUI' if self.header.has_full_width_band else 'non'}"
        ) if self.header else "  (pas d'en-tête distinct — header inline)"

        rules_block = (
            "  • " + ", ".join(f"y={y:.1f}mm" for y in self.horizontal_rules[:8])
            if self.horizontal_rules else "  (aucune)"
        )

        return f"""
PRÉ-ANALYSE PDF (valeurs RÉELLES extraites — utilise-les TELLES QUELLES) :

📐 DIMENSIONS
  • Format         : {self.width_mm:.0f}mm × {self.height_mm:.0f}mm ({"A4" if self.is_a4 else "non-A4"})
  • Pages          : {self.page_count}
  • Colonnes       : {self.estimated_columns}
  • Densité texte  : {density_label} ({self.text_density_score:.2f})
  • Blocs texte    : {self.text_blocks_count}
  • Gap moyen entre sections : {self.avg_section_gap_mm:.1f}mm

📏 MARGES MESURÉES (à reproduire EXACTEMENT en CSS)
{margins_block}

🪟 SIDEBAR
{sidebar_block}

🪪 HEADER (zone identité)
{header_block}

➖ LIGNES HORIZONTALES (séparateurs détectés en y mm)
{rules_block}

🔤 FONTS DÉTECTÉES (utilise les Google Fonts les plus proches si non standard)
{chr(10).join(font_lines) if font_lines else "  (aucune font extraite — fallback sur Inter)"}

🎨 PALETTE COULEURS DOMINANTES (utilise EXACTEMENT ces hex)
{chr(10).join(color_lines) if color_lines else "  (palette non extraite — fallback couleurs neutres)"}

📷 PHOTO DE PROFIL : {photo_str}
"""


# ─────────────────────────────────────────────────────────────────────────────
# ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

class PDFAnalyzer:
    """Analyse structurée d'un PDF — fonts, couleurs, dimensions, layout, photo, GÉOMÉTRIE."""

    def analyze(self, pdf_path: str | Path) -> PDFAnalysis:
        try:
            import fitz  # PyMuPDF
        except ImportError as e:
            raise ImportError("PyMuPDF requis : pip install pymupdf") from e

        doc = fitz.open(str(pdf_path))
        try:
            return self._analyze_doc(doc)
        finally:
            doc.close()

    def _analyze_doc(self, doc) -> PDFAnalysis:
        page = doc[0]

        rect = page.rect
        width_mm = rect.width * PT_TO_MM
        height_mm = rect.height * PT_TO_MM
        is_a4 = abs(width_mm - 210) < 5 and abs(height_mm - 297) < 5

        # Texte
        text_dict = page.get_text("dict")
        blocks = text_dict.get("blocks", [])
        text_blocks = [b for b in blocks if b.get("type", 0) == 0]

        fonts = self._extract_fonts(text_blocks)
        text_density = self._compute_text_density(text_blocks, page.rect)

        # Images / photos
        images = self._extract_images(page)
        photo = next((img for img in images if img.is_likely_photo), None)
        has_photo = photo is not None
        photo_position = self._photo_position(photo, page.rect) if photo else None

        # Couleurs (filtrant les zones photos)
        photo_bboxes = [i.bbox for i in images if i.is_likely_photo]
        colors = self._extract_colors(page, exclude_bboxes=photo_bboxes)

        # Layout
        estimated_columns = self._estimate_columns(text_blocks, width_mm)
        sidebar_position, sidebar_color = self._detect_sidebar(page)

        # ── NOUVEAU v3 : mesures précises ──
        margins = self._measure_margins(text_blocks, page.rect)
        sidebar_geom = self._measure_sidebar_geometry(
            page, text_blocks, sidebar_position, sidebar_color
        )
        header_geom = self._measure_header(page, text_blocks, sidebar_geom)
        section_gap = self._compute_section_gap(text_blocks)
        h_rules = self._detect_horizontal_rules(page)

        return PDFAnalysis(
            page_count=len(doc),
            width_mm=width_mm,
            height_mm=height_mm,
            is_a4=is_a4,
            fonts=fonts,
            colors=colors,
            images=images,
            has_photo=has_photo,
            photo_position=photo_position,
            estimated_columns=estimated_columns,
            sidebar_position=sidebar_position,
            sidebar_color_hex=sidebar_color,
            text_blocks_count=len(text_blocks),
            text_density_score=text_density,
            margins=margins,
            sidebar=sidebar_geom,
            header=header_geom,
            avg_section_gap_mm=section_gap,
            horizontal_rules=h_rules,
        )

    # ─── FONTS ───────────────────────────────────────────────────────────

    def _extract_fonts(self, text_blocks: list) -> List[FontInfo]:
        font_counter: Counter = Counter()
        for block in text_blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    raw_name = span.get("font", "")
                    size = round(span.get("size", 12.0), 1)
                    flags = span.get("flags", 0)

                    weight = "bold" if flags & 16 else "normal"
                    style = "italic" if flags & 2 else "normal"

                    name = self._clean_font_name(raw_name)
                    char_count = len(span.get("text", "").strip())
                    if char_count > 0 and name:
                        font_counter[(name, size, weight, style)] += char_count

        return [
            FontInfo(name=n, size=s, weight=w, style=st, usage=u)
            for (n, s, w, st), u in font_counter.most_common(20)
        ]

    @staticmethod
    def _clean_font_name(raw: str) -> str:
        """Strip subset prefix `ABCDEF+` and weight/style suffixes."""
        if not raw:
            return ""
        name = re.sub(r"^[A-Z]{6}\+", "", raw)
        name = re.sub(
            r"[-,]?(Bold|Italic|Light|Medium|Regular|Thin|Black|"
            r"Heavy|SemiBold|ExtraBold|ExtraLight|Oblique|Roman)$",
            "",
            name,
            flags=re.I,
        )
        return name.strip()

    @staticmethod
    def _compute_text_density(text_blocks: list, page_rect) -> float:
        total_text_area = 0.0
        for block in text_blocks:
            bbox = block.get("bbox")
            if bbox and len(bbox) >= 4:
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
                total_text_area += w * h
        page_area = page_rect.width * page_rect.height
        if page_area <= 0:
            return 0.0
        return min(total_text_area / page_area, 1.0)

    # ─── COULEURS ────────────────────────────────────────────────────────

    def _extract_colors(self, page, n_colors: int = 8, exclude_bboxes: list = None) -> List[ColorInfo]:
        try:
            from PIL import Image, ImageDraw
            import numpy as np
        except ImportError:
            logger.warning("PIL/numpy manquant — extraction couleurs skippée")
            return []

        pix = page.get_pixmap(dpi=150)
        img_data = pix.tobytes("png")
        img = Image.open(BytesIO(img_data)).convert("RGB")

        if exclude_bboxes:
            scale = pix.width / page.rect.width
            mask_img = img.copy()
            draw = ImageDraw.Draw(mask_img)
            for bbox in exclude_bboxes:
                x0, y0, x1, y1 = bbox
                draw.rectangle(
                    [int(x0 * scale), int(y0 * scale), int(x1 * scale), int(y1 * scale)],
                    fill=(255, 255, 255),
                )
            img = mask_img

        img.thumbnail((400, 600))
        arr = np.array(img).reshape(-1, 3)

        is_white = (arr[:, 0] > 240) & (arr[:, 1] > 240) & (arr[:, 2] > 240)
        is_black = (arr[:, 0] < 25) & (arr[:, 1] < 25) & (arr[:, 2] < 25)
        non_neutral = arr[~is_white & ~is_black]
        total_pixels = len(arr)

        if len(non_neutral) < 100:
            colors = []
            if is_white.sum() / total_pixels > 0.5:
                colors.append(ColorInfo(hex="#FFFFFF", rgb=(255, 255, 255),
                                        usage_pct=float(is_white.sum() / total_pixels * 100)))
            if is_black.sum() / total_pixels > 0.05:
                colors.append(ColorInfo(hex="#1A1A1A", rgb=(26, 26, 26),
                                        usage_pct=float(is_black.sum() / total_pixels * 100)))
            return colors

        try:
            from sklearn.cluster import KMeans
            kmeans = KMeans(n_clusters=n_colors, n_init=8, random_state=42)
            kmeans.fit(non_neutral)
            centers = kmeans.cluster_centers_
            counts = np.bincount(kmeans.labels_)
        except ImportError:
            return self._extract_colors_fallback(non_neutral, total_pixels, n_colors)

        order = np.argsort(-counts)
        colors = []
        for idx in order:
            r, g, b = centers[idx].astype(int)
            usage_pct = counts[idx] / total_pixels * 100
            colors.append(ColorInfo(
                hex=f"#{r:02X}{g:02X}{b:02X}",
                rgb=(int(r), int(g), int(b)),
                usage_pct=float(usage_pct),
            ))

        white_count = int(is_white.sum())
        if white_count / total_pixels > 0.3:
            colors.insert(0, ColorInfo(
                hex="#FFFFFF", rgb=(255, 255, 255),
                usage_pct=float(white_count / total_pixels * 100),
            ))

        return colors

    @staticmethod
    def _extract_colors_fallback(arr, total: int, n: int) -> List[ColorInfo]:
        quantized = (arr // 16) * 16
        tuples = [tuple(p) for p in quantized.tolist()]
        counter = Counter(tuples)
        return [
            ColorInfo(
                hex=f"#{r:02X}{g:02X}{b:02X}", rgb=(int(r), int(g), int(b)),
                usage_pct=float(count / total * 100),
            )
            for (r, g, b), count in counter.most_common(n)
        ]

    # ─── IMAGES / PHOTO ──────────────────────────────────────────────────

    def _extract_images(self, page) -> List[ImageInfo]:
        result = []
        try:
            for img in page.get_images(full=True):
                xref = img[0]
                bbox_list = page.get_image_rects(xref)
                if not bbox_list:
                    continue
                bbox = bbox_list[0]
                w, h = img[2], img[3]

                bbox_w = bbox.x1 - bbox.x0
                bbox_h = bbox.y1 - bbox.y0
                page_w = page.rect.width
                page_h = page.rect.height

                ratio = bbox_w / max(bbox_h, 1)
                size_ratio = (bbox_w * bbox_h) / (page_w * page_h)

                score = 0.0
                if 0.65 <= ratio <= 1.55:
                    score += 0.35
                if 0.02 <= size_ratio <= 0.18:
                    score += 0.30
                if bbox.y0 < page_h * 0.45:
                    score += 0.20
                if bbox.x0 < page_w * 0.35 or bbox.x1 > page_w * 0.65:
                    score += 0.10
                if w >= 150 and h >= 150:
                    score += 0.05

                is_photo = score >= 0.65

                result.append(ImageInfo(
                    width_px=w, height_px=h,
                    bbox=(float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1)),
                    is_likely_photo=is_photo,
                    score=round(score, 2),
                ))
        except Exception as e:
            logger.debug("Image extraction error: %s", e)

        return result

    @staticmethod
    def _photo_position(photo: ImageInfo, page_rect) -> str:
        x_center = (photo.bbox[0] + photo.bbox[2]) / 2
        third = page_rect.width / 3
        if x_center < third:
            return "top-left"
        if x_center > 2 * third:
            return "top-right"
        return "top-center"

    # ─── COLONNES / SIDEBAR ──────────────────────────────────────────────

    @staticmethod
    def _estimate_columns(text_blocks: list, page_width_mm: float) -> int:
        if not text_blocks:
            return 1
        x_positions = [b.get("bbox", [0])[0] for b in text_blocks if b.get("bbox")]
        if not x_positions:
            return 1
        x_mm = [x * PT_TO_MM for x in x_positions]
        mid = page_width_mm / 2
        right_count = sum(1 for x in x_mm if x > mid + 5)
        ratio = right_count / len(x_mm)
        return 2 if ratio > 0.25 else 1

    @staticmethod
    def _detect_sidebar(page) -> Tuple[Optional[str], Optional[str]]:
        """Détecte sidebar via dominant color sur strip gauche/droite."""
        try:
            from PIL import Image
            import numpy as np
        except ImportError:
            return None, None

        pix = page.get_pixmap(dpi=100)
        img = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
        arr = np.array(img)
        h_img, w_img = arr.shape[:2]

        left_strip  = arr[:, :int(w_img * 0.30)]
        right_strip = arr[:, int(w_img * 0.70):]

        def _strip_dominant_color(strip):
            flat = strip.reshape(-1, 3)
            non_white = flat[~((flat[:, 0] > 240) & (flat[:, 1] > 240) & (flat[:, 2] > 240))]
            if len(non_white) < 100:
                return None, 0.0
            r, g, b = np.median(non_white, axis=0).astype(int)
            color_hex = f"#{r:02X}{g:02X}{b:02X}"
            diffs = np.abs(non_white - np.array([r, g, b])).sum(axis=1)
            ratio = float((diffs < 30).sum() / len(flat))
            return color_hex, ratio

        left_color, left_ratio = _strip_dominant_color(left_strip)
        right_color, right_ratio = _strip_dominant_color(right_strip)

        if left_ratio > 0.25 and left_ratio > right_ratio:
            return "left", left_color
        if right_ratio > 0.25:
            return "right", right_color
        return None, None

    # ─── NOUVEAU v3 : MESURES PRÉCISES ───────────────────────────────────

    @staticmethod
    def _measure_margins(text_blocks: list, page_rect) -> Optional[Margins]:
        """
        Calcule les marges réelles depuis les bbox texte.
        Marge top = y minimal des textes
        Marge bottom = page_height - y maximal des textes
        Idem horizontal.
        """
        if not text_blocks:
            return None

        xs0, ys0, xs1, ys1 = [], [], [], []
        for b in text_blocks:
            bbox = b.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            xs0.append(bbox[0]); ys0.append(bbox[1])
            xs1.append(bbox[2]); ys1.append(bbox[3])

        if not xs0:
            return None

        # On prend le 5e percentile pour éviter les outliers (artefacts en marge)
        import numpy as np
        left_pt   = float(np.percentile(xs0, 5))
        top_pt    = float(np.percentile(ys0, 5))
        right_pt  = page_rect.width  - float(np.percentile(xs1, 95))
        bottom_pt = page_rect.height - float(np.percentile(ys1, 95))

        return Margins(
            top    = max(0.0, top_pt    * PT_TO_MM),
            bottom = max(0.0, bottom_pt * PT_TO_MM),
            left   = max(0.0, left_pt   * PT_TO_MM),
            right  = max(0.0, right_pt  * PT_TO_MM),
        )

    def _measure_sidebar_geometry(
        self,
        page,
        text_blocks: list,
        position: Optional[str],
        color: Optional[str],
    ) -> Optional[SidebarGeometry]:
        """Mesure la largeur exacte de la sidebar en scannant les colonnes de pixels."""
        if not position or not color:
            return None

        try:
            from PIL import Image
            import numpy as np
        except ImportError:
            return None

        pix = page.get_pixmap(dpi=100)
        img = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
        arr = np.array(img)
        h_img, w_img = arr.shape[:2]

        # Couleur cible
        r_t = int(color[1:3], 16)
        g_t = int(color[3:5], 16)
        b_t = int(color[5:7], 16)

        # Pour chaque colonne x, calcule % de pixels proches de la couleur sidebar
        diffs = np.abs(arr.astype(int) - np.array([r_t, g_t, b_t])).sum(axis=2)  # (H, W)
        is_sidebar_pixel = diffs < 60  # tolérance
        col_ratios = is_sidebar_pixel.sum(axis=0) / h_img  # (W,)

        threshold = 0.35  # une colonne fait partie de la sidebar si ≥ 35% de ses pixels matchent
        sidebar_cols = np.where(col_ratios > threshold)[0]

        if len(sidebar_cols) < 5:
            return None

        if position == "left":
            x0_px = int(sidebar_cols.min())
            x1_px = int(sidebar_cols.max())
            # On veut la zone CONTIGUË à gauche (cherche le 1er trou)
            for i, c in enumerate(sidebar_cols):
                if c > x0_px + i + 5:  # gros trou
                    x1_px = int(sidebar_cols[i - 1]) if i > 0 else x0_px
                    break
            else:
                x1_px = int(sidebar_cols.max())
        else:  # right
            x1_px = int(sidebar_cols.max())
            x0_px = int(sidebar_cols.min())

        scale_pt = page.rect.width / w_img
        x0_pt = x0_px * scale_pt
        x1_pt = x1_px * scale_pt
        width_mm = (x1_pt - x0_pt) * PT_TO_MM
        width_ratio = width_mm / (page.rect.width * PT_TO_MM)

        # Couleur du texte dans la sidebar (zone bbox)
        text_color = self._dominant_text_color_in_zone(
            text_blocks, x0_pt, 0, x1_pt, page.rect.height
        )

        return SidebarGeometry(
            position=position,
            width_mm=width_mm,
            width_ratio=width_ratio,
            color_hex=color,
            text_color_hex=text_color,
            bbox_mm=(
                x0_pt * PT_TO_MM, 0.0,
                x1_pt * PT_TO_MM, page.rect.height * PT_TO_MM,
            ),
        )

    @staticmethod
    def _dominant_text_color_in_zone(
        text_blocks: list,
        x0: float, y0: float, x1: float, y1: float,
    ) -> str:
        """Couleur dominante des spans texte dans la zone donnée (en points PDF)."""
        color_counter: Counter = Counter()
        for block in text_blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    sb = span.get("bbox") or line.get("bbox")
                    if not sb:
                        continue
                    sx = (sb[0] + sb[2]) / 2
                    sy = (sb[1] + sb[3]) / 2
                    if x0 <= sx <= x1 and y0 <= sy <= y1:
                        col = span.get("color")
                        if col is None:
                            continue
                        # color est un int (sRGB packed)
                        r = (col >> 16) & 0xFF
                        g = (col >> 8) & 0xFF
                        b = col & 0xFF
                        color_counter[(r, g, b)] += len(span.get("text", "").strip())

        if not color_counter:
            return "#FFFFFF"
        (r, g, b), _ = color_counter.most_common(1)[0]
        return f"#{r:02X}{g:02X}{b:02X}"

    @staticmethod
    def _measure_header(
        page,
        text_blocks: list,
        sidebar: Optional[SidebarGeometry],
    ) -> Optional[HeaderGeometry]:
        """
        Hauteur du header = du top page jusqu'au 1er gap vertical > 8mm
        dans la zone hors-sidebar.
        """
        if not text_blocks:
            return None

        # Filtre blocs hors sidebar
        if sidebar:
            sb_x0 = sidebar.bbox_mm[0] / PT_TO_MM
            sb_x1 = sidebar.bbox_mm[2] / PT_TO_MM
            blocks = [
                b for b in text_blocks
                if b.get("bbox") and not (sb_x0 <= b["bbox"][0] <= sb_x1)
            ]
        else:
            blocks = list(text_blocks)

        if not blocks:
            return None

        # Trie par y0 et cherche le 1er saut > 8mm (≈ 22pt)
        sorted_blocks = sorted(
            [b for b in blocks if b.get("bbox")],
            key=lambda b: b["bbox"][1],
        )

        gap_threshold_pt = 8 / PT_TO_MM
        header_end_pt = sorted_blocks[0]["bbox"][3]
        for prev, curr in zip(sorted_blocks, sorted_blocks[1:]):
            gap = curr["bbox"][1] - prev["bbox"][3]
            if gap > gap_threshold_pt:
                header_end_pt = prev["bbox"][3]
                break
            header_end_pt = curr["bbox"][3]

        height_mm = header_end_pt * PT_TO_MM

        # Background ? bandeau pleine largeur ?
        bg_color, full_width = PDFAnalyzer._detect_header_background(page, header_end_pt)

        return HeaderGeometry(
            height_mm=height_mm,
            background_color_hex=bg_color,
            has_full_width_band=full_width,
        )

    @staticmethod
    def _detect_header_background(page, header_end_pt: float) -> Tuple[Optional[str], bool]:
        """Renvoie (bg_color_hex, has_full_width_band) si le header a un fond uni."""
        try:
            from PIL import Image
            import numpy as np
        except ImportError:
            return None, False

        pix = page.get_pixmap(dpi=80)
        img = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
        arr = np.array(img)
        h_img, w_img = arr.shape[:2]

        scale = h_img / page.rect.height
        end_y_px = int(header_end_pt * scale)
        if end_y_px < 5:
            return None, False

        zone = arr[:end_y_px, :]
        flat = zone.reshape(-1, 3)
        non_white = flat[~((flat[:, 0] > 240) & (flat[:, 1] > 240) & (flat[:, 2] > 240))]
        if len(non_white) < 50:
            return None, False  # header sur blanc

        r, g, b = np.median(non_white, axis=0).astype(int)
        target = np.array([r, g, b])
        diffs = np.abs(non_white - target).sum(axis=1)
        ratio = float((diffs < 30).sum() / len(flat))

        if ratio < 0.30:
            return None, False  # pas assez uni pour parler de "fond"

        # Bandeau plein-largeur ? on regarde les 5 premières lignes de pixels
        top_strip = arr[:max(2, int(end_y_px * 0.3)), :]
        top_flat = top_strip.reshape(-1, 3)
        top_diffs = np.abs(top_flat - target).sum(axis=1)
        full_width = (top_diffs < 30).sum() / len(top_flat) > 0.85

        return f"#{r:02X}{g:02X}{b:02X}", bool(full_width)

    @staticmethod
    def _compute_section_gap(text_blocks: list) -> float:
        """Gap vertical médian entre 2 blocs successifs (en mm)."""
        if len(text_blocks) < 2:
            return 0.0

        sorted_b = sorted(
            [b for b in text_blocks if b.get("bbox")],
            key=lambda b: b["bbox"][1],
        )
        gaps = []
        for prev, curr in zip(sorted_b, sorted_b[1:]):
            gap = curr["bbox"][1] - prev["bbox"][3]
            if 0 < gap < 60:  # ignore les giga-gaps (sauts de section)
                gaps.append(gap)

        if not gaps:
            return 0.0

        import numpy as np
        return float(np.median(gaps) * PT_TO_MM)

    @staticmethod
    def _detect_horizontal_rules(page) -> List[float]:
        """Détecte des lignes horizontales (séparateurs) en y mm."""
        rules: List[float] = []
        try:
            drawings = page.get_drawings()
        except Exception:
            return rules

        for d in drawings:
            for item in d.get("items", []):
                if not item:
                    continue
                op = item[0]
                if op != "l":  # 'l' = line
                    continue
                p1, p2 = item[1], item[2]
                # Ligne horizontale si delta y < 1pt
                if abs(p2.y - p1.y) < 1.0 and abs(p2.x - p1.x) > 30:
                    rules.append(p1.y * PT_TO_MM)

        return sorted(set(round(r, 1) for r in rules))