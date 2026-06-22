
import shutil
import sys
import threading
from pathlib import Path
import os

from app.services.web.task_manager import task_manager
from template_generator.generate_templates import generate


class _StdoutCapture:
    """
    Redirects stdout writes from the generation thread into task logs.
    Only captures writes from the thread that created this instance;
    other threads still go to the original stdout unchanged.
    """

    def __init__(self, task_id: str, task_mgr, original):
        self._task_id = task_id
        self._task_mgr = task_mgr
        self._original = original
        self._buf = ""
        self._tid = threading.get_ident()

    def write(self, text: str):
        self._original.write(text)
        if threading.get_ident() == self._tid:
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    self._task_mgr.add_log(self._task_id, line)

    def flush(self):
        self._original.flush()

    def flush_remaining(self):
        if self._buf.strip():
            self._task_mgr.add_log(self._task_id, self._buf.strip())
            self._buf = ""


class GenerationService:
    def run_generation_pipeline(self, task_id: str, cv_path: str, lm_path: str | None, temp_dir: str):
        try:
            task_manager.update_task_status(task_id, "in_progress")

            original = sys.stdout
            capture = _StdoutCapture(task_id, task_manager, original)
            sys.stdout = capture

            try:
                generated_template_path = generate(
                    cv_pdf_path=str(Path(cv_path)),
                    lm_pdf_path=str(Path(lm_path)) if lm_path else None,
                )
            finally:
                sys.stdout = original
                capture.flush_remaining()

            template_id = generated_template_path.name
            task_manager.update_task_status(task_id, "completed", result={"template_id": template_id})

        except Exception as e:
            sys.stdout = sys.__stdout__  # safety restore
            print(f"Task {task_id} failed: {e}")
            task_manager.update_task_status(task_id, "failed", error=str(e))
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)


generation_service = GenerationService()
