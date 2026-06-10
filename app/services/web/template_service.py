
import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

OUTPUTS_DIR = Path("outputs")

class TemplateService:
    def list_generated_templates(self) -> List[Dict[str, Any]]:
        """
        Scans the outputs directory and returns a list of found templates
        with some metadata from their infos.json.
        """
        if not OUTPUTS_DIR.exists():
            return []

        templates = []
        for d in OUTPUTS_DIR.iterdir():
            if d.is_dir():
                info_file = d / "infos.json"
                template_data = {"id": d.name, "label": d.name, "category": "N/A"}
                if info_file.exists():
                    try:
                        with open(info_file, 'r') as f:
                            info_json = json.load(f)
                            template_data["label"] = info_json.get("label", d.name)
                            template_data["category"] = info_json.get("category", {"name": "N/A"}).get("name")
                    except (json.JSONDecodeError, IOError):
                        pass
                templates.append(template_data)
        return templates

    def get_template_details(self, template_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves all details for a single template, including file contents.
        """
        template_dir = OUTPUTS_DIR / template_id
        if not template_dir.is_dir():
            return None

        details = {"id": template_id, "files": {}}
        for f in template_dir.iterdir():
            if f.is_file():
                content = None
                try:
                    if f.suffix in ['.html', '.css', '.json']:
                        content = f.read_text(encoding='utf-8')
                    details["files"][f.name] = {"size": f.stat().st_size, "content": content}
                except IOError:
                    details["files"][f.name] = {"size": f.stat().st_size, "content": "Error reading file"}
        
        # Load infos for display
        info_file = template_dir / "infos.json"
        if info_file.exists():
            details["infos"] = json.loads(info_file.read_text())
        
        return details

template_service = TemplateService()
