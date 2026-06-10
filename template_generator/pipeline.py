#!/usr/bin/env python3
"""
pipeline.py — Orchestrateur complet Karria.

Enchaîne en un seul flux :
  1. generate  → PDF → template HTML/CSS/JSON + infos.json
  2. review    → preview côte-à-côte (PDF original vs HTML rendu)
                 attente décision humaine : ✅ Valider / ❌ Rejeter
  3. submit    → envoi au backend via KarriaAPIClient si validé

Modes :

  Single :
    python -m template_generator.pipeline --cv ./inputs/cv.pdf
    python -m template_generator.pipeline              ← interactif

  Batch :
    python -m template_generator.pipeline --batch

  Génération seule (sans review ni submit) :
    python -m template_generator.pipeline --cv ./inputs/cv.pdf --generate-only

  Review + submit d'un template déjà généré :
    python -m template_generator.pipeline --review ./outputs/blue-spark

  Submit d'un template déjà reviewé :
    python -m template_generator.pipeline --submit-only ./outputs/blue-spark

Séquence de décision :
  ┌─────────────────────────────────────────────────────────────┐
  │  generate() → dossier outputs/blue-spark/                   │
  │       ↓                                                      │
  │  preview_renderer.run_preview()                             │
  │    navigateur ouvre côte-à-côte PDF | HTML                  │
  │    tu peux éditer template.html/style.css → hot-reload       │
  │       ↓                                                      │
  │  ✅ Valider            ❌ Rejeter                            │
  │  → action_submit()     → arrêt propre                        │
  │  → template en prod ✓                                        │
  └─────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings

from .generate_templates import generate, _browse_for_pdf, _ask_premium, _run_batch
from .preview_renderer   import run_preview
from .submit_template    import action_submit, SubmitResult

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ═════════════════════════════════════════════════════════════════════════════

async def run_pipeline(
    cv_pdf_path:        str,
    output_dir:         Path,
    *,
    # génération
    label:              Optional[str]  = None,
    name:               Optional[str]  = None,
    category:           Optional[str]  = None,
    is_premium:         bool           = False,
    price:              Optional[float]= None,
    is_active:          bool           = True,
    tags:               Optional[List[str]] = None,
    layout_key:         Optional[str]  = None,
    lm_pdf_path:        Optional[str]  = None,
    lm_label:           Optional[str]  = None,
    lm_layout_key:      str            = "standard-letter",
    skip_visual_critic: bool           = False,
    # comportement pipeline
    generate_only:      bool           = False,
    skip_review:        bool           = False,
    preview_port:       int            = 0,
) -> Tuple[Optional[Path], Optional[SubmitResult]]:
    """
    Pipeline complet : génère → review → soumet.

    Returns:
        (template_dir, submit_result)
        template_dir   = Path du dossier généré (ou None si échec)
        submit_result  = SubmitResult (ou None si generate-only ou rejeté)
    """
    # ── ÉTAPE 1 : GÉNÉRATION ──────────────────────────────────────────────
    print("\n" + "═" * 70)
    print("  ÉTAPE 1/3 — Génération du template")
    print("═" * 70)

    try:
        template_dir = generate(
            cv_pdf_path=cv_pdf_path,
            label=label,
            output_dir=output_dir,
            name=name,
            category=category,
            is_premium=is_premium,
            price=price,
            is_active=is_active,
            tags=tags,
            layout_key=layout_key,
            lm_pdf_path=lm_pdf_path,
            lm_label=lm_label,
            lm_layout_key=lm_layout_key,
            skip_visual_critic=skip_visual_critic,
        )
    except Exception as e:
        logger.error("💥 Génération échouée : %s", e)
        return None, None

    if generate_only:
        print(f"\n✅ Génération seule terminée : {template_dir}")
        print("  Lance plus tard : python -m template_generator.pipeline --review", template_dir)
        return template_dir, None

    # ── ÉTAPE 2 : REVIEW PREVIEW ──────────────────────────────────────────
    print("\n" + "═" * 70)
    print("  ÉTAPE 2/3 — Review du preview (côte-à-côte)")
    print("═" * 70)

    if skip_review:
        print("⏭️  Review skippée (--skip-review)")
        approved = True
    else:
        approved = run_preview(
            template_dir,
            pdf_path=Path(cv_pdf_path),
            port=preview_port,
            auto_open=True,
        )

    if not approved:
        print("\n❌ Template rejeté — pipeline arrêtée.")
        print(f"   Dossier conservé : {template_dir}")
        print(f"   Tu peux l'éditer puis relancer avec : --review {template_dir}")
        return template_dir, None

    # ── ÉTAPE 3 : SUBMIT ──────────────────────────────────────────────────
    print("\n" + "═" * 70)
    print("  ÉTAPE 3/3 — Soumission au backend Karria")
    print("═" * 70)

    sub_args = argparse.Namespace(
        folder   = str(template_dir),
        with_lm  = lm_pdf_path is not None,
        dry_run  = False,
        # pas d'overrides — on lit infos.json
        name=None, label=None, category=None, description=None,
        primary_color=None, font_family=None, layout_key=None,
        is_premium=None, has_photo=None, is_active=None,
        price=None, tags=None, lm_name=None, lm_label=None,
    )

    try:
        result = await action_submit(sub_args)
    except Exception as e:
        logger.error("💥 Submit échoué : %s", e)
        print(f"\n⚠️  Le template est sauvegardé dans : {template_dir}")
        print(f"   Relance manuellement : python -m template_generator.submit_template {template_dir}")
        return template_dir, None

    print(f"\n🎉 Pipeline complète ! Template #{result.cv_id} en production.")
    return template_dir, result


# ═════════════════════════════════════════════════════════════════════════════
# MODE REVIEW-ONLY (template déjà généré)
# ═════════════════════════════════════════════════════════════════════════════

async def run_review_then_submit(
    template_dir: Path,
    *,
    with_lm:      bool = False,
    preview_port: int  = 0,
) -> Optional[SubmitResult]:
    """Review d'un template déjà généré → submit si validé."""
    if not template_dir.exists():
        raise FileNotFoundError(f"Dossier introuvable : {template_dir}")

    # Cherche le PDF original
    pdf_path = template_dir / "preview.pdf"
    pdf_arg  = pdf_path if pdf_path.exists() else None

    print(f"\n🔍 Review du template : {template_dir.name}")
    approved = run_preview(
        template_dir,
        pdf_path=pdf_arg,
        port=preview_port,
        auto_open=True,
    )

    if not approved:
        print("❌ Rejeté.")
        return None

    sub_args = argparse.Namespace(
        folder   = str(template_dir),
        with_lm  = with_lm,
        dry_run  = False,
        name=None, label=None, category=None, description=None,
        primary_color=None, font_family=None, layout_key=None,
        is_premium=None, has_photo=None, is_active=None,
        price=None, tags=None, lm_name=None, lm_label=None,
    )
    return await action_submit(sub_args)


# ═════════════════════════════════════════════════════════════════════════════
# MODE BATCH (plusieurs CV/LM)
# ═════════════════════════════════════════════════════════════════════════════

async def run_batch_pipeline(
    jobs:         List[Dict[str, Any]],
    output_dir:   Path,
    *,
    skip_review:  bool = False,
    preview_port: int  = 0,
) -> None:
    """
    Mode batch avec queue.

    Pour chaque job :
      1. Génération
      2. Review (sauf --skip-review)
      3. Décision : Valider → submit, Rejeter → suivant
    """
    total   = len(jobs)
    results = []

    for idx, job in enumerate(jobs, 1):
        print(f"\n{'═' * 70}")
        print(f"▶️  Job {idx}/{total} — {Path(job['cv']).name}")
        print("═" * 70)

        td, sr = await run_pipeline(
            cv_pdf_path        = job["cv"],
            output_dir         = output_dir,
            is_premium         = bool(job.get("premium")),
            price              = job.get("price"),
            lm_pdf_path        = job.get("lm"),
            skip_visual_critic = job.get("no_critic", False),
            skip_review        = skip_review,
            preview_port       = preview_port,
        )
        results.append({
            "job":    idx,
            "cv":     job["cv"],
            "dir":    td,
            "result": sr,
        })

        if sr is None and not skip_review:
            # Rejeté : continue au suivant sans bloquer
            pass

    # Résumé
    submitted = [r for r in results if r["result"] and r["result"].success]
    skipped   = [r for r in results if r["result"] is None]

    print(f"\n{'═' * 70}")
    print(f"📊 Batch terminé — ✅ soumis : {len(submitted)}  ⏭️ skippés : {len(skipped)}")
    for r in submitted:
        print(f"  ✅ Job {r['job']} → #{r['result'].cv_id}")
    for r in skipped:
        print(f"  ⏭️  Job {r['job']} → {Path(r['cv']).name}")


# ═════════════════════════════════════════════════════════════════════════════
# MODES INTERACTIFS
# ═════════════════════════════════════════════════════════════════════════════

def _interactive_pipeline() -> argparse.Namespace:
    print("=" * 60)
    print("  Karria — Pipeline complète")
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
        premium=premium, price=price, inactive=False,
        tags=None, layout=None, lm_label=None, lm_layout="standard-letter",
        output=out or str(settings.OUTPUT_DIR),
        batch=False, generate_only=False, skip_review=False,
        no_critic=False, review=None, submit_only=None,
        preview_port=0, verbose=False,
    )


def _interactive_batch_pipeline() -> argparse.Namespace:
    print("=" * 60)
    print("  Karria — Pipeline batch")
    print("=" * 60)

    out   = input(f"Dossier de sortie [{settings.OUTPUT_DIR}] : ").strip() or str(settings.OUTPUT_DIR)
    jobs: List[Dict[str, Any]] = []

    while True:
        print(f"\n➕ Job #{len(jobs) + 1}")
        cv = _browse_for_pdf("CV")
        if not cv:
            print("PDF CV obligatoire."); continue

        lm = None
        if input("Ajouter une LM ? [y/N] ").strip().lower() in ("y", "yes", "o", "oui"):
            lm = _browse_for_pdf("Lettre", start_dir=str(Path(cv).parent), allow_skip=True) or None

        premium, price = _ask_premium()
        jobs.append({"cv": cv, "lm": lm, "premium": premium, "price": price})

        if input("\nAjouter un autre CV ? [Y/n] ").strip().lower() in ("n", "no", "non"):
            break

    if not jobs:
        sys.exit("File vide.")

    return argparse.Namespace(
        batch=True, jobs=jobs, output=out,
        inactive=False, verbose=False,
        generate_only=False, skip_review=False, no_critic=False,
        review=None, submit_only=None, preview_port=0,
    )


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Pipeline complète Karria : generate → review → submit",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--cv",          help="PDF CV (lance la pipeline complète)")
    mode.add_argument("--review",      metavar="DIR",
                      help="Review + submit d'un template déjà généré")
    mode.add_argument("--submit-only", dest="submit_only", metavar="DIR",
                      help="Submit direct (pas de review) d'un template déjà généré")
    mode.add_argument("--batch",       action="store_true",
                      help="Mode batch interactif")

    gen = p.add_argument_group("Génération")
    gen.add_argument("--lm",            default=None)
    gen.add_argument("--label",         default=None)
    gen.add_argument("--name",          default=None)
    gen.add_argument("--category",      default=None)
    gen.add_argument("--premium",       action="store_true")
    gen.add_argument("--price",         type=float, default=None)
    gen.add_argument("--inactive",      action="store_true")
    gen.add_argument("--tags",          default=None)
    gen.add_argument("--layout",        default=None)
    gen.add_argument("--lm-label",      dest="lm_label", default=None)
    gen.add_argument("--lm-layout",     dest="lm_layout", default="standard-letter")
    gen.add_argument("--output", "-o",  default=None)

    ctl = p.add_argument_group("Contrôle pipeline")
    ctl.add_argument("--generate-only", dest="generate_only", action="store_true",
                     help="Génère uniquement, sans review ni submit")
    ctl.add_argument("--skip-review",   dest="skip_review",   action="store_true",
                     help="Saute la review et soumet directement")
    ctl.add_argument("--no-critic",     dest="no_critic",     action="store_true",
                     help="Désactive la passe 2 visual critic")
    ctl.add_argument("--with-lm",       dest="with_lm",       action="store_true",
                     help="(--review / --submit-only) inclure la LM du dossier")
    ctl.add_argument("--preview-port",  dest="preview_port",  type=int, default=0)
    ctl.add_argument("--verbose", "-v", action="store_true")
    return p


async def _main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    output_dir = Path(getattr(args, "output", None) or str(settings.OUTPUT_DIR)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Mode --review ──────────────────────────────────────────────────
    if getattr(args, "review", None):
        await run_review_then_submit(
            Path(args.review).resolve(),
            with_lm=getattr(args, "with_lm", False),
            preview_port=args.preview_port,
        )
        return

    # ── Mode --submit-only ─────────────────────────────────────────────
    if getattr(args, "submit_only", None):
        sub_args = argparse.Namespace(
            folder   = str(Path(args.submit_only).resolve()),
            with_lm  = getattr(args, "with_lm", False),
            dry_run  = False,
            name=None, label=None, category=None, description=None,
            primary_color=None, font_family=None, layout_key=None,
            is_premium=None, has_photo=None, is_active=None,
            price=None, tags=None, lm_name=None, lm_label=None,
        )
        await action_submit(sub_args)
        return

    # ── Mode --batch ───────────────────────────────────────────────────
    if args.batch:
        args = _interactive_batch_pipeline()
        await run_batch_pipeline(
            jobs         = args.jobs,
            output_dir   = output_dir,
            skip_review  = getattr(args, "skip_review", False),
            preview_port = getattr(args, "preview_port", 0),
        )
        return

    # ── Mode --cv (ou interactif) ──────────────────────────────────────
    if not getattr(args, "cv", None):
        args = _interactive_pipeline()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else None

    await run_pipeline(
        cv_pdf_path        = args.cv,
        output_dir         = output_dir,
        label              = args.label,
        name               = getattr(args, "name", None),
        category           = getattr(args, "category", None),
        is_premium         = getattr(args, "premium", False),
        price              = getattr(args, "price", None),
        is_active          = not getattr(args, "inactive", False),
        tags               = tags,
        layout_key         = getattr(args, "layout", None),
        lm_pdf_path        = getattr(args, "lm", None),
        lm_label           = getattr(args, "lm_label", None),
        lm_layout_key      = getattr(args, "lm_layout", "standard-letter"),
        skip_visual_critic = getattr(args, "no_critic", False),
        generate_only      = getattr(args, "generate_only", False),
        skip_review        = getattr(args, "skip_review", False),
        preview_port       = getattr(args, "preview_port", 0),
    )


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()