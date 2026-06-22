import json
from pathlib import Path
from typing import Any, Dict

OUTPUTS_DIR = Path("outputs")


class TestService:

    def has_lm(self, template_id: str) -> bool:
        return (OUTPUTS_DIR / template_id / "lm" / "lm_template.html").exists()

    def get_cv_test_data(self, template_id: str) -> Dict[str, Any]:
        from template_generator.fake_data import get_cv_fake_data, merge_with_data_json

        data_path = OUTPUTS_DIR / template_id / "data.json"
        fake = get_cv_fake_data()
        if data_path.exists():
            try:
                ai_data = json.loads(data_path.read_text(encoding="utf-8"))
                return merge_with_data_json(json.dumps(ai_data), fake)
            except Exception:
                pass
        return fake

    def get_lm_test_data(self, template_id: str) -> Dict[str, Any]:
        from template_generator.fake_data import get_lm_fake_data

        data_path = OUTPUTS_DIR / template_id / "lm" / "lm_data.json"
        fake = get_lm_fake_data()
        if data_path.exists():
            try:
                ai_data = json.loads(data_path.read_text(encoding="utf-8"))
                return {**fake, **ai_data}
            except Exception:
                pass
        return fake

    def render_cv(self, template_id: str, data: Dict[str, Any]) -> str:
        from template_generator.preview_renderer import _render_template

        html_path = OUTPUTS_DIR / template_id / "template.html"
        if not html_path.exists():
            return "<p style='color:red'>template.html introuvable</p>"
        return _render_template(html_path, data)

    def render_lm(self, template_id: str, data: Dict[str, Any]) -> str:
        from template_generator.preview_renderer import _render_template

        html_path = OUTPUTS_DIR / template_id / "lm" / "lm_template.html"
        if not html_path.exists():
            return "<p style='color:red'>lm_template.html introuvable</p>"
        return _render_template(html_path, data)


test_service = TestService()
