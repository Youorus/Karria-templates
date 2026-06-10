
import uuid
from typing import Dict, Any, Literal

# This store will live in the main application memory.
# For a real application, this should be replaced with Redis, a database, or another persistent solution.
TASK_DB: Dict[str, Dict[str, Any]] = {}

TaskStatus = Literal["pending", "in_progress", "completed", "failed"]

class TaskManager:
    def create_task(self, task_name: str) -> str:
        """Creates a new task and returns its ID."""
        task_id = str(uuid.uuid4())
        TASK_DB[task_id] = {
            "name": task_name,
            "status": "pending",
            "result": None,
            "error": None
        }
        return task_id

    def get_task(self, task_id: str) -> Dict[str, Any] | None:
        """Retrieves a task's details."""
        return TASK_DB.get(task_id)

    def update_task_status(self, task_id: str, status: TaskStatus, result: Any = None, error: str = None):
        """Updates the status and result of a task."""
        if task_id in TASK_DB:
            TASK_DB[task_id]["status"] = status
            TASK_DB[task_id]["result"] = result
            TASK_DB[task_id]["error"] = error

task_manager = TaskManager()
