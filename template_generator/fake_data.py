# template_generator/fake_data.py
"""
Générateur de données factices réalistes pour le preview HTML.

Objectif : remplacer les data.json "tirés du PDF" par des données
suffisamment réalistes pour qu'un humain puisse évaluer visuellement
si les textes longs débordent, si les sections s'affichent correctement, etc.
"""

from __future__ import annotations

import json
from typing import Any, Dict


# ─────────────────────────────────────────────────────────────────────────────
# FAKE DATA — CV
# ─────────────────────────────────────────────────────────────────────────────

CV_FAKE: Dict[str, Any] = {
    "fullName":   "Sophie Marchand",
    "jobTitle":   "Product Manager · Lead UX",
    "photo":      "",      # pas de photo par défaut (safe pour tous les templates)
    "availability": "Disponible dès septembre 2025",
    "preferred_language": "fr",

    "summary": (
        "Je suis Product Manager passionnée par l'expérience utilisateur et "
        "l'innovation produit. Fort de 7 ans d'expérience dans des scale-ups "
        "B2B, j'allie vision stratégique et exécution pragmatique pour livrer "
        "des produits qui créent de la valeur mesurable."
    ),

    "contact": {
        "phone":   "+33 6 12 34 56 78",
        "email":   "sophie.marchand@email.fr",
        "address": "12 rue des Lilas, 75010 Paris",
        "linkedin": "linkedin.com/in/sophiemarchand",
        "website":  "sophiemarchand.fr",
    },

    "labels": {
        "contact":     "Contact",
        "experiences": "Expériences professionnelles",
        "education":   "Formation",
        "skills":      "Compétences",
        "languages":   "Langues",
        "interests":   "Centres d'intérêt",
        "profile":     "Profil",
    },

    "experiences": [
        {
            "position":    "Senior Product Manager",
            "company":     "TechFlow SAS",
            "location":    "Paris",
            "start":       "2021",
            "end":         "En cours",
            "description": (
                "Pilotage de la roadmap produit d'une plateforme SaaS B2B "
                "(12 000 utilisateurs). Réduction du churn de 18 % en 12 mois "
                "grâce à une refonte onboarding data-driven."
            ),
        },
        {
            "position":    "Product Manager",
            "company":     "Innova Digital",
            "location":    "Lyon",
            "start":       "2018",
            "end":         "2021",
            "description": (
                "Lancement de 3 features majeures en 2 ans. "
                "Animation des sprints et coordination d'une équipe de 8 "
                "développeurs en méthodo agile."
            ),
        },
        {
            "position":    "UX Designer / Product Owner",
            "company":     "Agence Pixel",
            "location":    "Bordeaux",
            "start":       "2016",
            "end":         "2018",
            "description": (
                "Conception d'interfaces pour des clients grands comptes. "
                "Réalisation de tests utilisateurs et prototypage Figma."
            ),
        },
    ],

    "education": [
        {
            "degree":   "Master Management de l'Innovation Digitale",
            "school":   "Sciences Po Paris",
            "location": "Paris",
            "start":    "2014",
            "end":      "2016",
        },
        {
            "degree":   "Licence Informatique & Interaction",
            "school":   "Université Paris-Saclay",
            "location": "Orsay",
            "start":    "2011",
            "end":      "2014",
        },
    ],

    "skills": [
        {"name": "Product Strategy",    "level": 5},
        {"name": "UX Research",         "level": 5},
        {"name": "Figma / Prototyping", "level": 4},
        {"name": "SQL & Analytics",     "level": 4},
        {"name": "Agile / Scrum",       "level": 5},
        {"name": "Python (scripts)",    "level": 3},
        {"name": "A/B Testing",         "level": 4},
    ],

    "languages": [
        {"name": "Français",  "level": 5},
        {"name": "Anglais",   "level": 5},
        {"name": "Espagnol",  "level": 3},
    ],

    "interests": [
        {"icon": "🎨", "label": "Design thinking"},
        {"icon": "🚴", "label": "Cyclisme urbain"},
        {"icon": "📚", "label": "Tech & prospective"},
        {"icon": "🌿", "label": "Permaculture"},
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# FAKE DATA — LM
# ─────────────────────────────────────────────────────────────────────────────

LM_FAKE: Dict[str, Any] = {
    "fullName": "Sophie Marchand",
    "jobTitle": "Product Manager · Lead UX",
    "city":     "Paris",
    "date":     "4 mai 2025",
    "preferred_language": "fr",

    "contact": {
        "phone":   "+33 6 12 34 56 78",
        "email":   "sophie.marchand@email.fr",
        "address": "12 rue des Lilas, 75010 Paris",
    },

    "recipient": {
        "company": "TechVision SA",
        "address": "24 avenue de l'Innovation, 69002 Lyon",
        "name":    "Mme. Claire Dupont",
    },

    "labels": {"subject": "Objet"},
    "subject":    "Candidature au poste de Head of Product — Réf. HP-2025-04",
    "salutation": "Madame, Monsieur,",

    "paragraphs": [
        (
            "Forte de sept années d'expérience en gestion de produit dans des "
            "environnements SaaS B2B à forte croissance, je me permets de vous "
            "adresser ma candidature pour le poste de Head of Product au sein de "
            "TechVision SA, dont l'ambition de démocratiser l'accès aux outils "
            "analytiques m'enthousiasme particulièrement."
        ),
        (
            "Chez TechFlow, j'ai piloté la refonte complète de l'expérience "
            "d'activation, réduisant le délai de mise en valeur de 40 % et "
            "améliorant la rétention à 30 jours de 22 points. Cette transformation "
            "reposait sur une méthodologie alliant interviews utilisateurs, tests A/B "
            "rigoureux et collaboration étroite avec les équipes data et engineering."
        ),
        (
            "Je suis convaincue que mon profil hybride — stratégie produit, culture "
            "UX et appétence pour la donnée — correspond précisément aux défis que "
            "vous souhaitez relever. Je serais ravie d'approfondir ma candidature "
            "lors d'un entretien à votre convenance."
        ),
    ],

    "closing": "Je vous prie d'agréer, Madame, Monsieur, mes salutations distinguées.",
}


# ─────────────────────────────────────────────────────────────────────────────
# API PUBLIQUE
# ─────────────────────────────────────────────────────────────────────────────

def get_cv_fake_data() -> Dict[str, Any]:
    """Retourne une copie des données factices CV."""
    return dict(CV_FAKE)


def get_lm_fake_data() -> Dict[str, Any]:
    """Retourne une copie des données factices LM."""
    return dict(LM_FAKE)


def get_cv_fake_data_json() -> str:
    return json.dumps(CV_FAKE, ensure_ascii=False, indent=2)


def get_lm_fake_data_json() -> str:
    return json.dumps(LM_FAKE, ensure_ascii=False, indent=2)


def merge_with_data_json(template_data_json: str, fake_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fusionne les données du data.json généré par l'IA avec les fake data.
    Priorité : fake_data > data.json IA.
    Utile pour garantir que le preview montre des textes longs réalistes
    même si l'IA n'a généré que des données minimales.
    """
    try:
        ai_data = json.loads(template_data_json)
    except Exception:
        ai_data = {}

    merged = {**ai_data, **fake_data}
    # On garde les labels de l'IA (ils peuvent être plus précis)
    if "labels" in ai_data and isinstance(ai_data["labels"], dict):
        merged["labels"] = {**fake_data.get("labels", {}), **ai_data["labels"]}
    return merged