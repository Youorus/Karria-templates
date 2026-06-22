
import uuid
from typing import Dict, Any, Literal

TASK_DB: Dict[str, Dict[str, Any]] = {}

TaskStatus = Literal["pending", "in_progress", "completed", "failed"]


class TaskManager:
    def create_task(self, task_name: str) -> str:
        task_id = str(uuid.uuid4())
        TASK_DB[task_id] = {
            "name": task_name,
            "status": "pending",
            "result": None,
            "error": None,
            "logs": [],
        }
        return task_id

    def get_task(self, task_id: str) -> Dict[str, Any] | None:
        return TASK_DB.get(task_id)

    def update_task_status(self, task_id: str, status: TaskStatus, result: Any = None, error: str = None):
        if task_id in TASK_DB:
            TASK_DB[task_id]["status"] = status
            TASK_DB[task_id]["result"] = result
            TASK_DB[task_id]["error"] = error

    def add_log(self, task_id: str, message: str):
        if task_id in TASK_DB:
            TASK_DB[task_id].setdefault("logs", []).append(message)

    def get_logs(self, task_id: str) -> list:
        return TASK_DB.get(task_id, {}).get("logs", [])


task_manager = TaskManager()
