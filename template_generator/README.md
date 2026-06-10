# Karria — Générateur de templates depuis PDF

Outil de génération automatique de templates CV (+ LM optionnelle) à partir
d'un simple PDF, avec fidélité visuelle maximale et alignement strict sur
le pipeline backend Karria.

## Ce qu'il fait

À partir d'un PDF CV (et optionnellement d'un PDF LM), le script produit
**exactement** la structure de dossier attendue par le backend `submit_full` :

```
outputs/{cv_name}/
├── template.html         ← Jinja2 robuste à toutes les données utilisateur
├── style.css             ← référence humaine (le CSS est aussi inline dans template.html)
├── preview.pdf           ← copie du PDF source (utilisé par pipeline preview du backend)
├── schema.json           ← contrat de données pour cv_data_agent
├── data.json             ← exemple fidèle au PDF original (utilisé pour previews)
├── infos.json            ← métadonnées complètes pour MachineFullSubmitMeta
└── lm/                   ← si LM fournie
    ├── lm_template.html
    ├── lm_style.css
    ├── lm_preview.pdf
    ├── lm_schema.json
    └── lm_data.json
```

## Améliorations clé vs version précédente

| Problème ancien                                          | Solution v3                                                               |
| -------------------------------------------------------- | ------------------------------------------------------------------------- |
| Prompt MASTER tronqué (s'arrêtait au CSS)                | Prompts complets et chirurgicaux pour CV et LM séparément                 |
| `infos.json` non aligné avec `MachineFullSubmitMeta`     | Format strictement aligné — prêt pour `submit_full`                       |
| Pas de pré-analyse PDF → l'IA "devine" couleurs/fonts    | PyMuPDF extrait les vraies couleurs (clustering RGB) et fonts             |
| Aucune validation post-génération                        | 5 validations + retry avec feedback ciblé si échec                        |
| Variables Jinja2 non alignées avec `cv_data_agent`       | Liste exhaustive injectée dans le prompt — variables exactes              |
| Robustesse aux données vides non garantie                | `{% if section %}` exigé partout — validé par rendu Jinja2 sur data.json  |
| `is_premium` / `price` non gérés dans le format de sortie | Champs présents et configurables via CLI ou kwargs                        |

## Installation

```bash
# Dépendances Python
pip install pymupdf pillow scikit-learn pdf2image jinja2 google-genai

# Dépendance système pour pdf2image (rendu PDF en images)
# Ubuntu/Debian :
sudo apt-get install poppler-utils
# macOS :
brew install poppler
```

## Configuration

Le script lit `GEMINI_API_KEY` depuis l'environnement :

```bash
export GEMINI_API_KEY="ton_api_key"
export GEMINI_MODEL="gemini-2.5-pro"  # ou autre — facultatif
export GEN_OUTPUT_DIR="./outputs"     # facultatif
```

## Usage CLI

### Mode complet (CV + LM, premium)

```bash
python -m tools.template_generator.generate_templates \
  --cv  ./inputs/modern-blue.pdf \
  --lm  ./inputs/modern-blue-lm.pdf \
  --label "Modern Blue" \
  --category modern \
  --premium \
  --price 4.99 \
  --tags "modern,tech,blue" \
  --output ./outputs
```

### Mode CV seul (gratuit)

```bash
python -m tools.template_generator.generate_templates \
  --cv ./inputs/classic.pdf \
  --label "Classic Pro" \
  --category classic \
  --output ./outputs
```

### Mode interactif (sans args)

```bash
python -m tools.template_generator.generate_templates
```

Le script te guide avec un sélecteur de PDF et te demande les métadonnées.

## Usage programmatique

```python
from pathlib import Path
from tools.template_generator import generate

generate(
    cv_pdf_path="./inputs/modern.pdf",
    lm_pdf_path="./inputs/modern-lm.pdf",
    label="Modern Blue",
    output_dir=Path("./outputs"),
    category="modern",
    is_premium=True,
    price=4.99,
    tags=["modern", "tech", "blue"],
)
```

## Pipeline interne

```
PDF CV
   ↓
1. PDFAnalyzer  →  fonts détectées, palette RGB, dimensions, photo détectée
   ↓
2. PromptBuilder  →  prompt chirurgical avec valeurs réelles injectées
   ↓
3. GeminiCaller  →  IA reçoit (PDF rendered as images) + prompt
   ↓
4. ResponseParser  →  extrait template.html, style.css, schema.json, data.json
   ↓
5. Validator  →  5 niveaux de validation (structure, JSON, HTML↔schema, rendu Jinja2, no external CSS)
   ↓
6. Si validation KO  →  retry avec correction prompt ciblé (max 2 fois)
   ↓
7. InfosBuilder  →  construit infos.json aligné MachineFullSubmitMeta
   ↓
8. FolderWriter  →  écrit la structure complète sur disque
```

## Validations effectuées

Avant de livrer un template, le script vérifie :

1. **Structure** : les 4 fichiers (HTML/CSS/schema/data) sont présents
2. **JSON valide** : schema.json et data.json sont bien parsables
3. **CSS inline** : pas de `<link rel="stylesheet">` externe (sauf Google Fonts)
4. **Cohérence HTML ↔ schema** : toutes les variables utilisées dans le HTML
   sont soit dans la liste autorisée (`fullName`, `experiences`, etc.),
   soit déclarées dans le schéma
5. **Rendu Jinja2** : le template est rendu avec data.json — si ça crash,
   ça crashera aussi en production

Si une validation échoue, le script **relance automatiquement** l'IA avec
un prompt de correction qui inclut les erreurs exactes à corriger.

## Format infos.json

Le `infos.json` produit est aligné EXACTEMENT avec `MachineFullSubmitMeta` :

```json
{
  "version": "v3",
  "generated_at": "2026-05-01T17:30:00+00:00",
  "with_cover_letter": true,

  "cv": {
    "name": "modern-blue",
    "label": "Modern Blue",
    "category": "modern",
    "description": "Template CV Modern Blue",
    "primary_color": "#1A73E8",
    "font_family": "Inter",
    "is_premium": true,
    "price": 4.99,
    "is_active": true,
    "has_photo": false,
    "tags": ["modern", "blue", "two-columns", "no-photo"],
    "review_description": "",
    "layout_key": "two-column-left-sidebar"
  },

  "cover_letter": {
    "name": "modern-blue-lm",
    "label": "Modern Blue — Lettre",
    "category": "modern",
    "description": "Lettre de motivation associée au template Modern Blue",
    "primary_color": "#1A73E8",
    "font_family": "Inter",
    "layout_key": "standard-letter"
  },

  "_extraction_meta": {
    "cv": {
      "fonts_detected":     [{"name": "Inter", "size": 11.0, "weight": "normal", "style": "normal"}, ...],
      "color_palette":      [{"hex": "#1A73E8", "usage_pct": 12.4}, ...],
      "estimated_columns":  2,
      "has_photo":          false,
      "page_dimensions_mm": [210.0, 297.0],
      "is_a4":              true
    },
    "lm": { ... }
  }
}
```

Le bloc `_extraction_meta` est **informatif** — il sert à l'audit et à la
debug. Tu peux l'ignorer côté backend (ne pas le passer dans `MachineFullSubmitMeta`).

## Soumission au backend

Côté script (côté admin), tu peux maintenant lire `infos.json` et appeler
`CVTemplateService.submit_full` directement :

```python
import json
from pathlib import Path
from app.cv_template.schemas import MachineFullSubmitMeta
from app.cv_template.service import CVTemplateService

template_dir = Path("./outputs/modern-blue")
infos = json.loads((template_dir / "infos.json").read_text())

# Préfixe les champs CV/LM pour matcher MachineFullSubmitMeta
meta = MachineFullSubmitMeta(
    cv_name=infos["cv"]["name"],
    cv_label=infos["cv"]["label"],
    cv_category=infos["cv"]["category"],
    cv_description=infos["cv"]["description"],
    cv_primary_color=infos["cv"]["primary_color"],
    cv_font_family=infos["cv"]["font_family"],
    cv_is_premium=infos["cv"]["is_premium"],
    cv_price=infos["cv"]["price"],
    cv_is_active=infos["cv"]["is_active"],
    cv_has_photo=infos["cv"]["has_photo"],
    cv_tags=infos["cv"]["tags"],
    cv_review_description=infos["cv"]["review_description"],
    cv_layout_key=infos["cv"]["layout_key"],
    with_cover_letter=infos["with_cover_letter"],
    lm_name=(infos.get("cover_letter") or {}).get("name"),
    lm_label=(infos.get("cover_letter") or {}).get("label"),
    lm_category=(infos.get("cover_letter") or {}).get("category", "classic"),
    lm_description=(infos.get("cover_letter") or {}).get("description"),
    lm_primary_color=(infos.get("cover_letter") or {}).get("primary_color"),
    lm_font_family=(infos.get("cover_letter") or {}).get("font_family"),
    lm_layout_key=(infos.get("cover_letter") or {}).get("layout_key", "standard-letter"),
)

cv_html  = (template_dir / "template.html").read_text()
cv_css   = (template_dir / "style.css").read_text()
cv_pdf   = (template_dir / "preview.pdf").read_bytes()
cv_schema = json.loads((template_dir / "schema.json").read_text())
cv_data   = json.loads((template_dir / "data.json").read_text())
cv_infos  = infos  # le infos.json complet

lm_html = lm_css = lm_pdf = lm_schema = lm_data = None
if infos["with_cover_letter"]:
    lm_dir   = template_dir / "lm"
    lm_html  = (lm_dir / "lm_template.html").read_text()
    lm_css   = (lm_dir / "lm_style.css").read_text()
    lm_pdf   = (lm_dir / "lm_preview.pdf").read_bytes()
    lm_schema = json.loads((lm_dir / "lm_schema.json").read_text())
    lm_data   = json.loads((lm_dir / "lm_data.json").read_text())

result = await CVTemplateService.submit_full(
    meta=meta,
    cv_html=cv_html,
    cv_css=cv_css,
    cv_pdf_bytes=cv_pdf,
    cv_schema_json=cv_schema,
    cv_infos_json=cv_infos,
    cv_example_data=cv_data,
    lm_html=lm_html,
    lm_css=lm_css,
    lm_pdf_bytes=lm_pdf,
    lm_schema_json=lm_schema,
    lm_example_data=lm_data,
)

print("✅ Template enregistré :", result.cv_template.id)
```

## Limitations connues

1. **Fidélité PDF→HTML n'est pas absolue.** Certaines PDFs utilisent des
   éléments graphiques vectoriels complexes qui ne se traduisent pas
   parfaitement en HTML/CSS. Le script vise 90-95% de fidélité visuelle,
   pas 100% pixel-perfect.

2. **Fonts non Google Fonts.** Si la PDF utilise une font payante (Adobe,
   Monotype...), le script choisit la Google Font la plus proche. La
   substitution est listée dans `schema.json.meta.fonts_substitutions`.

3. **Layouts très créatifs** (collages, photos pleine page, infographies
   complexes) ne sont pas le sweet spot — le script est optimisé pour
   les CV professionnels classiques (1 ou 2 colonnes).

4. **Coût IA.** Chaque génération CV consomme ~30-50K tokens (PDF en
   images = lourd). Si tu as 100 templates à générer, prévois un budget
   API en conséquence.

## Ce qui pourrait être ajouté plus tard

- **Itération visuelle** : générer le PDF du template → comparer pixel-à-pixel
  au PDF source → demander à l'IA de corriger les divergences. Cher mais
  donnerait du 99%+ de fidélité.
- **Cache de templates similaires** : si deux PDFs ont une structure proche,
  réutiliser le template précédent comme base.
- **Tests automatiques de robustesse** : générer plusieurs `data.json` aux
  contenus extrêmes (utilisateur sans expérience, utilisateur avec 15 expériences,
  noms longs, etc.) et vérifier que le template ne casse jamais.
