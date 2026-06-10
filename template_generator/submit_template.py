#!/usr/bin/env python3
"""
submit_template.py v3 — Soumission de templates Karria.

Utilise directement KarriaAPIClient (modules/karria_api/client.py).
Lit la configuration depuis config.py (source unique de vérité).

Modes :
  • standalone   : python -m template_generator.submit_template ./outputs/blue-spark
  • batch        : python -m template_generator.submit_template --batch
  • CRUD         : --list / --get ID / --update ID / --delete ID
  • dry-run      : ajoute --dry-run pour tester sans envoyer

Ce module est appelé par pipeline.py après validation du preview.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from template_generator.client import KarriaAPIClient

# ── Config (source unique de vérité) ────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ═════════════════════════════════════════════════════════════════════════════

REQUIRED_CV_FILES = ("template.html", "style.css", "preview.pdf", "infos.json")
REQUIRED_LM_FILES = ("lm_template.html", "lm_style.css", "lm_preview.pdf")





# ═════════════════════════════════════════════════════════════════════════════
# DATACLASSES
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class SubmitJob:
    folder:        Path
    with_lm:       bool = False
    label_preview: str  = ""


@dataclass
class SubmitResult:
    folder:    Path
    success:   bool
    cv_id:     Optional[int]   = None
    lm_id:     Optional[int]   = None
    error:     Optional[str]   = None
    elapsed_s: float           = 0.0


# ═════════════════════════════════════════════════════════════════════════════
# LECTURE DES FICHIERS
# ═════════════════════════════════════════════════════════════════════════════

def _read_bytes(path: Path, label: str, *, required: bool) -> Optional[bytes]:
    if path.exists():
        data = path.read_bytes()
        logger.info("  ✅ %-25s (%s bytes)", label, f"{len(data):,}")
        return data
    if required:
        logger.error("  ❌ %-25s MANQUANT : %s", label, path)
        raise FileNotFoundError(f"Fichier obligatoire introuvable : {path}")
    logger.info("  ⬜ %-25s absent (optionnel)", label)
    return None


def load_template_files(folder: Path, *, with_lm: bool) -> Dict[str, Optional[bytes]]:
    print(f"\n📂 Lecture : {folder.resolve()}")
    files: Dict[str, Optional[bytes]] = {
        "cv_html":        _read_bytes(folder / "template.html", "template.html", required=True),
        "cv_css":         _read_bytes(folder / "style.css",     "style.css",     required=True),
        "cv_preview_pdf": _read_bytes(folder / "preview.pdf",   "preview.pdf",   required=True),
        "cv_schema":      _read_bytes(folder / "schema.json",   "schema.json",   required=False),
        "cv_data":        _read_bytes(folder / "data.json",     "data.json",     required=False),
        "cv_infos":       _read_bytes(folder / "infos.json",    "infos.json",    required=True),
    }
    if with_lm:
        lm_dir = folder / "lm"
        print(f"\n📂 Lecture LM : {lm_dir.resolve()}")
        files.update({
            "lm_html":        _read_bytes(lm_dir / "lm_template.html", "lm_template.html", required=True),
            "lm_css":         _read_bytes(lm_dir / "lm_style.css",     "lm_style.css",     required=True),
            "lm_preview_pdf": _read_bytes(lm_dir / "lm_preview.pdf",   "lm_preview.pdf",   required=True),
            "lm_schema":      _read_bytes(lm_dir / "lm_schema.json",   "lm_schema.json",   required=False),
            "lm_data":        _read_bytes(lm_dir / "lm_data.json",     "lm_data.json",     required=False),
        })
    return files


# ═════════════════════════════════════════════════════════════════════════════
# LECTURE infos.json → MÉTADONNÉES
# ═════════════════════════════════════════════════════════════════════════════

def load_metadata_from_infos(folder: Path) -> Dict[str, Any]:
    """Charge tous les champs depuis infos.json (aligné MachineFullSubmitMeta)."""
    infos_path = folder / "infos.json"
    if not infos_path.exists():
        raise FileNotFoundError(f"infos.json introuvable dans {folder}")

    raw = json.loads(infos_path.read_text(encoding="utf-8"))

    # Bloc CV : sous "cv" (v3) ou à la racine (compat v2)
    cv = raw.get("cv") if isinstance(raw.get("cv"), dict) else raw

    # Bloc LM
    paired = raw.get("paired_documents") or cv.get("paired_documents") or {}
    lm     = paired.get("cover_letter") or raw.get("cover_letter") or {}

    def _g(d: dict, *keys, default=None):
        for k in keys:
            v = d.get(k)
            if v is not None:
                return v
        return default

    return {
        # CV
        "cv_name":               _g(cv, "name",               default=""),
        "cv_label":              _g(cv, "label",              default=""),
        "cv_category":           _g(cv, "category",           default="modern"),
        "cv_description":        _g(cv, "description"),
        "cv_primary_color":      _g(cv, "primary_color",      default="#1A73E8"),
        "cv_font_family":        _g(cv, "font_family",        default="Inter"),
        "cv_is_premium":         bool(_g(cv, "is_premium",    default=False)),
        "cv_price":              _g(cv, "price"),
        "cv_is_active":          bool(_g(cv, "is_active",     default=True)),
        "cv_has_photo":          bool(_g(cv, "has_photo",     default=False)),
        "cv_tags":               _g(cv, "tags",               default=None),
        "cv_review_description": _g(cv, "review_description", default=""),
        "cv_layout_key":         _g(cv, "layout_key", "layout", default="two-column-left-sidebar"),
        # LM
        "lm_name":          _g(lm, "name"),
        "lm_label":         _g(lm, "label"),
        "lm_category":      _g(lm, "category"),
        "lm_description":   _g(lm, "description"),
        "lm_primary_color": _g(lm, "primary_color"),
        "lm_font_family":   _g(lm, "font_family"),
        "lm_layout_key":    _g(lm, "layout_key", default="standard-letter"),
    }


# ═════════════════════════════════════════════════════════════════════════════
# VALIDATION PRÉ-ENVOI
# ═════════════════════════════════════════════════════════════════════════════

def validate_payload(meta: Dict[str, Any], with_lm: bool) -> List[str]:
    errors: List[str] = []

    if not meta.get("cv_name"):
        errors.append("CV: 'name' obligatoire")
    if not meta.get("cv_label"):
        errors.append("CV: 'label' obligatoire")

    is_premium = bool(meta.get("cv_is_premium"))
    price      = meta.get("cv_price")

    if is_premium and price is None:
        errors.append("CV: is_premium=True nécessite un 'price' non-null")
    if is_premium and price is not None:
        try:
            float(price)
        except (TypeError, ValueError):
            errors.append(f"CV: price='{price}' n'est pas un nombre")
    if not is_premium and price not in (None, "", 0, "0"):
        errors.append(
            f"CV: is_premium=False mais price={price} défini — "
            "soit passe is_premium=True, soit retire le prix"
        )

    tags = meta.get("cv_tags")
    if tags is not None and not isinstance(tags, list):
        errors.append(f"CV: 'tags' doit être une liste, reçu {type(tags).__name__}")

    if with_lm:
        if not meta.get("lm_name"):
            errors.append("LM: 'lm_name' obligatoire si with_lm=True")
        if not meta.get("lm_label"):
            errors.append("LM: 'lm_label' obligatoire si with_lm=True")

    return errors


# ═════════════════════════════════════════════════════════════════════════════
# OVERRIDES CLI 3-ÉTATS
# ═════════════════════════════════════════════════════════════════════════════

def _three_state_bool(val: Optional[str]) -> Optional[bool]:
    if val is None:
        return None
    v = str(val).strip().lower()
    if v in {"true", "yes", "y", "1", "oui"}:
        return True
    if v in {"false", "no", "n", "0", "non"}:
        return False
    raise ValueError(f"Valeur booléenne invalide : {val!r}")


def apply_cli_overrides(meta: Dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "name",          None): meta["cv_name"]          = args.name
    if getattr(args, "label",         None): meta["cv_label"]         = args.label
    if getattr(args, "category",      None): meta["cv_category"]      = args.category
    if getattr(args, "description",   None): meta["cv_description"]   = args.description
    if getattr(args, "primary_color", None): meta["cv_primary_color"] = args.primary_color
    if getattr(args, "font_family",   None): meta["cv_font_family"]   = args.font_family
    if getattr(args, "layout_key",    None): meta["cv_layout_key"]    = args.layout_key

    prem = _three_state_bool(getattr(args, "is_premium", None))
    if prem is not None:
        meta["cv_is_premium"] = prem

    photo = _three_state_bool(getattr(args, "has_photo", None))
    if photo is not None:
        meta["cv_has_photo"] = photo

    active = _three_state_bool(getattr(args, "is_active", None))
    if active is not None:
        meta["cv_is_active"] = active

    if getattr(args, "price", None) is not None:
        meta["cv_price"] = args.price

    raw_tags = getattr(args, "tags", None)
    if raw_tags:
        try:
            meta["cv_tags"] = (
                json.loads(raw_tags) if raw_tags.startswith("[")
                else [t.strip() for t in raw_tags.split(",") if t.strip()]
            )
        except json.JSONDecodeError:
            raise ValueError(f"--tags JSON invalide : {raw_tags}")

    if getattr(args, "lm_name",  None): meta["lm_name"]  = args.lm_name
    if getattr(args, "lm_label", None): meta["lm_label"] = args.lm_label

    # Cohérence : premium=False → price=None
    if not meta.get("cv_is_premium"):
        meta["cv_price"] = None


# ═════════════════════════════════════════════════════════════════════════════
# UI : AFFICHAGE
# ═════════════════════════════════════════════════════════════════════════════

def _print_cv(cv: dict) -> None:
    print(f"\n  🆔 id            : {cv.get('id')}")
    print(f"  📄 name          : {cv.get('name')}")
    print(f"  🏷️  label         : {cv.get('label')}")
    print(f"  📂 category      : {cv.get('category')}")
    print(f"  💎 premium       : {'Oui — ' + str(cv.get('price')) + ' €' if cv.get('is_premium') else 'Non'}")
    print(f"  ✅ actif         : {'Oui' if cv.get('is_active') else 'Non'}")
    print(f"  📷 photo         : {'Oui' if cv.get('has_photo') else 'Non'}")
    print(f"  🏷️  tags          : {cv.get('tags')}")
    print(f"  👁️  views         : {cv.get('views_count', 0)}")
    cover_letters = cv.get("cover_letters", [])
    if cover_letters:
        print(f"\n  ✉️  Lettres ({len(cover_letters)}) :")
        for cl in cover_letters:
            print(f"    • [{cl.get('id')}] {cl.get('name')} — {cl.get('label')}")


def _print_lm(lm: dict) -> None:
    print(f"\n  🆔 id            : {lm.get('id')}")
    print(f"  ✉️  name          : {lm.get('name')}")
    print(f"  🏷️  label         : {lm.get('label')}")


def _badge(folder: Path) -> str:
    badges = []
    try:
        infos = json.loads((folder / "infos.json").read_text(encoding="utf-8"))
        cv = infos.get("cv") if isinstance(infos.get("cv"), dict) else infos
        if cv.get("is_premium"):  badges.append("💎")
        if cv.get("has_photo"):   badges.append("📷")
        if not cv.get("is_active", True): badges.append("⏸️")
    except Exception:
        pass
    if _has_lm(folder):
        badges.append("✉️")
    return " ".join(badges) or " "


def _template_label(folder: Path) -> str:
    try:
        infos = json.loads((folder / "infos.json").read_text(encoding="utf-8"))
        cv    = infos.get("cv") if isinstance(infos.get("cv"), dict) else infos
        label = cv.get("label") or infos.get("label")
        name  = cv.get("name")  or infos.get("name") or folder.name
        return f"{label} ({name})" if label else name
    except Exception:
        return folder.name


def _is_template_folder(folder: Path) -> bool:
    return folder.is_dir() and all((folder / f).exists() for f in REQUIRED_CV_FILES)


def _has_lm(folder: Path) -> bool:
    lm_dir = folder / "lm"
    return lm_dir.is_dir() and all((lm_dir / f).exists() for f in REQUIRED_LM_FILES)


# ═════════════════════════════════════════════════════════════════════════════
# RÉSOLUTION DE LA RACINE TEMPLATES
# ═════════════════════════════════════════════════════════════════════════════

def _resolve_root(cli_root: Optional[str] = None) -> Path:
    candidates = []
    if cli_root:
        candidates.append(Path(cli_root).expanduser())

    candidates.extend([
        settings.TEMPLATES_ROOT.expanduser(),
        settings.OUTPUT_DIR.expanduser(),
        Path.cwd() / "outputs",
        Path.cwd() / "templates",
        Path.cwd(),
    ])

    for c in candidates:
        c = c.expanduser().resolve()
        if not c.is_dir():
            continue
        if any(_is_template_folder(p) for p in c.iterdir() if p.is_dir()):
            return c
        if _is_template_folder(c):
            return c.parent
    return (Path(cli_root).expanduser() if cli_root else Path.cwd()).resolve()


# ═════════════════════════════════════════════════════════════════════════════
# NAVIGATION INTERACTIVE
# ═════════════════════════════════════════════════════════════════════════════

def _choose_template_folder(root: Path) -> Optional[Path]:
    current = root.resolve()

    while True:
        if not current.exists():
            current = root

        dirs = sorted(
            [p for p in current.iterdir() if p.is_dir() and not p.name.startswith(".")],
            key=lambda p: p.name.lower(),
        )

        print(f"\n📂 {current}")
        print(f"🏠 Racine : {root}\n")

        entries: List[Path] = []
        for d in dirs:
            entries.append(d)
            if _is_template_folder(d):
                print(f"  [{len(entries):2d}] ✅ {_template_label(d):<40s} {_badge(d)}")
            else:
                print(f"  [{len(entries):2d}] 📁 {d.name}/")

        if not entries:
            print("  (aucun sous-dossier)")

        print("\nCommandes : [n] sélectionner | [..] parent | [/] racine | [done] terminer | [q] quitter")
        choice = input("> ").strip()
        low    = choice.lower()

        if low in {"q", "quit", "exit"}: sys.exit("Annulé.")
        if low in {"done", "fin", "go"}: return None
        if choice == "/":  current = root; continue
        if choice == "..": current = current.parent; continue

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(entries):
                sel = entries[idx]
                if _is_template_folder(sel):
                    return sel.resolve()
                current = sel.resolve(); continue

        if choice:
            cand = Path(choice).expanduser()
            if not cand.is_absolute():
                cand = current / choice
            cand = cand.resolve()
            if _is_template_folder(cand):
                return cand
            if cand.is_dir():
                current = cand; continue

        print("❌ Choix invalide.")


# ═════════════════════════════════════════════════════════════════════════════
# ACTION SUBMIT
# ═════════════════════════════════════════════════════════════════════════════

async def action_submit(
    args: argparse.Namespace,
) -> SubmitResult:
    """Soumet un seul template. Utilisé en standalone ou par la queue batch."""


    folder  = Path(args.folder).resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f"Dossier introuvable : {folder}")

    with_lm = bool(getattr(args, "with_lm", False)) and _has_lm(folder)

    # 1. Fichiers
    files = load_template_files(folder, with_lm=with_lm)

    # 2. Métadonnées depuis infos.json
    meta = load_metadata_from_infos(folder)

    # 3. Overrides CLI optionnels
    apply_cli_overrides(meta, args)

    # 4. Validation
    errs = validate_payload(meta, with_lm=with_lm)
    if errs:
        for e in errs:
            logger.error("  ❌ %s", e)
        raise ValueError(f"Payload invalide pour {folder.name}")

    # 5. Récap
    print(f"\n🚀 Soumission '{meta['cv_name']}'")
    print(f"   Label     : {meta['cv_label']}")
    print(f"   Catégorie : {meta['cv_category']}")
    print(f"   Premium   : {'💎 ' + str(meta['cv_price']) + ' €' if meta['cv_is_premium'] else 'Non'}")
    print(f"   Photo     : {'Oui' if meta['cv_has_photo'] else 'Non'}")
    print(f"   Actif     : {'Oui' if meta['cv_is_active'] else 'Non'}")
    print(f"   Avec LM   : {'Oui' if with_lm else 'Non'}")

    if getattr(args, "dry_run", False):
        print("\n🧪 DRY-RUN — aucune requête envoyée.")
        return SubmitResult(folder=folder, success=True)

    # 6. Envoi via KarriaAPIClient
    t0 = time.perf_counter()

    async with KarriaAPIClient() as client:
        result = await client.submit_full_template(
            # CV
            cv_name=meta["cv_name"],
            cv_label=meta["cv_label"],
            cv_category=meta["cv_category"],
            cv_description=meta.get("cv_description"),
            cv_primary_color=meta["cv_primary_color"],
            cv_font_family=meta["cv_font_family"],
            cv_is_premium=meta["cv_is_premium"],
            cv_price=meta["cv_price"],
            cv_is_active=meta["cv_is_active"],
            cv_has_photo=meta["cv_has_photo"],
            cv_tags=meta.get("cv_tags"),
            cv_review_description=meta.get("cv_review_description"),
            cv_layout_key=meta["cv_layout_key"],
            cv_html=files["cv_html"],
            cv_css=files["cv_css"],
            cv_preview_pdf=files["cv_preview_pdf"],
            cv_schema=files.get("cv_schema"),
            cv_data=files.get("cv_data"),
            cv_infos=files.get("cv_infos"),
            # LM
            with_cover_letter=with_lm,
            lm_name=meta.get("lm_name"),
            lm_label=meta.get("lm_label"),
            lm_category=meta.get("lm_category", "classic"),
            lm_description=meta.get("lm_description"),
            lm_primary_color=meta.get("lm_primary_color"),
            lm_font_family=meta.get("lm_font_family"),
            lm_layout_key=meta.get("lm_layout_key", "standard-letter"),
            lm_html=files.get("lm_html"),
            lm_css=files.get("lm_css"),
            lm_preview_pdf=files.get("lm_preview_pdf"),
            lm_schema=files.get("lm_schema"),
            lm_data=files.get("lm_data"),
        )

    elapsed = round(time.perf_counter() - t0, 2)
    cv      = result.get("cv_template", {})
    lm      = result.get("cover_letter")

    print(f"\n🎉 Template créé en {elapsed}s")
    _print_cv(cv)
    if lm:
        print("\n✉️  Lettre de motivation :")
        _print_lm(lm)

    return SubmitResult(
        folder=folder, success=True,
        cv_id=cv.get("id"),
        lm_id=lm.get("id") if lm else None,
        elapsed_s=elapsed,
    )


# ═════════════════════════════════════════════════════════════════════════════
# CRUD ACTIONS
# ═════════════════════════════════════════════════════════════════════════════

async def action_list(args: argparse.Namespace) -> None:

    async with KarriaAPIClient() as client:
        templates = await client.list_cv_templates(active_only=not getattr(args, "all", False))
    print(f"\n📚 {len(templates)} template(s) :")
    for t in templates:
        lm_count = len(t.get("cover_letters", []))
        status  = "✅" if t.get("is_active") else "❌"
        premium = "💎" if t.get("is_premium") else "  "
        photo   = "📷" if t.get("has_photo") else "  "
        print(f"  {status} {premium} {photo} [{t['id']:3d}] {t['name']:<45s}  LM:{lm_count}")


async def action_get(args: argparse.Namespace) -> None:

    async with KarriaAPIClient() as client:
        cv = await client.get_cv_template(args.get)
    _print_cv(cv)


async def action_update(args: argparse.Namespace) -> None:

    payload: Dict[str, Any] = {}
    if args.label:       payload["label"]       = args.label
    if args.description: payload["description"] = args.description
    is_active = _three_state_bool(getattr(args, "is_active", None))
    if is_active is not None:
        payload["is_active"] = is_active
    is_premium = _three_state_bool(getattr(args, "is_premium", None))
    if is_premium is not None:
        payload["is_premium"] = is_premium
        if not is_premium:
            payload["price"] = None
    if args.price is not None:
        payload["price"] = float(args.price)
    raw_tags = getattr(args, "tags", None)
    if raw_tags:
        payload["tags"] = (
            json.loads(raw_tags) if raw_tags.startswith("[")
            else [t.strip() for t in raw_tags.split(",") if t.strip()]
        )
    if not payload:
        print("⚠️  Aucun champ à mettre à jour."); return
    async with KarriaAPIClient() as client:
        cv = await client.update_cv_template(args.update, payload)
    _print_cv(cv)


async def action_delete(args: argparse.Namespace) -> None:

    print(f"\n⚠️  Suppression du template #{args.delete} (et ses LM en cascade)…")
    if input("Confirmer ? [oui/non] : ").strip().lower() not in {"oui", "o", "yes", "y"}:
        print("Annulé."); return
    async with KarriaAPIClient() as client:
        await client.delete_cv_template(args.delete)
    print(f"✅ Template #{args.delete} supprimé.")


# ═════════════════════════════════════════════════════════════════════════════
# BATCH INTERACTIF
# ═════════════════════════════════════════════════════════════════════════════

async def action_batch_submit(args: argparse.Namespace) -> None:
    root = _resolve_root(getattr(args, "templates_root", None))
    if not root.exists():
        logger.error("❌ Racine templates introuvable : %s", root); sys.exit(1)

    print(f"\n🚀 Karria — Soumission interactive\nRacine : {root}\n")
    queue: List[SubmitJob] = []

    while True:
        folder = _choose_template_folder(root)
        if folder is None:
            break
        include_lm = False
        if _has_lm(folder):
            include_lm = input("\nInclure la LM détectée ? [Y/n] ").strip().lower() not in {"n", "non", "no"}
        queue.append(SubmitJob(folder=folder, with_lm=include_lm, label_preview=_template_label(folder)))
        _print_queue(queue)
        if input("\nAjouter un autre template ? [Y/n] ").strip().lower() in {"n", "non", "no"}:
            break

    if not queue:
        print("\nAucun template sélectionné."); return

    # Validation pré-batch
    print("\n🔍 Validation pré-batch…")
    bad: List[tuple] = []
    for job in queue:
        try:
            meta = load_metadata_from_infos(job.folder)
            errs = validate_payload(meta, with_lm=job.with_lm)
            if errs: bad.append((job.folder, errs))
        except Exception as e:
            bad.append((job.folder, [str(e)]))
    if bad:
        print("\n❌ Erreurs :")
        for folder, errs in bad:
            print(f"\n  📂 {folder.name}")
            for e in errs: print(f"     • {e}")
        if input("\nContinuer quand même ? [y/N] ").strip().lower() not in {"y", "oui", "yes"}:
            print("Annulé."); return

    # Soumission
    print(f"\n🚀 Démarrage : {len(queue)} template(s)")
    results: List[SubmitResult] = []
    for i, job in enumerate(queue, 1):
        print(f"\n▶️  [{i}/{len(queue)}] {job.label_preview}")
        try:
            sub_args         = argparse.Namespace(**vars(args))
            sub_args.folder  = str(job.folder)
            sub_args.with_lm = job.with_lm
            # Reset des overrides en mode queue (on lit infos.json)
            for attr in ("name", "label", "category", "description",
                         "primary_color", "font_family", "layout_key",
                         "is_premium", "has_photo", "is_active", "price",
                         "tags", "lm_name", "lm_label"):
                setattr(sub_args, attr, None)
            result = await action_submit(sub_args)
            results.append(result)
        except Exception as e:
            logger.exception("❌ Échec : %s — %s", job.folder.name, e)
            results.append(SubmitResult(folder=job.folder, success=False, error=str(e)))

    # Rapport
    ok, failed = sum(1 for r in results if r.success), sum(1 for r in results if not r.success)
    print(f"\n{'═' * 68}")
    print(f"📦 Résumé batch — ✅ {ok}  ❌ {failed}")
    for r in results:
        if not r.success:
            print(f"  • {r.folder.name} → {r.error}")

    # CSV optionnel
    csv_path = getattr(args, "report_csv", None)
    if csv_path:
        out = Path(csv_path).expanduser().resolve()
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["folder", "success", "cv_id", "lm_id", "elapsed_s", "error"])
            for r in results:
                writer.writerow([r.folder.name, r.success, r.cv_id or "", r.lm_id or "", r.elapsed_s, r.error or ""])
        print(f"\n📊 Rapport CSV : {out}")


def _print_queue(queue: List[SubmitJob]) -> None:
    print(f"\n🧺 Queue : {len(queue)} template(s)")
    for i, job in enumerate(queue, 1):
        lm = "+ LM" if job.with_lm else "    "
        print(f"  [{i:2d}] {lm} {job.label_preview}")


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Gestion des templates CV/LM via l'API Karria.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("folder",     nargs="?")
    mode.add_argument("--list",     action="store_true")
    mode.add_argument("--get",      type=int, metavar="ID")
    mode.add_argument("--update",   type=int, metavar="ID")
    mode.add_argument("--delete",   type=int, metavar="ID")
    mode.add_argument("--batch",    action="store_true")

    sub = p.add_argument_group("Soumission")
    sub.add_argument("--name"); sub.add_argument("--label"); sub.add_argument("--category")
    sub.add_argument("--description"); sub.add_argument("--primary-color", dest="primary_color")
    sub.add_argument("--font-family",  dest="font_family"); sub.add_argument("--layout-key", dest="layout_key")
    sub.add_argument("--tags")
    sub.add_argument("--has-photo",  dest="has_photo",  help="true/false")
    sub.add_argument("--is-premium", dest="is_premium", help="true/false")
    sub.add_argument("--is-active",  dest="is_active",  help="true/false")
    sub.add_argument("--price",      type=float)
    sub.add_argument("--dry-run",    dest="dry_run", action="store_true")
    sub.add_argument("--templates-root", dest="templates_root")
    sub.add_argument("--report-csv",     dest="report_csv")

    lm = p.add_argument_group("LM")
    lm.add_argument("--with-lm",   dest="with_lm", action="store_true", default=False)
    lm.add_argument("--lm-name",   dest="lm_name"); lm.add_argument("--lm-label", dest="lm_label")

    p.add_argument("--all", action="store_true", help="(--list) inclure les inactifs")
    return p


async def _main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    # Garantit l'existence de tous les attributs attendus
    defaults = {
        "is_premium": None, "has_photo": None, "is_active": None,
        "price": None, "tags": None, "name": None, "label": None,
        "category": None, "description": None, "primary_color": None,
        "font_family": None, "layout_key": None, "lm_name": None,
        "lm_label": None, "dry_run": False, "report_csv": None,
        "with_lm": False, "templates_root": None, "all": False, "folder": None,
    }
    for attr, val in defaults.items():
        if not hasattr(args, attr):
            setattr(args, attr, val)

    try:
        if args.batch:              await action_batch_submit(args)
        elif args.list:             await action_list(args)
        elif getattr(args,"get",None):    await action_get(args)
        elif getattr(args,"update",None): await action_update(args)
        elif getattr(args,"delete",None): await action_delete(args)
        elif args.folder:           await action_submit(args)
        else:                       await action_batch_submit(args)
    except FileNotFoundError as e:
        logger.error("❌ %s", e); sys.exit(1)
    except ValueError as e:
        logger.error("❌ Validation : %s", e); sys.exit(2)
    except Exception as e:
        logger.exception("❌ Erreur inattendue : %s", e); sys.exit(1)


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()