
from typing import Dict, Any
from pathlib import Path

# Import the actual validation and rendering functions
from template_generator.preview_renderer import _rebuild_rendered, _validate_preview_html

class PreviewValidator:
    def validate_preview(self, template_id: str) -> Dict[str, Any]:
        """
        Runs the actual technical validations on the generated template files
        by rendering the HTML and then analyzing it with Playwright.
        """
        template_dir = Path("outputs") / template_id
        if not template_dir.is_dir():
            return {
                "score": 0,
                "passed": False,
                "issues": [{"level": "critical", "category": "file", "message": "Template directory not found."}],
                "metrics": {}
            }

        # 1. Re-render the template with fake data, just like the preview server does.
        rendered_html = _rebuild_rendered(template_dir)

        # 2. Run the real validation function on the rendered HTML.
        validation_report = _validate_preview_html(rendered_html)
        
        return validation_report

preview_validator = PreviewValidator()
