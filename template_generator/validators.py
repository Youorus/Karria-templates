# tools/template_generator/validators.py
"""
Validators
==========
Garde-fous post-IA pour éviter de livrer un template cassé.

Niveaux :
  1. Structurel    — les 4 fichiers sont présents et parsables
  2. JSON          — schema/data sont JSON valides + champs minimaux
  3. CSS externe   — pas de <link rel="stylesheet"> autre que Google Fonts
  4. HTML ↔ Schema — le HTML utilise les bonnes variables
  5. Rendu Jinja2  — le template rend SANS ERREUR avec data.json
  6. LM A4         — densité, marges, tailles compatibles 1 page A4

Si une validation échoue : (False, [erreurs]) pour permettre un retry IA ciblé.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple


logger = logging.getLogger(__name__)


def _get_limit(schema_limits: Any, attr: str) -> Optional[int]:
    if schema_limits is None:
        return None
    value = getattr(schema_limits, attr, None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_load_file(files: Dict[str, str], key: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    raw = files.get(key, "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"{key} invalide : {e}"
    if not isinstance(parsed, dict):
        return None, f"{key} doit être un objet JSON"
    return parsed, None


# ─────────────────────────────────────────────────────────────────────────────
# 1. EXTRACTION DES BLOCS DE LA RÉPONSE IA
# ─────────────────────────────────────────────────────────────────────────────

def _parse_blocks(text: str) -> Tuple[Dict[str, str], List[str]]:
    """Extrait les blocs ```lang ... ``` du texte. Retourne (files_html_css, json_candidates)."""
    files: Dict[str, str] = {}
    pattern = r"```(\w+)\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)

    json_candidates: List[str] = []
    for lang, content in matches:
        lang = lang.lower().strip()
        content = content.strip()
        if lang in ("html", "htm"):
            if "html" not in files:
                files["html"] = content
        elif lang == "css":
            if "css" not in files:
                files["css"] = content
        elif lang in ("json", "jsonc"):
            json_candidates.append(content)
    return files, json_candidates


def _classify_jsons(json_candidates: List[str]) -> Tuple[str, str]:
    """Discrimine schema (a 'fields' + 'meta') et data (a 'fullName' top-level)."""
    schema_str, data_str = "", ""
    for js in json_candidates:
        try:
            data = json.loads(js)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue

        is_schema = (
            "fields" in data
            and isinstance(data.get("fields"), dict)
            and ("meta" in data or "version" in data)
        )
        if is_schema and not schema_str:
            schema_str = js
        elif not data_str:
            data_str = js
    return schema_str, data_str


def extract_files_from_response(text: str) -> Dict[str, str]:
    """Parse la réponse Gemini pour un CV et extrait les 4 fichiers."""
    blocks, jsons = _parse_blocks(text)
    schema, data = _classify_jsons(jsons)

    files: Dict[str, str] = {}
    if "html" in blocks:
        files["template.html"] = blocks["html"]
    if "css" in blocks:
        files["style.css"] = blocks["css"]
    if schema:
        files["schema.json"] = schema
    if data:
        files["data.json"] = data
    return files


def extract_lm_files_from_response(text: str) -> Dict[str, str]:
    """Parse la réponse Gemini pour une LM et extrait les 4 fichiers (préfixés lm_)."""
    blocks, jsons = _parse_blocks(text)
    schema, data = _classify_jsons(jsons)

    files: Dict[str, str] = {}
    if "html" in blocks:
        files["lm_template.html"] = blocks["html"]
    if "css" in blocks:
        files["lm_style.css"] = blocks["css"]
    if schema:
        files["lm_schema.json"] = schema
    if data:
        files["lm_data.json"] = data
    return files


def extract_fidelity_response(text: str) -> Tuple[str, str]:
    """Parse la réponse de la 2ᵉ passe vision-correction (HTML + CSS uniquement)."""
    blocks, _ = _parse_blocks(text)
    return blocks.get("html", ""), blocks.get("css", "")


# ─────────────────────────────────────────────────────────────────────────────
# 2. STRUCTURE
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_CV_FILES = ["template.html", "style.css", "schema.json", "data.json"]
REQUIRED_LM_FILES = ["lm_template.html", "lm_style.css", "lm_schema.json", "lm_data.json"]


def validate_structure(files: Dict[str, str], doc_type: str = "CV") -> Tuple[bool, List[str]]:
    required = REQUIRED_CV_FILES if doc_type == "CV" else REQUIRED_LM_FILES
    missing = [f for f in required if f not in files]
    if missing:
        return False, [f"Fichiers manquants : {missing}"]
    return True, []


# ─────────────────────────────────────────────────────────────────────────────
# 3. JSON
# ─────────────────────────────────────────────────────────────────────────────

def validate_json_files(files: Dict[str, str], doc_type: str = "CV") -> Tuple[bool, List[str]]:
    errors: List[str] = []
    schema_key = "schema.json" if doc_type == "CV" else "lm_schema.json"
    data_key = "data.json" if doc_type == "CV" else "lm_data.json"

    try:
        schema = json.loads(files[schema_key])
        if not isinstance(schema, dict):
            errors.append(f"{schema_key} doit être un objet JSON")
        elif "fields" not in schema:
            errors.append(f"{schema_key} doit contenir une clé 'fields'")
        elif not isinstance(schema["fields"], dict):
            errors.append(f"{schema_key}.fields doit être un objet")
    except (KeyError, json.JSONDecodeError) as e:
        errors.append(f"{schema_key} invalide : {e}")

    try:
        data = json.loads(files[data_key])
        if not isinstance(data, dict):
            errors.append(f"{data_key} doit être un objet JSON")
        else:
            required = ["fullName"] if doc_type == "CV" else ["fullName", "subject", "paragraphs"]
            for key in required:
                if not data.get(key):
                    errors.append(f"{data_key} : champ '{key}' manquant ou vide")
    except (KeyError, json.JSONDecodeError) as e:
        errors.append(f"{data_key} invalide : {e}")

    return len(errors) == 0, errors


# ─────────────────────────────────────────────────────────────────────────────
# 3B. LIMITES PHYSIQUES SCHEMA + DATA
# ─────────────────────────────────────────────────────────────────────────────

def _field_max_items(field: Dict[str, Any]) -> Optional[int]:
    value = field.get("maxItems")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _field_max_length(field: Dict[str, Any]) -> Optional[int]:
    value = field.get("maxLength")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_schema_physical_limits(
    files: Dict[str, str],
    doc_type: str = "CV",
    schema_limits: Any = None,
) -> Tuple[bool, List[str]]:
    """
    Vérifie que le schema généré par l'IA ne dépasse pas les limites physiques
    calculées depuis PDFAnalysis.
    """
    if doc_type != "CV" or schema_limits is None:
        return True, []

    schema_key = "schema.json"
    schema, err = _json_load_file(files, schema_key)
    if err:
        return False, [err]

    fields = schema.get("fields", {}) if isinstance(schema, dict) else {}
    if not isinstance(fields, dict):
        return False, ["schema.json.fields doit être un objet"]

    errors: List[str] = []

    def check_field_limit(field_name: str, attr: str, json_key: str) -> None:
        limit = _get_limit(schema_limits, attr)
        if limit is None:
            return
        field = fields.get(field_name, {})
        if not isinstance(field, dict):
            return
        actual = _field_max_items(field) if json_key == "maxItems" else _field_max_length(field)
        if actual is None:
            errors.append(f"schema.json : {field_name}.{json_key} doit être défini et ≤ {limit}")
        elif actual > limit:
            errors.append(f"schema.json : {field_name}.{json_key}={actual} dépasse la limite physique {limit}")

    check_field_limit("summary", "summary_max_length", "maxLength")
    check_field_limit("experiences", "experiences_max_items", "maxItems")
    check_field_limit("education", "education_max_items", "maxItems")
    check_field_limit("skills", "skills_max_items", "maxItems")
    check_field_limit("languages", "languages_max_items", "maxItems")
    check_field_limit("interests", "interests_max_items", "maxItems")
    check_field_limit("references", "references_max_items", "maxItems")

    desc_limit = _get_limit(schema_limits, "experience_description_max_length")
    experiences = fields.get("experiences", {})
    if desc_limit is not None and isinstance(experiences, dict):
        desc = (
            experiences.get("item", {})
            .get("fields", {})
            .get("description", {})
        )
        if isinstance(desc, dict):
            actual = _field_max_length(desc)
            if actual is None:
                errors.append(
                    "schema.json : experiences.item.fields.description.maxLength "
                    f"doit être défini et ≤ {desc_limit}"
                )
            elif actual > desc_limit:
                errors.append(
                    "schema.json : experiences.item.fields.description.maxLength="
                    f"{actual} dépasse la limite physique {desc_limit}"
                )

    return len(errors) == 0, errors


def _validate_value_against_field(
    value: Any,
    field: Dict[str, Any],
    path: str,
    errors: List[str],
) -> None:
    field_type = field.get("type")

    if value is None:
        return

    max_length = _field_max_length(field)
    if max_length is not None and isinstance(value, str) and len(value) > max_length:
        errors.append(f"data.json : {path} dépasse maxLength {max_length} ({len(value)} caractères)")

    if field_type == "array":
        if not isinstance(value, list):
            errors.append(f"data.json : {path} doit être une liste")
            return

        max_items = _field_max_items(field)
        if max_items is not None and len(value) > max_items:
            errors.append(f"data.json : {path} dépasse maxItems {max_items} ({len(value)} éléments)")

        item_schema = field.get("item", {})
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                _validate_value_against_field(item, item_schema, f"{path}[{idx}]", errors)
        return

    if field_type == "object":
        if not isinstance(value, dict):
            errors.append(f"data.json : {path} doit être un objet")
            return

        child_fields = field.get("fields", {})
        if isinstance(child_fields, dict):
            for child_name, child_schema in child_fields.items():
                if not isinstance(child_schema, dict):
                    continue
                child_required = bool(child_schema.get("required"))
                child_value = value.get(child_name)
                child_path = f"{path}.{child_name}"
                if child_required and (child_value is None or child_value == "" or child_value == []):
                    errors.append(f"data.json : {child_path} requis mais manquant ou vide")
                if child_name in value:
                    _validate_value_against_field(child_value, child_schema, child_path, errors)
        return


def validate_data_against_schema_recursive(
    files: Dict[str, str],
    doc_type: str = "CV",
) -> Tuple[bool, List[str]]:
    """
    Validation récursive data.json ↔ schema.json.
    Corrige le trou classique : maxLength/maxItems dans les objets imbriqués,
    notamment experiences[].description.
    """
    schema_key = "schema.json" if doc_type == "CV" else "lm_schema.json"
    data_key = "data.json" if doc_type == "CV" else "lm_data.json"

    schema, schema_err = _json_load_file(files, schema_key)
    if schema_err:
        return False, [schema_err]
    data, data_err = _json_load_file(files, data_key)
    if data_err:
        return False, [data_err]

    fields = schema.get("fields", {}) if isinstance(schema, dict) else {}
    if not isinstance(fields, dict):
        return False, [f"{schema_key}.fields doit être un objet"]

    errors: List[str] = []
    for field_name, field_schema in fields.items():
        if not isinstance(field_schema, dict):
            continue
        required = bool(field_schema.get("required"))
        value = data.get(field_name)
        if required and (value is None or value == "" or value == []):
            errors.append(f"{data_key} : {field_name} requis mais manquant ou vide")
        if field_name in data:
            _validate_value_against_field(value, field_schema, field_name, errors)

    return len(errors) == 0, errors


# ─────────────────────────────────────────────────────────────────────────────
# 4. COHÉRENCE HTML ↔ SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_CV_TOP_VARS: Set[str] = {
    "fullName", "jobTitle", "photo", "summary", "availability",
    "preferred_language", "_visible_sections",
    "contact", "labels",
    "experiences", "education", "educations",
    "skills", "languages", "interests",
    "projects", "awards", "achievements", "certifications",
    "references", "publications", "volunteering",
}

ALLOWED_LM_TOP_VARS: Set[str] = {
    "fullName", "jobTitle", "city", "date", "subject", "salutation", "closing",
    "preferred_language", "contact", "recipient", "labels", "paragraphs",
}

JINJA_INTERNAL_VARS: Set[str] = {
    "loop", "self", "super", "varargs", "kwargs",
    "true", "false", "none", "True", "False", "None",
    "and", "or", "not", "in", "is",
}

RUNTIME_INJECTED_VARS: Set[str] = {
    "_visible_sections", "preferred_language",
}


def extract_jinja_var_usage(html: str) -> Tuple[Set[str], Set[str]]:
    """Retourne (used_vars top-level, locally_declared_vars)."""
    locally_declared: Set[str] = set()

    for_pattern = r"{%-?\s*for\s+([^%]+?)\s+in\s+\w"
    for raw in re.findall(for_pattern, html):
        for var in re.split(r"[,\s]+", raw):
            var = var.strip()
            if var and var.isidentifier():
                locally_declared.add(var)

    locally_declared.update(re.findall(r"{%-?\s*set\s+(\w+)\s*=", html))
    locally_declared.update(re.findall(r"{%-?\s*with\s+(\w+)\s*=", html))
    locally_declared.update(re.findall(r"{%-?\s*macro\s+\w+\s*\(([^)]*)\)", html))

    used: Set[str] = set()
    # {{ var }} et {{ obj.attr }}
    for match in re.findall(r"{{-?\s*([\w.|()\[\]'\"\s]+?)\s*-?}}", html):
        # On prend l'identifiant top-level
        token = re.split(r"[\.\|\(\[\s]", match.strip(), maxsplit=1)[0]
        if token and token.isidentifier():
            used.add(token)
    # {% if var %}, {% for x in var %}
    for match in re.findall(r"{%-?\s*(?:if|elif)\s+([\w.\s\(\)\|=<>!,'\"]+?)\s*-?%}", html):
        token = re.split(r"[\.\|\(\[\s=<>!,]", match.strip(), maxsplit=1)[0]
        if token and token.isidentifier():
            used.add(token)
    for match in re.findall(r"{%-?\s*for\s+[^%]+?\s+in\s+([\w.]+)", html):
        token = match.split(".")[0]
        if token and token.isidentifier():
            used.add(token)

    return used, locally_declared


def validate_html_vs_schema(files: Dict[str, str], doc_type: str = "CV") -> Tuple[bool, List[str]]:
    html_key = "template.html" if doc_type == "CV" else "lm_template.html"
    schema_key = "schema.json" if doc_type == "CV" else "lm_schema.json"
    allowed = ALLOWED_CV_TOP_VARS if doc_type == "CV" else ALLOWED_LM_TOP_VARS

    html = files.get(html_key, "")
    if not html:
        return False, [f"{html_key} introuvable"]

    used, locally_declared = extract_jinja_var_usage(html)

    try:
        schema = json.loads(files.get(schema_key, "{}"))
    except json.JSONDecodeError:
        schema = {}
    schema_fields = set((schema.get("fields") or {}).keys())

    suspicious = used - locally_declared - allowed - JINJA_INTERNAL_VARS - RUNTIME_INJECTED_VARS
    suspicious -= schema_fields

    errors = []
    if suspicious:
        errors.append(
            f"{html_key} : variables Jinja2 inconnues (pas dans le schéma ni la liste autorisée) : "
            f"{sorted(suspicious)}"
        )

    return len(errors) == 0, errors


# ─────────────────────────────────────────────────────────────────────────────
# 5. RENDU JINJA2
# ─────────────────────────────────────────────────────────────────────────────

def validate_render(files: Dict[str, str], doc_type: str = "CV") -> Tuple[bool, List[str]]:
    """Vérifie que le template Jinja2 se rend SANS ERREUR avec data.json."""
    try:
        from jinja2 import Environment, BaseLoader, StrictUndefined, UndefinedError
        from jinja2 import TemplateSyntaxError
    except ImportError:
        logger.warning("Jinja2 manquant — validation rendu skippée")
        return True, []

    html_key = "template.html" if doc_type == "CV" else "lm_template.html"
    data_key = "data.json" if doc_type == "CV" else "lm_data.json"
    html = files.get(html_key, "")
    raw_data = files.get(data_key, "{}")

    try:
        data = json.loads(raw_data)
    except json.JSONDecodeError:
        return False, [f"{data_key} non parsable — render skippé"]

    env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
    # Filtre custom utilisé dans les templates
    env.filters["make_bars"] = lambda level: range(int(level or 0))

    try:
        env.from_string(html).render(**data)
    except TemplateSyntaxError as e:
        return False, [f"{html_key} : erreur de syntaxe Jinja2 — {e.message} (ligne {e.lineno})"]
    except UndefinedError as e:
        return False, [f"{html_key} : variable non définie pendant le rendu — {e}"]
    except Exception as e:
        return False, [f"{html_key} : erreur de rendu inattendue — {e}"]

    return True, []


# ─────────────────────────────────────────────────────────────────────────────
# 6. PAS DE <link> CSS EXTERNE
# ─────────────────────────────────────────────────────────────────────────────

def validate_no_external_css(files: Dict[str, str], doc_type: str = "CV") -> Tuple[bool, List[str]]:
    html_key = "template.html" if doc_type == "CV" else "lm_template.html"
    html = files.get(html_key, "")

    links = re.findall(r'<link[^>]+href="([^"]+)"[^>]*>', html, re.IGNORECASE)

    bad = []
    for link in links:
        if "fonts.googleapis.com" in link or "fonts.gstatic.com" in link:
            continue
        bad.append(link)

    if bad:
        return False, [f"{html_key} : <link> CSS externes détectés : {bad}"]
    if "<style>" not in html and "<style " not in html:
        return False, [f"{html_key} : aucun <style> trouvé — le CSS doit être inline"]
    return True, []


# ─────────────────────────────────────────────────────────────────────────────
# 7. DENSITÉ / A4 STRICT — LM
# ─────────────────────────────────────────────────────────────────────────────

def validate_lm_schema_density(files: Dict[str, str], doc_type: str = "CV") -> Tuple[bool, List[str]]:
    if doc_type != "LM":
        return True, []

    errors: List[str] = []
    raw = files.get("lm_schema.json", "")
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as e:
        return False, [f"lm_schema.json invalide : {e}"]

    fields = schema.get("fields", {}) if isinstance(schema, dict) else {}

    paragraphs = fields.get("paragraphs", {})
    item = paragraphs.get("item", {}) if isinstance(paragraphs, dict) else {}

    max_items = paragraphs.get("maxItems") if isinstance(paragraphs, dict) else None
    if max_items is None:
        errors.append("lm_schema.json : paragraphs.maxItems doit être défini et ≤ 4")
    else:
        try:
            if int(max_items) > 4:
                errors.append("lm_schema.json : paragraphs.maxItems doit être ≤ 4")
        except (TypeError, ValueError):
            errors.append("lm_schema.json : paragraphs.maxItems doit être un entier")

    max_length = item.get("maxLength") if isinstance(item, dict) else None
    if max_length is None:
        errors.append("lm_schema.json : paragraphs.item.maxLength doit être défini et ≤ 420")
    else:
        try:
            if int(max_length) > 420:
                errors.append("lm_schema.json : paragraphs.item.maxLength doit être ≤ 420")
        except (TypeError, ValueError):
            errors.append("lm_schema.json : paragraphs.item.maxLength doit être un entier")

    closing = fields.get("closing", {})
    closing_max = closing.get("maxLength") if isinstance(closing, dict) else None
    if closing_max is None:
        errors.append("lm_schema.json : closing.maxLength doit être défini et ≤ 140")
    else:
        try:
            if int(closing_max) > 140:
                errors.append("lm_schema.json : closing.maxLength doit être ≤ 140")
        except (TypeError, ValueError):
            errors.append("lm_schema.json : closing.maxLength doit être un entier")

    subject = fields.get("subject", {})
    subject_max = subject.get("maxLength") if isinstance(subject, dict) else None
    if subject_max is not None:
        try:
            if int(subject_max) > 180:
                errors.append("lm_schema.json : subject.maxLength doit être ≤ 180")
        except (TypeError, ValueError):
            errors.append("lm_schema.json : subject.maxLength doit être un entier")

    return len(errors) == 0, errors


def validate_lm_data_density(files: Dict[str, str], doc_type: str = "CV") -> Tuple[bool, List[str]]:
    if doc_type != "LM":
        return True, []

    errors: List[str] = []
    raw = files.get("lm_data.json", "")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return False, [f"lm_data.json invalide : {e}"]

    paragraphs = data.get("paragraphs", []) if isinstance(data, dict) else []
    if not isinstance(paragraphs, list):
        errors.append("lm_data.json : paragraphs doit être une liste")
    else:
        if len(paragraphs) > 4:
            errors.append("lm_data.json : maximum 4 paragraphes")
        for idx, para in enumerate(paragraphs, start=1):
            if len(str(para)) > 520:
                errors.append(f"lm_data.json : paragraphe {idx} trop long (> 520 caractères)")

    closing = str(data.get("closing", "")) if isinstance(data, dict) else ""
    if len(closing) > 160:
        errors.append("lm_data.json : closing trop long (> 160 caractères)")

    return len(errors) == 0, errors


def validate_lm_css_density(files: Dict[str, str], doc_type: str = "CV") -> Tuple[bool, List[str]]:
    if doc_type != "LM":
        return True, []

    css = files.get("lm_style.css", "")
    html = files.get("lm_template.html", "")
    combined = css + "\n" + html
    normalized = re.sub(r"\s+", " ", combined)

    errors: List[str] = []

    if not re.search(r"\.page\s*\{[^}]*height\s*:\s*297mm", combined, flags=re.I | re.S):
        errors.append("LM CSS : .page doit avoir height: 297mm")
    if re.search(r"\.page\s*\{[^}]*min-height\s*:\s*297mm", combined, flags=re.I | re.S):
        errors.append("LM CSS : .page ne doit pas utiliser min-height: 297mm")
    if re.search(r"\.page\s*\{[^}]*margin\s*:\s*20mm\s+auto", combined, flags=re.I | re.S):
        errors.append("LM CSS : .page ne doit pas utiliser margin: 20mm auto")
    if re.search(r"\.page\s*\{[^}]*box-shadow\s*:", combined, flags=re.I | re.S):
        errors.append("LM CSS : .page ne doit pas avoir box-shadow")
    if "overflow: hidden" not in normalized:
        errors.append("LM CSS : overflow: hidden obligatoire")

    if re.search(r"font-size\s*:\s*(?:3[7-9]|[4-9][0-9])pt", combined, flags=re.I):
        errors.append("LM CSS : font-size > 36pt détecté")
    if re.search(r"font-size\s*:\s*51pt", combined, flags=re.I):
        errors.append("LM CSS : nom en 51pt détecté, trop grand pour A4")

    if re.search(r"\.header\s*\{[^}]*margin-bottom\s*:\s*(?:1[3-9]|[2-9][0-9])mm", combined, flags=re.I | re.S):
        errors.append("LM CSS : .header margin-bottom doit être ≤ 12mm")
    if re.search(r"\.recipient-info\s*\{[^}]*padding-top\s*:\s*(?:[7-9]|[1-9][0-9])mm", combined, flags=re.I | re.S):
        errors.append("LM CSS : .recipient-info padding-top doit être ≤ 6mm")
    if re.search(r"line-height\s*:\s*1\.(?:5|6|7|8|9)", combined, flags=re.I):
        errors.append("LM CSS : line-height > 1.42 détecté")
    if re.search(r"\.paragraph\s*\{[^}]*margin-bottom\s*:\s*(?:1[0-9]|[2-9][0-9])px", combined, flags=re.I | re.S):
        errors.append("LM CSS : .paragraph margin-bottom doit être ≤ 9px")

    return len(errors) == 0, errors


# ─────────────────────────────────────────────────────────────────────────────
# 8. ORCHESTRATEUR
# ─────────────────────────────────────────────────────────────────────────────

def validate_all(
    files: Dict[str, str],
    doc_type: str = "CV",
    schema_limits: Any = None,
) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    checks = [
        ("Structure",              validate_structure),
        ("JSON",                   validate_json_files),
        ("Schema limites physiques", validate_schema_physical_limits),
        ("Data ↔ Schema récursif", validate_data_against_schema_recursive),
        ("CSS externe",            validate_no_external_css),
        ("HTML ↔ Schema",          validate_html_vs_schema),
        ("Rendu Jinja2",           validate_render),
        ("LM CSS densité",         validate_lm_css_density),
        ("LM schema densité",      validate_lm_schema_density),
        ("LM data densité",        validate_lm_data_density),
    ]
    for name, fn in checks:
        if fn is validate_schema_physical_limits:
            ok, errs = fn(files, doc_type, schema_limits=schema_limits)
        else:
            ok, errs = fn(files, doc_type)
        if not ok:
            for e in errs:
                errors.append(f"[{name}] {e}")
    return len(errors) == 0, errors