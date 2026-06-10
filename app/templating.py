
from fastapi.templating import Jinja2Templates
from pathlib import Path

# This file creates a single, shared instance of Jinja2Templates
# that can be imported by any part of the application.
# It resolves paths relative to this file's location in app/.

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
