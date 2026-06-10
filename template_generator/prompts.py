# template_generator/prompts.py
"""
Prompts pour la génération de templates Karria — version v3.

Améliorations vs v2 :
  • Mesures précises injectées (marges, sidebar width, gaps, header) → l'IA
    a des chiffres en mm, plus de "fais un truc fidèle"
  • Self-check CV CORRIGÉ (les anciennes lignes mentionnaient recipient-info,
    closing, etc. — c'était du copier-coller du prompt LM)
  • Format plus dense : moins de bla-bla, plus d'instructions actionnables
  • Nouveau prompt visual_critic (utilisé par la 2e passe IA pour comparer
    le HTML rendu au PDF original)
"""

from __future__ import annotations

from textwrap import dedent
from typing import Any, Optional

try:
    from .pdf_analyzer import PDFAnalysis
except ImportError:  # exécution directe: python template_generator/generate_templates.py
    from pdf_analyzer import PDFAnalysis


def _limit_value(schema_limits: Any, attr: str, fallback: int) -> int:
    if schema_limits is None:
        return fallback
    value = getattr(schema_limits, attr, None)
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _schema_limits_prompt_block(schema_limits: Any) -> str:
    if schema_limits is None:
        return ""

    if hasattr(schema_limits, "to_prompt_block"):
        return schema_limits.to_prompt_block()

    return dedent(f"""\
        ═══════════════════════════════════════════════════════════════════════
        LIMITES PHYSIQUES CALCULÉES — À RESPECTER STRICTEMENT
        ═══════════════════════════════════════════════════════════════════════
        Ces limites remplacent les valeurs génériques. Elles sont calculées depuis
        la géométrie réelle du PDF : marges, sidebar, header, photo, densité texte.

        - summary.maxLength ≤ {_limit_value(schema_limits, "summary_max_length", 360)}
        - experiences.maxItems ≤ {_limit_value(schema_limits, "experiences_max_items", 4)}
        - experiences[].description.maxLength ≤ {_limit_value(schema_limits, "experience_description_max_length", 160)}
        - education.maxItems ≤ {_limit_value(schema_limits, "education_max_items", 2)}
        - skills.maxItems ≤ {_limit_value(schema_limits, "skills_max_items", 8)}
        - languages.maxItems ≤ {_limit_value(schema_limits, "languages_max_items", 3)}
        - interests.maxItems ≤ {_limit_value(schema_limits, "interests_max_items", 0)}
        - references.maxItems ≤ {_limit_value(schema_limits, "references_max_items", 0)}

        Si le contenu source dépasse ces limites, sélectionne les éléments les plus
        récents, pertinents et mesurables. N'ajoute jamais une section entière si elle
        risque de créer un débordement A4.
    """)


# ═════════════════════════════════════════════════════════════════════════════
# PROMPT CV
# ═════════════════════════════════════════════════════════════════════════════

def build_cv_prompt(
    analysis: PDFAnalysis,
    expected_layout: str = "two-column-left-sidebar",
    schema_limits: Any = None,
) -> str:
    """Prompt complet pour générer un template CV depuis un PDF."""
    pre_analysis = analysis.to_prompt_summary()

    summary_max_length = _limit_value(schema_limits, "summary_max_length", 500)
    experiences_max_items = _limit_value(schema_limits, "experiences_max_items", 6)
    experience_description_max_length = _limit_value(schema_limits, "experience_description_max_length", 350)
    education_max_items = _limit_value(schema_limits, "education_max_items", 4)
    skills_max_items = _limit_value(schema_limits, "skills_max_items", 10)
    languages_max_items = _limit_value(schema_limits, "languages_max_items", 5)
    interests_max_items = _limit_value(schema_limits, "interests_max_items", 6)
    references_max_items = _limit_value(schema_limits, "references_max_items", 0)
    schema_limits_block = _schema_limits_prompt_block(schema_limits)

    # Suggestion de grid si on a une sidebar mesurée
    grid_hint = ""
    if analysis.sidebar:
        sb_w = round(analysis.sidebar.width_mm)
        if analysis.sidebar.position == "left":
            grid_hint = f"  • CSS grid suggéré : grid-template-columns: {sb_w}mm 1fr;"
        else:
            grid_hint = f"  • CSS grid suggéré : grid-template-columns: 1fr {sb_w}mm;"

    margin_hint = ""
    if analysis.margins:
        margin_hint = (
            f"  • Le `.page` DOIT utiliser EXACTEMENT : {analysis.margins.to_css()}\n"
            f"  • Si tu utilises grid avec une sidebar, c'est `padding: 0` sur .page\n"
            f"    et tu appliques le padding sur la zone main hors-sidebar."
        )

    return dedent(f"""\
        Tu es un expert en design web et ingénierie de templates de CV.
        Mission : reproduire le PDF fourni en HTML/CSS avec une fidélité PIXEL-PERFECT.

        ═══════════════════════════════════════════════════════════════════════
        OBJECTIF
        ═══════════════════════════════════════════════════════════════════════
        Produis 4 fichiers :
          1. template.html  — Jinja2, CSS inline dans <style>, A4 strict
          2. style.css      — copie du CSS pour référence humaine
          3. schema.json    — contrat de données pour cv_data_agent
          4. data.json      — données d'exemple FIDÈLES au PDF (pour preview)

        Les mesures ci-dessous sont MESURÉES AU MILLIMÈTRE depuis le PDF.
        Tu DOIS les utiliser telles quelles. Pas d'arrondi créatif.
        Les limites de schema ci-dessous sont des limites PHYSIQUES DE RENDU,
        pas de simples préférences. Elles doivent empêcher tout débordement A4.

        ═══════════════════════════════════════════════════════════════════════
        {pre_analysis}
        ═══════════════════════════════════════════════════════════════════════
{schema_limits_block}

        ═══════════════════════════════════════════════════════════════════════

        ═══════════════════════════════════════════════════════════════════════
        RÈGLES BLOQUANTES (échec validation si non respectées)
        ═══════════════════════════════════════════════════════════════════════

        🟥 A4 STRICT
        ─────────────
        - .page : `width: 210mm; height: 297mm; max-height: 297mm; overflow: hidden;`
        - Le CV doit tenir sur UNE page A4. Le contenu doit être réduit via schema.json,
          jamais en laissant la page grandir silencieusement.
        - `@page {{ size: A4; margin: 0; }}`
        - `*, *::before, *::after {{ box-sizing: border-box; }}`
        - Sur tous les éléments visuels (sidebar, badges) :
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;

        🟥 MARGES MESURÉES (depuis l'analyse ci-dessus)
        ─────────────────────────────────────────────
{margin_hint or "  • Si non mesurées, fallback : padding: 18mm;"}

        🟥 LAYOUT EN GRID OU FLEX (pas en absolute positioning)
        ──────────────────────────────────────────────────────
        - Si sidebar détectée : utilise CSS Grid pour la séparation main/sidebar
{grid_hint}
        - JAMAIS de position: absolute pour le layout principal
        - JAMAIS de width/height en % sur les conteneurs internes
        - Unités : `mm` pour marges/paddings/largeurs ; `px` autorisé seulement
          pour bordures fines, ombres, et marges <5mm internes

        🟥 CSS INLINE DANS LE HTML
        ─────────────────────────
        Le `template.html` NE DOIT PAS contenir `<link rel="stylesheet">` vers
        un fichier externe. Tout le CSS DOIT être dans un `<style>` du <head>.
        Exception : Google Fonts via `<link href="https://fonts.googleapis.com/...">`.

        🟥 COULEURS — VARIABLES CSS DANS :root
        ─────────────────────────────────────
        Toutes les couleurs DOIVENT être déclarées dans `:root {{ }}` puis
        référencées via `var(--name)`. Utilise les hex EXACTS de la pré-analyse.
        Pas de hex hardcodé dans les règles.

        🟥 FONTS — GOOGLE FONTS UNIQUEMENT
        ─────────────────────────────────
        - Charge via `<link href="https://fonts.googleapis.com/css2?family=...">`
        - Substitutions courantes :
          Helvetica/Arial → Inter ; Calibri → Lato ; Times → Cormorant Garamond ;
          Georgia → Lora ; Avenir → Nunito ; Futura → Jost
        - Indique les substitutions dans schema.json.meta.fonts_substitutions

        🟥 ZÉRO JAVASCRIPT — ZÉRO IMAGE EXTERNE (sauf {{photo}})
        ──────────────────────────────────────────────────────
        Aucun <script>, aucun logo/badge image. Tout en pur CSS.

        ═══════════════════════════════════════════════════════════════════════
        VARIABLES JINJA2 — NOMS EXACTS (NE PAS INVENTER)
        ═══════════════════════════════════════════════════════════════════════
        Ces variables sont injectées par `cv_data_agent` du backend Karria.

        ▼ HEADER
          {{{{ fullName }}}}, {{{{ jobTitle }}}}, {{{{ photo }}}}, {{{{ availability }}}}

        ▼ RÉSUMÉ
          {{{{ summary }}}}                  → string, 1ère personne

        ▼ CONTACT
          {{{{ contact.phone }}}}, {{{{ contact.email }}}}, {{{{ contact.address }}}},
          {{{{ contact.linkedin }}}}, {{{{ contact.website }}}}

        ▼ LABELS i18n (JAMAIS texte hardcodé pour les titres de section)
          {{{{ labels.contact }}}}, {{{{ labels.experiences }}}}, {{{{ labels.education }}}},
          {{{{ labels.skills }}}}, {{{{ labels.languages }}}}, {{{{ labels.interests }}}},
          {{{{ labels.profile }}}}

        ▼ EXPÉRIENCES (`{{% for exp in experiences %}}`)
          {{{{ exp.position }}}}, {{{{ exp.company }}}}, {{{{ exp.location }}}},
          {{{{ exp.start }}}}, {{{{ exp.end }}}}, {{{{ exp.description }}}}

        ▼ FORMATION (`{{% for edu in education %}}` — fallback `educations` si absent)
          {{{{ edu.degree }}}}, {{{{ edu.school }}}}, {{{{ edu.location }}}},
          {{{{ edu.start }}}}, {{{{ edu.end }}}}

        ▼ COMPÉTENCES (`{{% for skill in skills %}}`)
          {{{{ skill.name }}}}, {{{{ skill.level }}}} (int 1-5)
          Barres : `{{% for bar in skill.level | make_bars %}}...{{% endfor %}}`

        ▼ LANGUES (`{{% for lang in languages %}}`)
          {{{{ lang.name }}}}, {{{{ lang.level }}}} (int 1-5)

        ▼ CENTRES D'INTÉRÊT (`{{% for interest in interests %}}`)
          {{{{ interest.icon }}}} (emoji), {{{{ interest.label }}}}

        ═══════════════════════════════════════════════════════════════════════
        ROBUSTESSE — CHAQUE SECTION GÈRE L'ABSENCE DE DONNÉES
        ═══════════════════════════════════════════════════════════════════════

        ✅ TOUJOURS :
        ```jinja2
        {{% if photo %}}<img src="{{{{ photo }}}}" alt="...">{{% endif %}}
        {{% if jobTitle %}}<p class="job-title">{{{{ jobTitle }}}}</p>{{% endif %}}
        {{% if experiences %}}
          <section class="experiences">
            <h2>{{{{ labels.experiences }}}}</h2>
            {{% for exp in experiences %}}...{{% endfor %}}
          </section>
        {{% endif %}}
        ```

        ❌ JAMAIS :
        - Section vide visible (toujours protéger par `{{% if %}}`)
        - Texte hardcodé pour les titres (toujours `{{{{ labels.X }}}}`)
        - Couleur hex en dur dans les règles (toujours `var(--name)`)
        - Variable inventée comme `{{{{ candidat.nom }}}}`

        ═══════════════════════════════════════════════════════════════════════
        FICHIER 3 — schema.json (contrat exact)
        ═══════════════════════════════════════════════════════════════════════
        ```json
        {{
          "version": "1.0",
          "meta": {{
            "layout": "{expected_layout}",
            "primary_color": "<hex>",
            "fonts": ["<font1>", "<font2>"],
            "fonts_substitutions": {{}},
            "has_photo": <true|false>
          }},
          "fields": {{
            "fullName":     {{ "type": "string",  "required": true }},
            "jobTitle":     {{ "type": "string",  "required": false }},
            "photo":        {{ "type": "string",  "required": false }},
            "summary":      {{ "type": "string",  "required": true,  "maxLength": {summary_max_length} }},
            "availability": {{ "type": "string",  "required": false }},
            "preferred_language": {{ "type": "string", "required": false }},
            "contact": {{
              "type": "object", "required": true,
              "fields": {{
                "phone":   {{ "type": "string", "required": false }},
                "email":   {{ "type": "string", "required": false }},
                "address": {{ "type": "string", "required": false }}
              }}
            }},
            "labels": {{
              "type": "object", "required": true,
              "fields": {{
                "contact":     {{ "type": "string", "required": true }},
                "experiences": {{ "type": "string", "required": true }},
                "education":   {{ "type": "string", "required": true }},
                "skills":      {{ "type": "string", "required": true }},
                "languages":   {{ "type": "string", "required": true }},
                "interests":   {{ "type": "string", "required": true }},
                "profile":     {{ "type": "string", "required": false }}
              }}
            }},
            "experiences": {{
              "type": "array", "required": false, "maxItems": {experiences_max_items},
              "item": {{ "type": "object", "fields": {{
                "position": {{ "type": "string", "required": true }},
                "company":  {{ "type": "string", "required": true }},
                "location": {{ "type": "string", "required": false }},
                "start":    {{ "type": "string", "required": true }},
                "end":      {{ "type": "string", "required": false }},
                "description": {{ "type": "string", "required": false, "maxLength": {experience_description_max_length} }}
              }} }}
            }},
            "education": {{
              "type": "array", "required": false, "maxItems": {education_max_items},
              "item": {{ "type": "object", "fields": {{
                "degree":   {{ "type": "string", "required": true }},
                "school":   {{ "type": "string", "required": true }},
                "location": {{ "type": "string", "required": false }},
                "start":    {{ "type": "string", "required": false }},
                "end":      {{ "type": "string", "required": false }}
              }} }}
            }},
            "skills": {{
              "type": "array", "required": false, "maxItems": {skills_max_items},
              "item": {{ "type": "object", "fields": {{
                "name":  {{ "type": "string",  "required": true }},
                "level": {{ "type": "integer", "required": true, "min": 1, "max": 5 }}
              }} }}
            }},
            "languages": {{
              "type": "array", "required": false, "maxItems": {languages_max_items},
              "item": {{ "type": "object", "fields": {{
                "name":  {{ "type": "string",  "required": true }},
                "level": {{ "type": "integer", "required": true, "min": 1, "max": 5 }}
              }} }}
            }},
            "interests": {{
              "type": "array", "required": false, "maxItems": {interests_max_items},
              "item": {{ "type": "object", "fields": {{
                "icon":  {{ "type": "string", "required": false }},
                "label": {{ "type": "string", "required": true }}
              }} }}
            }}
            ,
            "references": {{
              "type": "array", "required": false, "maxItems": {references_max_items},
              "item": {{ "type": "object", "fields": {{
                "name":  {{ "type": "string", "required": true }},
                "title": {{ "type": "string", "required": false }},
                "phone": {{ "type": "string", "required": false }},
                "email": {{ "type": "string", "required": false }}
              }} }}
            }}
          }}
        }}
        ```

        ═══════════════════════════════════════════════════════════════════════
        FICHIER 4 — data.json (fidèle au PDF)
        ═══════════════════════════════════════════════════════════════════════
        - Reproduit FIDÈLEMENT le contenu visible (mêmes noms, intitulés, dates)
        - `summary` à la PREMIÈRE PERSONNE ("Je", "J'ai", "Mon parcours")
        - `skills.level` et `languages.level` : entiers 1-5
        - Pas de photo dans le PDF → `"photo": ""`
        - Section absente du PDF → OMETS-LA (pas de tableau vide)
        - Respecte STRICTEMENT les limites dynamiques du schema.json généré :
          summary≤{summary_max_length}, experiences≤{experiences_max_items},
          description expérience≤{experience_description_max_length},
          education≤{education_max_items}, skills≤{skills_max_items},
          languages≤{languages_max_items}, interests≤{interests_max_items},
          references≤{references_max_items}.
        - Si le PDF original contient plus d'éléments, garde uniquement les plus récents,
          pertinents et visibles sans débordement.

        Format :
        ```json
        {{
          "fullName": "...",
          "jobTitle": "",
          "photo": "",
          "summary": "Je suis ...",
          "availability": "Disponible immédiatement",
          "preferred_language": "fr",
          "contact": {{ "phone": "...", "email": "...", "address": "..." }},
          "labels": {{ ... }},
          "experiences": [ ... ],
          "education": [ ... ],
          "skills": [ {{ "name": "...", "level": 4 }} ],
          "languages": [ {{ "name": "...", "level": 5 }} ],
          "interests": [ {{ "icon": "🎵", "label": "..." }} ]
        }}
        ```

        ═══════════════════════════════════════════════════════════════════════
        FORMAT DE RÉPONSE STRICT
        ═══════════════════════════════════════════════════════════════════════
        Réponds avec exactement 4 blocs de code, dans CET ORDRE :

        ```html
        <!DOCTYPE html>...
        ```

        ```css
        :root {{ ... }}...
        ```

        ```json
        {{ "version": "1.0", "meta": {{...}}, "fields": {{...}} }}
        ```
        (= schema.json — reconnaissable à "fields" + "meta")

        ```json
        {{ "fullName": "...", ... }}
        ```
        (= data.json — reconnaissable à "fullName" en racine)

        Aucun texte hors des blocs.

        ═══════════════════════════════════════════════════════════════════════
        SELF-CHECK CV (vérifie AVANT d'émettre)
        ═══════════════════════════════════════════════════════════════════════
        □ template.html commence par <!DOCTYPE html> ?
        □ <style> dans <head> contient TOUT le CSS ?
        □ Aucun <link> CSS sauf Google Fonts ?
        □ Toutes les couleurs en var(--name) depuis :root ?
        □ Marges .page = celles MESURÉES dans la pré-analyse ?
        □ Sidebar largeur = celle MESURÉE en mm ?
        □ Chaque section optionnelle entourée de {{% if section %}} ?
        □ Tous les titres de section utilisent labels.* ?
        □ Variables Jinja2 = noms exacts de la liste ?
        □ schema.json.meta.layout = "{expected_layout}" ?
        □ schema.json.fields couvre TOUTES les variables du HTML ?
        □ data.json.summary à la PREMIÈRE PERSONNE ?
        □ data.json reproduit fidèlement le contenu du PDF ?
        □ Format A4 strict (210mm × height 297mm, overflow hidden) ?
        □ schema.json utilise les limites dynamiques calculées, pas des constantes génériques ?
        □ data.json respecte toutes les limites du schema.json ?
        □ Aucun JS ?

        Émets ta réponse maintenant — 4 blocs de code, rien d'autre.
    """)


# ═════════════════════════════════════════════════════════════════════════════
# PROMPT LM (lettre de motivation)
# ═════════════════════════════════════════════════════════════════════════════

def build_lm_prompt(
    analysis: PDFAnalysis,
    expected_layout: str = "standard-letter",
) -> str:
    """Prompt strict pour LM — UNE PAGE A4, densité contrôlée."""
    pre_analysis = analysis.to_prompt_summary()

    margin_hint = ""
    if analysis.margins:
        margin_hint = (
            f"  • .page padding mesuré : {analysis.margins.to_css()}\n"
            f"    (si la lettre déborde, réduis-le légèrement, jamais l'augmente)"
        )

    return dedent(f"""\
        Tu es un expert en typographie de lettres formelles françaises et en
        intégration HTML/CSS pour PDF A4.

        Mission : produire un template Karria fidèle au PDF de lettre fourni,
        professionnel, robuste, qui tient STRICTEMENT sur UNE SEULE PAGE A4
        avec du contenu réel (3-4 paragraphes).

        ═══════════════════════════════════════════════════════════════════════
        OBJECTIF — 4 fichiers
        ═══════════════════════════════════════════════════════════════════════
          1. lm_template.html  — Jinja2, CSS inline, A4 strict UNE PAGE
          2. lm_style.css      — copie exacte du CSS
          3. lm_schema.json    — contrat pour cover_letter_agent
          4. lm_data.json      — données d'exemple fidèles au PDF

        ═══════════════════════════════════════════════════════════════════════
        {pre_analysis}
        ═══════════════════════════════════════════════════════════════════════

        ═══════════════════════════════════════════════════════════════════════
        RÈGLES BLOQUANTES — A4 UNE PAGE STRICT
        ═══════════════════════════════════════════════════════════════════════

        🟥 OBLIGATOIRE
        ──────────────
        - @page {{ size: A4; margin: 0; }}
        - html, body : width: 210mm; height: 297mm; margin: 0; padding: 0; overflow: hidden;
        - .page :
            width: 210mm;
            height: 297mm;          ← height fixe, PAS min-height
            max-height: 297mm;
            margin: 0;
            padding: 16mm 18mm;     ← OU les marges mesurées si plus petites
            overflow: hidden;
            box-sizing: border-box;
            background: white;
            display: flex;
            flex-direction: column;

{margin_hint}

        🟥 INTERDIT
        ──────────
        - min-height: 297mm sur .page (utiliser height: 297mm)
        - margin: 20mm auto sur .page
        - box-shadow sur .page (rendu PDF : pas d'ombre)
        - background gris autour de la page
        - header trop décoratif qui consomme la page

        🟥 DENSITÉ TYPOGRAPHIQUE PLAFONNÉE
        ────────────────────────────────
        - body font-size      : 10pt à 10.5pt
        - body line-height    : 1.34 à 1.42
        - .full-name / h1     : 24pt à 32pt MAX
        - .header margin-bot. : 6mm à 12mm MAX
        - .recipient padding-top : 0 à 6mm MAX
        - .paragraph margin-bot. : 6px à 9px MAX
        - .closing margin-top    : 8px à 12px MAX

        Si le PDF source a un grand nom décoratif, reproduis l'esprit visuel
        sans cloner la taille brute si elle empêche la lettre de tenir.

        ═══════════════════════════════════════════════════════════════════════
        VARIABLES JINJA2 AUTORISÉES
        ═══════════════════════════════════════════════════════════════════════

        Expéditeur : {{{{ fullName }}}}, {{{{ jobTitle }}}}, {{{{ contact.phone }}}},
                     {{{{ contact.email }}}}, {{{{ contact.address }}}}

        Destinataire : {{{{ recipient.company }}}}, {{{{ recipient.address }}}},
                       {{{{ recipient.name }}}}

        Métadonnées : {{{{ city }}}}, {{{{ date }}}}

        Contenu : {{{{ labels.subject }}}}, {{{{ subject }}}}, {{{{ salutation }}}},
                  paragraphs (liste), {{{{ closing }}}}

        Paragraphes :
        ```jinja2
        {{% for para in paragraphs %}}
          <p class="paragraph">{{{{ para }}}}</p>
        {{% endfor %}}
        ```

        Champs optionnels protégés :
        ```jinja2
        {{% if contact.phone %}}<p>{{{{ contact.phone }}}}</p>{{% endif %}}
        {{% if recipient.name %}}<p>À l'attention de {{{{ recipient.name }}}}</p>{{% endif %}}
        ```

        ═══════════════════════════════════════════════════════════════════════
        LANGUE — FRANÇAIS PARTOUT
        ═══════════════════════════════════════════════════════════════════════
        - preferred_language : "fr"
        - salutation : "Madame, Monsieur,"
        - labels.subject : "Objet"
        - date en français
        - closing court et professionnel

        Closing recommandé : "Je vous prie d'agréer, Madame, Monsieur, mes salutations distinguées."
        Évite : "Dans l'attente de votre réponse, je vous prie d'agréer..."

        ═══════════════════════════════════════════════════════════════════════
        CONTRAT lm_schema.json
        ═══════════════════════════════════════════════════════════════════════
        ```json
        {{
          "version": "1.0",
          "meta": {{
            "layout": "{expected_layout}",
            "primary_color": "<hex>",
            "fonts": ["<font-body>", "<font-heading>"]
          }},
          "fields": {{
            "fullName": {{ "type": "string", "required": true }},
            "jobTitle": {{ "type": "string", "required": false }},
            "city": {{ "type": "string", "required": false }},
            "date": {{ "type": "string", "required": true }},
            "subject": {{ "type": "string", "required": true, "maxLength": 180 }},
            "salutation": {{ "type": "string", "required": true, "maxLength": 60 }},
            "closing": {{ "type": "string", "required": true, "maxLength": 140 }},
            "preferred_language": {{ "type": "string", "required": false }},
            "contact": {{
              "type": "object", "required": true,
              "fields": {{
                "phone": {{ "type": "string", "required": false }},
                "email": {{ "type": "string", "required": false }},
                "address": {{ "type": "string", "required": false }}
              }}
            }},
            "recipient": {{
              "type": "object", "required": true,
              "fields": {{
                "company": {{ "type": "string", "required": true }},
                "address": {{ "type": "string", "required": false }},
                "name": {{ "type": "string", "required": false }}
              }}
            }},
            "labels": {{
              "type": "object", "required": true,
              "fields": {{
                "subject": {{ "type": "string", "required": true }}
              }}
            }},
            "paragraphs": {{
              "type": "array", "required": true,
              "minItems": 3, "maxItems": 4,
              "item": {{ "type": "string", "maxLength": 420 }}
            }}
          }}
        }}
        ```

        ═══════════════════════════════════════════════════════════════════════
        lm_data.json
        ═══════════════════════════════════════════════════════════════════════
        - 3 à 4 paragraphes maximum, chacun court
        - closing maximum 140 caractères
        - preferred_language = "fr"

        ═══════════════════════════════════════════════════════════════════════
        FORMAT DE RÉPONSE
        ═══════════════════════════════════════════════════════════════════════
        4 blocs de code, dans cet ordre : html, css, json (schema), json (data).
        Aucun texte hors des blocs.

        ═══════════════════════════════════════════════════════════════════════
        SELF-CHECK LM
        ═══════════════════════════════════════════════════════════════════════
        □ .page utilise height: 297mm (pas min-height) ?
        □ .page n'a pas margin: 20mm auto ?
        □ .page n'a pas box-shadow ?
        □ .header margin-bottom ≤ 12mm ?
        □ nom/prénom ≤ 32pt ?
        □ recipient-info padding-top ≤ 6mm ?
        □ body font-size ≤ 10.5pt ?
        □ line-height corps ≤ 1.42 ?
        □ paragraph margin-bottom ≤ 9px ?
        □ schema paragraphs maxItems ≤ 4 ?
        □ schema paragraph maxLength ≤ 420 ?
        □ closing maxLength ≤ 140 ?
        □ Tout est en français ?

        Émets ta réponse maintenant.
    """)


# ═════════════════════════════════════════════════════════════════════════════
# PROMPT INFOS (métadonnées commerciales)
# ═════════════════════════════════════════════════════════════════════════════

def build_infos_prompt(
    analysis: PDFAnalysis,
    cv_files: dict,
    lm_analysis: Optional[PDFAnalysis] = None,
    lm_files: Optional[dict] = None,
) -> str:
    """Demande à l'IA les métadonnées commerciales du template (label, tags, etc.)."""
    pre_analysis = analysis.to_prompt_summary()
    html = (cv_files or {}).get("template.html", "")[:8000]
    css = (cv_files or {}).get("style.css", "")[:8000]
    schema = (cv_files or {}).get("schema.json", "")[:4000]

    lm_block = ""
    if lm_analysis is not None:
        lm_block = (
            "LETTRE DE MOTIVATION ASSOCIÉE : oui\n"
            f"Analyse LM :\n{lm_analysis.to_prompt_summary()}"
        )

    return dedent(f"""\
        Tu es un expert en classification de templates CV/lettres, branding et
        naming de produits digitaux.

        Mission : analyser le PDF + le HTML/CSS/schema générés, puis produire
        UNIQUEMENT un JSON valide pour infos.json.

        STYLE DE NAMING — FUN, COOL, MÉMORABLE :
        - label = vrai nom de template cool, vendable, qui donne envie de cliquer
        - français, anglais court, ou hybride si ça sonne bien
        - évoque énergie / ambiance / personnalité / promesse pro
        - JAMAIS une description technique du layout

        INTERDITS pour label :
        "Timeline Verticale", "CV Moderne", "Template Classique", "Deux Colonnes",
        "Minimaliste Bleu", "Sidebar Gauche", "CV Professionnel", "Modèle avec Photo"

        EXEMPLES de bons labels :
        "Rocket Line", "Neon Career", "Bold Move", "Pixel Pro", "Urban Flow",
        "Career Pop", "Fresh Start", "Nova Resume", "Vibe Pro", "Next Step",
        "Blue Spark", "Focus Club", "Studio Boss", "Level Up", "Glow Up Pro"

        Le `name` = slug exact du label : lowercase, sans accents/apostrophes,
        mots séparés par tirets, uniquement a-z, 0-9 et tirets.
        Ex : "Glow Up Pro" → "glow-up-pro"

        IMPORTANT :
        - Tu détermines : name, label, category, description, couleurs, fonts,
          layout, has_photo, photo_style, color_scheme, decorative_elements, tags.
        - Tu NE DÉCIDES PAS premium ni prix (toujours is_premium=false, price=null).
          Le script Python remplacera avec les choix humains.
        - Réponds UNIQUEMENT avec un objet JSON. Aucun markdown, aucun commentaire.

        Catégories autorisées :
        classic, modern, professional, creative, minimalist, executive, academic, ats, elegant

        Layouts autorisés :
        single-column, two-column-left-sidebar, two-column-right-sidebar,
        header-sidebar, timeline, card-based, editorial, compact

        Format JSON obligatoire :
        {{
          "name": "slug-exact-du-label",
          "label": "Nom fun et commercial",
          "category": "professional",
          "description": "Description commerciale précise",
          "primary_color": "#000000",
          "accent_color": "#ffffff",
          "font_family": "Inter",
          "body_font": "Arial",
          "layout": "two-column-left-sidebar",
          "layout_key": "two-column-left-sidebar",
          "has_photo": false,
          "photo_style": null,
          "color_scheme": "blanc-noir",
          "decorative_elements": ["..."],
          "tags": ["..."],
          "is_premium": false,
          "price": null,
          "is_active": true,
          "review_description": "Résumé court pour review interne",
          "paired_documents": {{ "cover_letter": null }}
        }}

        Si LM associée, remplace paired_documents.cover_letter par :
        {{
          "name": "slug-lm",
          "label": "Lettre de motivation — ...",
          "description": "Description cohérente avec le CV",
          "font_family": "...",
          "body_font": "...",
          "primary_color": "#...",
          "accent_color": "#...",
          "layout_key": "standard-letter"
        }}

        Analyse PDF CV :
        {pre_analysis}

        {lm_block}

        Extrait template.html :
        {html}

        Extrait style.css :
        {css}

        Extrait schema.json :
        {schema}
    """)


# ═════════════════════════════════════════════════════════════════════════════
# PROMPT VISUAL CRITIC — 2e PASSE GEMINI
# ═════════════════════════════════════════════════════════════════════════════

def build_visual_critic_prompt(
    analysis: PDFAnalysis,
    current_html: str,
    current_css: str,
) -> str:
    """
    Prompt envoyé à Gemini avec :
      - Le PDF original (en pièce jointe par le caller)
      - Le rendu HTML actuel (converti en image, en pièce jointe par le caller)
      - Le CSS courant
    Demande : identifier les écarts et émettre un HTML/CSS corrigé.
    """
    pre_analysis = analysis.to_prompt_summary()

    return dedent(f"""\
        Tu es un critique visuel expert. Tu vas voir DEUX images :
          1. Le PDF ORIGINAL (référence absolue, dernière image avant ce texte)
          2. Le RENDU HTML ACTUEL (au-dessus, à comparer)

        Wait — l'ordre exact dépend de ce que je t'ai envoyé. Compare quoi qu'il
        en soit le PDF original avec le rendu HTML actuel.

        ═══════════════════════════════════════════════════════════════════════
        MESURES DU PDF ORIGINAL (référence)
        ═══════════════════════════════════════════════════════════════════════
        {pre_analysis}

        ═══════════════════════════════════════════════════════════════════════
        TA MISSION
        ═══════════════════════════════════════════════════════════════════════
        Identifie les ÉCARTS visuels entre le rendu HTML et le PDF original.
        Concentre-toi sur :
          • Marges (top/bottom/left/right) — les bords doivent matcher au mm près
          • Largeur de la sidebar — elle doit faire EXACTEMENT la même proportion
          • Hauteur du header — pas plus, pas moins
          • Espacements entre sections — gaps verticaux
          • Tailles des titres et noms — proportionnelles à l'original
          • Couleurs des fonds et textes
          • Position des éléments (photo, contact, etc.)
          • Alignements (gauche/droite/centré) des blocs

        IGNORE :
          • Le contenu textuel exact (les fake data peuvent différer)
          • Les avatars / images génériques
          • Les variations de typographie mineures dues aux substitutions Google Fonts

        ═══════════════════════════════════════════════════════════════════════
        FORMAT DE RÉPONSE
        ═══════════════════════════════════════════════════════════════════════

        Réponds en 3 blocs :

        ```diagnosis
        - Écart 1 : [description précise + valeur attendue vs valeur actuelle]
        - Écart 2 : ...
        - Écart 3 : ...
        ```

        ```html
        <!-- HTML CORRIGÉ COMPLET — pas de patch, le fichier ENTIER -->
        ...
        ```

        ```css
        /* CSS CORRIGÉ COMPLET — pas de patch, le fichier ENTIER */
        ...
        ```

        S'il n'y a aucun écart significatif (rendu déjà fidèle), réponds
        littéralement :

        ```diagnosis
        OK — fidélité acceptable, aucune correction nécessaire.
        ```

        (et n'inclus alors PAS les blocs html/css)

        ═══════════════════════════════════════════════════════════════════════
        CSS COURANT (pour ta référence avant correction)
        ═══════════════════════════════════════════════════════════════════════
        ```css
        {current_css[:6000]}
        ```

        ═══════════════════════════════════════════════════════════════════════
        HTML COURANT (extrait, pour ta référence)
        ═══════════════════════════════════════════════════════════════════════
        ```html
        {current_html[:4000]}
        ```

        Émets maintenant ton diagnostic + le code corrigé si nécessaire.
    """)