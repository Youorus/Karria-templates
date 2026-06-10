
import shutil
from pathlib import Path
import os

from app.services.web.task_manager import task_manager

# Import the actual generator function
from template_generator.generate_templates import generate

class GenerationService:
    def run_generation_pipeline(self, task_id: str, cv_path: str, lm_path: str | None, temp_dir: str):
        """
        The main pipeline function that will be run in the background.
        It calls the real generation logic.
        """
        try:
            task_manager.update_task_status(task_id, "in_progress")
            
            cv_file = Path(cv_path)
            lm_file = Path(lm_path) if lm_path else None
            
            # The `generate` function saves the output to its own configured directory (`outputs/`)
            # and returns the path to the created template folder.
            generated_template_path = generate(
                cv_pdf_path=str(cv_file),
                lm_pdf_path=str(lm_file) if lm_file else None,
                # We let it use the default output_dir defined in settings
            )

            template_id = generated_template_path.name
            task_manager.update_task_status(task_id, "completed", result={"template_id": template_id})

        except Exception as e:
            print(f"Task {task_id} failed: {e}")
            task_manager.update_task_status(task_id, "failed", error=str(e))
        finally:
            # Clean up the temporary directory that held the uploaded files
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)


generation_service = GenerationService()
