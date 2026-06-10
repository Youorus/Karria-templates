"""
auth.py — Authentification machine Karria.
Spécialise OAuth2Manager : payload JSON, réponse encapsulée dans {"data": {...}}.
"""
from .core.auth import OAuth2Manager
from config import settings


def build_karria_auth() -> OAuth2Manager:
    for key in ["KARRIA_BASE_URL", "KARRIA_CLIENT_ID", "KARRIA_CLIENT_SECRET"]:
        if not hasattr(settings, key) or not getattr(settings, key):
            raise ValueError(
                f"Configuration Karria manquante : '{key}' n'est pas défini.\n"
                "Vérifie que ton .env contient bien KARRIA_BASE_URL, "
                "KARRIA_CLIENT_ID, et KARRIA_CLIENT_SECRET."
            )
    
    token_url = (
        f"{settings.KARRIA_BASE_URL.rstrip('/')}"
        f"{settings.KARRIA_API_PREFIX}"
        f"/machine-auth/token"
    )
    return OAuth2Manager(
        token_url=token_url,
        payload={
            "grant_type": "client_credentials",
            "client_id": settings.KARRIA_CLIENT_ID,
            "client_secret": settings.KARRIA_CLIENT_SECRET,
        },
        name="Karria",
        use_json=True,
        token_extractor=lambda d: d["data"]["access_token"] if "data" in d else d["access_token"],
        expires_extractor=lambda d: int(d["data"]["expires_in"]) if "data" in d else int(d.get("expires_in", 3600)),
    )
