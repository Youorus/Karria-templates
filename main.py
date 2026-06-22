
import os
import sys
from pathlib import Path

# Add project root to the Python path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# --- App Initialization ---
app = FastAPI(
    title="Karria Templates Web UI",
    description="Interface web pour la génération et la gestion de templates Karria.",
    version="1.0.0"
)

# Trust X-Forwarded-Proto from Traefik so url_for() generates https:// URLs
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# --- In-Memory Task Store ---
task_store = {}

# --- Routers ---
from app.routers.web import views
app.include_router(views.router, prefix="/web", tags=["Web Interface"])

# --- Static Files ---
static_dir = ROOT_DIR / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

outputs_dir = ROOT_DIR / "outputs"
app.mount("/outputs", StaticFiles(directory=str(outputs_dir)), name="outputs")

# --- Root Redirect ---
@app.get("/", include_in_schema=False)
async def root():
    """Redirects the root URL to the main template listing page."""
    return RedirectResponse(url="/web/templates")

# --- Startup/Shutdown Events ---
@app.on_event("startup")
async def startup_event():
    if not outputs_dir.exists():
        outputs_dir.mkdir(parents=True)
    print("Application startup complete. Uvicorn running...")

@app.on_event("shutdown")
async def shutdown_event():
    print("Application shutdown.")
