"""
client.py — Client Karria machine-to-machine.

Cache in-memory sur tous les référentiels stables (pays, secteurs, villes…)
pour éviter les lookups redondants en mode stream continu.
"""
import logging
from pathlib import Path
from typing import Any

import httpx

from .core.http_client import get_http_client, close_http_client
from config import settings
from .auth import build_karria_auth

logger = logging.getLogger(__name__)


class AuthError(Exception):
    pass


class KarriaAPIClient:
    def __init__(self) -> None:
        try:
            self._auth = build_karria_auth()
        except ValueError as e:
            raise AuthError(f"Client is not authenticated: {e}") from e
        self._base = settings.KARRIA_BASE_URL.rstrip("/")
        self._prefix = settings.KARRIA_API_PREFIX.rstrip("/")

        # ── Caches référentiels ──
        self._cache_countries: dict[str, dict] = {}
        self._cache_cities: dict[str, dict] = {}
        self._cache_sectors: dict[str, dict] = {}
        self._cache_domains: dict[str, dict] = {}
        self._cache_contract_types: dict[str, dict] = {}
        self._cache_rome_jobs: dict[str, dict] = {}
        self._cache_companies: dict[str, dict] = {}

        # ── Caches templates (name → dict) ──
        self._cache_cv_templates: dict[str, dict] = {}

    # =========================================================
    # 🔧 INTERNALS
    # =========================================================

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self._base}{self._prefix}{path}"

    @staticmethod
    def _clean(payload: dict[str, Any]) -> dict[str, Any]:
        """Retire les valeurs None d'un dict."""
        return {k: v for k, v in payload.items() if v is not None}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Requête JSON standard avec refresh automatique du token."""
        http = await get_http_client()
        token = await self._auth.get_token(http)

        resp = await http.request(
            method,
            self._url(path),
            json=json,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )

        if resp.status_code == 401:
            logger.warning("⚠️  Karria 401 — refresh forcé.")
            token = await self._auth.force_refresh(http)
            resp = await http.request(
                method,
                self._url(path),
                json=json,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )

        resp.raise_for_status()
        return resp.json()

    async def _request_multipart(
            self,
            path: str,
            *,
            data: dict[str, Any],
            files: dict[str, tuple],
            timeout: float = 300.0,  # ← 5 min, pipeline preview peut être long
    ) -> dict[str, Any]:
        http = await get_http_client()
        token = await self._auth.get_token(http)

        resp = await http.post(
            self._url(path),
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,  # ← surcharge le timeout du client singleton
        )

        if resp.status_code == 401:
            logger.warning("⚠️  Karria 401 (multipart) — refresh forcé.")
            token = await self._auth.force_refresh(http)
            resp = await http.post(
                self._url(path),
                data=data,
                files=files,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,  # ← idem sur le retry
            )

        resp.raise_for_status()
        return resp.json()
    # =========================================================
    # 🌍 PAYS
    # =========================================================

    async def get_or_create_country(self, *, code: str, name: str) -> dict[str, Any]:
        if code in self._cache_countries:
            return self._cache_countries[code]

        # Suppression du /lookup qui cause des 405
        # On tente directement la création, le backend doit gérer l'existant
        result = (
            await self._request("POST", "/countries/", json={"code": code, "name": name})
        )["data"]

        self._cache_countries[code] = result
        return result

    # =========================================================
    # 🏙️ VILLES
    # =========================================================

    async def get_or_create_city(
        self,
        *,
        name: str,
        postal_code: str | None = None,
        country_id: int | None = None,
        country_code: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict[str, Any]:
        cache_key = f"{postal_code or name}:{country_id}"
        if cache_key in self._cache_cities:
            return self._cache_cities[cache_key]

        # Suppression du /lookup qui cause des 405
        result = (
            await self._request(
                "POST",
                "/cities/",
                json=self._clean({
                    "name": name,
                    "postal_code": postal_code,
                    "latitude": latitude,
                    "longitude": longitude,
                    "country_id": country_id,
                    "country_code": country_code,
                }),
            )
        )["data"]

        self._cache_cities[cache_key] = result
        return result

    # =========================================================
    # 🏢 ENTREPRISES
    # =========================================================

    async def get_or_create_company(
        self,
        *,
        name: str,
        description: str | None = None,
        logo: str | None = None,
        website: str | None = None,
    ) -> dict[str, Any]:
        cache_key = (website or name).lower()
        if cache_key in self._cache_companies:
            return self._cache_companies[cache_key]

        # Suppression du /lookup qui cause des 405
        result = (
            await self._request(
                "POST",
                "/companies/machine/create",
                json=self._clean({"name": name, "description": description, "logo": logo, "website": website}),
            )
        )["data"]

        self._cache_companies[cache_key] = result
        return result

    async def update_company(self, company_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        result = await self._request(
            "PATCH",
            f"/companies/machine/{company_id}",
            json=self._clean(payload),
        )
        return result.get("data", result)

    async def delete_company(self, company_id: int) -> None:
        await self._request("DELETE", f"/companies/machine/{company_id}")

    # =========================================================
    # 🏭 SECTEURS
    # =========================================================

    async def get_or_create_sector(self, *, code: str, label: str) -> dict[str, Any]:
        if code in self._cache_sectors:
            return self._cache_sectors[code]

        # Suppression du /lookup qui cause des 405
        result = (await self._request("POST", "/sectors/", json={"code": code, "label": label}))["data"]

        self._cache_sectors[code] = result
        return result

    # =========================================================
    # 🗂️ DOMAINES
    # =========================================================

    async def get_or_create_domain(
        self,
        *,
        code: str,
        label: str,
        sector_id: int | None = None,
    ) -> dict[str, Any]:
        if code in self._cache_domains:
            return self._cache_domains[code]

        # Suppression du /lookup qui cause des 405
        result = (
            await self._request(
                "POST",
                "/domains/",
                json=self._clean({"code": code, "label": label, "sector_id": sector_id}),
            )
        )["data"]

        self._cache_domains[code] = result
        return result

    # =========================================================
    # 📄 TYPES DE CONTRAT
    # =========================================================

    async def get_or_create_contract_type(self, *, code: str, label: str) -> dict[str, Any]:
        if code in self._cache_contract_types:
            return self._cache_contract_types[code]

        # Suppression du /lookup qui cause des 405
        result = (
            await self._request("POST", "/contract-types/", json={"code": code, "label": label})
        )["data"]

        self._cache_contract_types[code] = result
        return result

    # =========================================================
    # 💼 ROME JOBS
    # =========================================================

    async def get_or_create_rome_job(
        self,
        *,
        rome_code: str,
        label: str,
        domain_id: int,
    ) -> dict[str, Any]:
        if rome_code in self._cache_rome_jobs:
            return self._cache_rome_jobs[rome_code]

        # Suppression du /lookup qui cause des 405
        result = (
            await self._request(
                "POST",
                "/rome-jobs/",
                json={"rome_code": rome_code, "label": label, "domain_id": domain_id},
            )
        )["data"]

        self._cache_rome_jobs[rome_code] = result
        return result

    # =========================================================
    # 📋 OFFRES D'EMPLOI
    # =========================================================

    async def lookup_job_offer(self, *, source_id: str, origin_source: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/job-offers/machine/lookup",
            json={"source_id": source_id, "origin_source": origin_source},
        )

    async def create_job_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/job-offers/machine/create", json=self._clean(payload))

    async def get_or_create_job_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        lookup = await self.lookup_job_offer(
            source_id=payload["source_id"],
            origin_source=payload["origin_source"],
        )
        data = lookup.get("data", {})
        if data.get("exists"):
            return data["offer"]
        return (await self.create_job_offer(payload))["data"]

    # =========================================================
    # 🎨 CV TEMPLATES
    # =========================================================

    async def get_cv_template(self, template_id: int) -> dict[str, Any]:
        """Récupère un CV template par son ID."""
        result = await self._request("GET", f"/machine/templates/{template_id}")
        return result.get("data", result)

    async def list_cv_templates(self, active_only: bool = True) -> list[dict[str, Any]]:
        """Liste tous les CV templates."""
        result = await self._request(
            "GET",
            "/machine/templates",
            params={"active_only": str(active_only).lower()},
        )
        return result.get("data", result)["items"]

    async def update_cv_template(
        self,
        template_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Met à jour un CV template (PATCH partiel)."""
        result = await self._request(
            "PATCH",
            f"/machine/templates/{template_id}",
            json=self._clean(payload),
        )
        return result.get("data", result)

    async def delete_cv_template(self, template_id: int) -> None:
        """Supprime un CV template (et ses LM en cascade)."""
        await self._request("DELETE", f"/machine/templates/{template_id}")
        # Invalider le cache
        self._cache_cv_templates = {
            k: v for k, v in self._cache_cv_templates.items()
            if v.get("id") != template_id
        }

    # =========================================================
    # ✉️ COVER LETTER TEMPLATES
    # =========================================================

    async def list_cover_letters(self, cv_template_id: int) -> list[dict[str, Any]]:
        """Liste les LM d'un CV template donné."""
        result = await self._request(
            "GET",
            f"/machine/templates/{cv_template_id}/cover-letters",
        )
        return result.get("data", result)["items"]

    async def get_cover_letter(self, cover_letter_id: int) -> dict[str, Any]:
        """Récupère une LM par son ID."""
        result = await self._request(
            "GET",
            f"/machine/cover-letters/{cover_letter_id}",
        )
        return result.get("data", result)

    async def update_cover_letter(
        self,
        cover_letter_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Met à jour une LM (PATCH partiel)."""
        result = await self._request(
            "PATCH",
            f"/machine/cover-letters/{cover_letter_id}",
            json=self._clean(payload),
        )
        return result.get("data", result)

    async def delete_cover_letter(self, cover_letter_id: int) -> None:
        """Supprime une LM."""
        await self._request("DELETE", f"/machine/cover-letters/{cover_letter_id}")

    # =========================================================
    # 🤖 SUBMIT FULL — CV + LM depuis un dossier local
    # =========================================================

    async def submit_full_template(
        self,
        *,
        # ── Métadonnées CV ──
        cv_name: str,
        cv_label: str,
        cv_html: bytes,
        cv_css: bytes,
        cv_preview_pdf: bytes,
        cv_category: str = "classic",
        cv_description: str | None = None,
        cv_primary_color: str = "#1A73E8",
        cv_font_family: str = "Inter",
        cv_is_premium: bool = False,
        cv_price: float | None = None,
        cv_is_active: bool = True,
        cv_has_photo: bool = False,
        cv_tags: list[str] | None = None,
        cv_review_description: str | None = None,
        cv_layout_key: str = "two-column-left-sidebar",
        cv_schema: bytes | None = None,
        cv_data: bytes | None = None,
        cv_infos: bytes | None = None,
        # ── Métadonnées LM ──
        with_cover_letter: bool = False,
        lm_name: str | None = None,
        lm_label: str | None = None,
        lm_html: bytes | None = None,
        lm_css: bytes | None = None,
        lm_preview_pdf: bytes | None = None,
        lm_category: str = "classic",
        lm_description: str | None = None,
        lm_primary_color: str | None = None,
        lm_font_family: str | None = None,
        lm_layout_key: str = "standard-letter",
        lm_schema: bytes | None = None,
        lm_data: bytes | None = None,
    ) -> dict[str, Any]:
        """
        Envoie un template complet (CV + LM optionnelle) en multipart/form-data.
        Retourne le résultat {"cv_template": {...}, "cover_letter": {...}|None}.
        """
        import json as _json

        # ── Form fields ──
        # Les booléens sont sérialisés en "true"/"false" (multipart = tout string).
        # Les champs optionnels None sont omis — FastAPI leur applique leur valeur
        # par défaut côté router plutôt que de recevoir la string "None".
        data: dict[str, Any] = {
            "cv_name":           cv_name,
            "cv_label":          cv_label,
            "cv_category":       cv_category,
            "cv_primary_color":  cv_primary_color,
            "cv_font_family":    cv_font_family,
            "cv_is_premium":     str(cv_is_premium).lower(),
            "cv_is_active":      str(cv_is_active).lower(),
            "cv_has_photo":      str(cv_has_photo).lower(),
            "cv_layout_key":     cv_layout_key,
            "with_cover_letter": str(with_cover_letter).lower(),
            "lm_layout_key":     lm_layout_key,
            "lm_category":       lm_category,
        }

        # Champs optionnels — envoyés uniquement s'ils ont une valeur.
        # IMPORTANT : cv_price doit être une string pour le multipart
        # (le router le reparse en Decimal côté backend).
        if cv_description is not None:
            data["cv_description"] = cv_description
        if cv_price is not None:
            data["cv_price"] = str(cv_price)
        if cv_tags is not None:
            # cv_tags est sérialisé en JSON string — le router le décode via json.loads()
            data["cv_tags"] = _json.dumps(cv_tags)
        if cv_review_description is not None:
            data["cv_review_description"] = cv_review_description
        if lm_name is not None:
            data["lm_name"] = lm_name
        if lm_label is not None:
            data["lm_label"] = lm_label
        if lm_description is not None:
            data["lm_description"] = lm_description
        if lm_primary_color is not None:
            data["lm_primary_color"] = lm_primary_color
        if lm_font_family is not None:
            data["lm_font_family"] = lm_font_family

        # ── Fichiers CV ──
        files: dict[str, tuple] = {
            "cv_html_file":   ("template.html", cv_html,        "text/html"),
            "cv_css_file":    ("style.css",     cv_css,         "text/css"),
            "cv_preview_pdf": ("preview.pdf",   cv_preview_pdf, "application/pdf"),
        }

        # CORRECTION : le router backend attend "schema_file" (sans préfixe cv_),
        # "data_file" et "infos_file" — alignés avec les paramètres UploadFile
        # du endpoint /machine/submit-full.
        # L'ancien nom "cv_schema_file" ne correspondait à aucun paramètre
        # du router → le fichier était ignoré silencieusement → config_schema NULL en DB.
        if cv_schema is not None:
            files["cv_config_schema_file"] = ("schema.json", cv_schema, "application/json")
        if cv_data is not None:
            files["cv_data_file"] = ("data.json", cv_data, "application/json")
        if cv_infos is not None:
            files["cv_infos_file"] = ("infos.json", cv_infos, "application/json")

        # ── Fichiers LM ──
        if with_cover_letter:
            if lm_html is not None:
                files["lm_html_file"] = ("lm_template.html", lm_html, "text/html")
            if lm_css is not None:
                files["lm_css_file"] = ("lm_style.css", lm_css, "text/css")
            if lm_preview_pdf is not None:
                files["lm_preview_pdf"] = ("lm_preview.pdf", lm_preview_pdf, "application/pdf")
            if lm_schema is not None:
                files["lm_config_schema_file"] = ("lm_schema.json", lm_schema, "application/json")
            if lm_data is not None:
                files["lm_data_file"] = ("lm_data.json", lm_data, "application/json")

        # Log de ce qui est envoyé — aide au debug
        logger.debug(
            "[submit_full_template] form fields: %s | files: %s",
            list(data.keys()),
            {k: v[0] for k, v in files.items()},
        )

        resp = await self._request_multipart(
            "/machine/submit-full",
            data=data,
            files=files,
        )

        result = resp.get("data", resp)

        # Mettre en cache le CV créé
        cv = result.get("cv_template", {})
        if cv.get("name"):
            self._cache_cv_templates[cv["name"]] = cv

        return result

    # =========================================================
    # 🔍 LOOKUP CV TEMPLATE (par name — depuis le cache ou l'API)
    # =========================================================

    async def lookup_cv_template_by_name(self, name: str) -> dict[str, Any] | None:
        """
        Retourne le CV template dont le `name` correspond,
        ou None s'il n'existe pas.
        Vérifie d'abord le cache local, sinon parcourt la liste API.
        """
        if name in self._cache_cv_templates:
            return self._cache_cv_templates[name]

        templates = await self.list_cv_templates(active_only=False)
        for t in templates:
            self._cache_cv_templates[t["name"]] = t

        return self._cache_cv_templates.get(name)

    # =========================================================
    # 🔄 LIFECYCLE
    # =========================================================

    async def close(self) -> None:
        await close_http_client()

    async def __aenter__(self) -> "KarriaAPIClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()