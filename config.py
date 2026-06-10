"""
config.py — Source unique de vérité pour TOUS les modules Karria.

Ce module est le seul endroit qui lit les variables d'environnement.
Tous les autres modules (generate_templates, submit_template, pipeline,
preview_renderer, visual_critic) DOIVENT importer depuis ici :

    from config import settings
    print(settings.MODEL, settings.OUTPUT_DIR, ...)

Avantages :
  • Une seule source de vérité (fini les double-lectures os.getenv)
  • Validation immédiate au chargement (KeyError plutôt qu'à minuit en prod)
  • Types corrects (int, float, Path) dès le départ
  • Test simple : on patch settings dans les tests, pas l'env système
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Charge .env une seule fois, au tout premier import.
load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS DE CAST
# ─────────────────────────────────────────────────────────────────────────────

def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise EnvironmentError(f"{key}={raw!r} n'est pas un entier valide")


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        raise EnvironmentError(f"{key}={raw!r} n'est pas un float valide")


def _env_path(key: str, default: str) -> Path:
    return Path(os.getenv(key, default)).expanduser()


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "oui"}


# ─────────────────────────────────────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Settings:
    """Configuration figée — instanciée une seule fois ci-dessous."""

    # ── Gemini ──
    GEMINI_API_KEY:     str
    MODEL:              str
    MAX_OUTPUT_TOKENS:  int
    TEMPERATURE:        float
    MAX_RETRIES:        int

    # ── PDF / Analyse ──
    DPI:                int

    # ── Génération double-passe ──
    ENABLE_VISUAL_CRITIC: bool   # 2e appel Gemini pour comparer rendu vs PDF

    # ── Chemins ──
    OUTPUT_DIR:          Path    # ./outputs/ — dossier où la pipeline ÉCRIT
    PDF_SEARCH_DIR:      Path    # ./templates/ — dossier où la pipeline LIT les PDF
    TEMPLATES_ROOT:      Path    # racine pour le navigateur de submit (= OUTPUT_DIR)

    # ── Preview ──
    PREVIEW_PORT:        int

    # ── Karria API ──
    KARRIA_BASE_URL: str
    KARRIA_API_PREFIX: str
    KARRIA_CLIENT_ID: str
    KARRIA_CLIENT_SECRET: str
    KARRIA_SCOPE: str

    # ── HTTP Client ──
    HTTP_TIMEOUT_TOTAL: float
    HTTP_TIMEOUT_CONNECT: float
    HTTP_MAX_CONNECTIONS: int
    HTTP_MAX_KEEPALIVE: int

    def validate(self) -> None:
        """Validation finale — appelée par tous les entrypoints CLI."""
        if not self.GEMINI_API_KEY:
            raise EnvironmentError(
                "GEMINI_API_KEY manquante. Ajoute-la dans .env :\n"
                "  GEMINI_API_KEY=ta_cle_ici"
            )
        if self.DPI < 72 or self.DPI > 600:
            raise EnvironmentError(f"DPI={self.DPI} hors plage [72, 600]")


def _build_settings() -> Settings:
    api_key = os.getenv("GEMINI_API_KEY", "")

    output_dir   = _env_path("OUTPUT_DIR",      "./outputs")
    pdf_search   = _env_path("PDF_SEARCH_DIR",  "./templates")
    templates_rt = _env_path("KARRIA_TEMPLATES_ROOT", str(output_dir))

    return Settings(
        GEMINI_API_KEY       = api_key,
        MODEL                = os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
        MAX_OUTPUT_TOKENS    = _env_int("MAX_OUTPUT_TOKENS", 32000),
        TEMPERATURE          = _env_float("TEMPERATURE", 0.15),
        MAX_RETRIES          = _env_int("MAX_RETRIES", 2),
        DPI                  = _env_int("DPI", 200),
        ENABLE_VISUAL_CRITIC = _env_bool("ENABLE_VISUAL_CRITIC", True),
        OUTPUT_DIR           = output_dir,
        PDF_SEARCH_DIR       = pdf_search,
        TEMPLATES_ROOT       = templates_rt,
        PREVIEW_PORT         = _env_int("PREVIEW_PORT", 8765),
        
        KARRIA_BASE_URL      = os.getenv("KARRIA_BASE_URL", "http://127.0.0.1:8000"),
        KARRIA_API_PREFIX    = os.getenv("KARRIA_API_PREFIX", "/api/v1"),
        KARRIA_CLIENT_ID     = os.getenv("KARRIA_CLIENT_ID", ""),
        KARRIA_CLIENT_SECRET = os.getenv("KARRIA_CLIENT_SECRET", ""),
        KARRIA_SCOPE         = os.getenv("KARRIA_SCOPE", "companies:read companies:write job_offers:read job_offers:write countries:read countries:write cities:read cities:write sectors:read sectors:write domains:read domains:write contract_types:read contract_types:write experience_levels:read experience_levels:write rome_jobs:read rome_jobs:write"),
        
        HTTP_TIMEOUT_TOTAL   = _env_float("HTTP_TIMEOUT_TOTAL", 15.0),
        HTTP_TIMEOUT_CONNECT = _env_float("HTTP_TIMEOUT_CONNECT", 5.0),
        HTTP_MAX_CONNECTIONS = _env_int("HTTP_MAX_CONNECTIONS", 200),
        HTTP_MAX_KEEPALIVE   = _env_int("HTTP_MAX_KEEPALIVE", 50),
    )


# Instance globale unique. Tout le reste du code l'importe.
settings: Settings = _build_settings()


# Pour rétro-compat avec ton code existant qui faisait `from config import GEMINI_API_KEY`.
# (Préfère utiliser `settings.X` dans tout nouveau code.)
GEMINI_API_KEY     = settings.GEMINI_API_KEY
MODEL              = settings.MODEL
OUTPUT_DIR         = str(settings.OUTPUT_DIR)
MAX_RETRIES        = settings.MAX_RETRIES
DPI                = settings.DPI
MAX_OUTPUT_TOKENS  = settings.MAX_OUTPUT_TOKENS
PDF_SEARCH_DIR     = str(settings.PDF_SEARCH_DIR)


__all__ = [
    "settings", "Settings",
    "GEMINI_API_KEY", "MODEL", "OUTPUT_DIR", "MAX_RETRIES",
    "DPI", "MAX_OUTPUT_TOKENS", "PDF_SEARCH_DIR",
]
