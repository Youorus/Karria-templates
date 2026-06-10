
from pathlib import Path

from fastapi import (
    APIRouter,
    Request,
    Depends,
    HTTPException,
    Response
)
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates

from app.services.web.task_manager import task_manager, TaskManager
from app.services.web.generation_service import generation_service, GenerationService

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/tasks/{task_id}/status", response_class=HTMLResponse, name="get_task_status")
async def get_task_status(
    request: Request,
    response: Response,
    task_id: str,
    tm: TaskManager = Depends(lambda: task_manager)
):
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task.status == "completed":
        # Use HTMX header to trigger a client-side redirect
        redirect_url = request.url_for("show_preview", template_id=task.result)
        response.headers["HX-Redirect"] = redirect_url

    return templates.TemplateResponse("fragments/task_status.html", {"request": request, "task": task})

@router.post("/validate-render/{template_id}", response_class=HTMLResponse, name="run_validation")
async def run_validation(
    request: Request, 
    template_id: str,
    g_service: GenerationService = Depends(lambda: generation_service)
):
    try:
        results = await g_service.run_preview_and_validation(template_id)
        # Convert dictionary to a Pydantic-like object for template compatibility
        class AttrDict(dict):
            __getattr__ = dict.__getitem__
            __setattr__ = dict.__setitem__

        return templates.TemplateResponse("fragments/validation_results.html", {"request": request, "results": AttrDict(results)})
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    except Exception as e:
         # Handle potential errors during validation
        return HTMLResponse(f'<div class="p-4 bg-red-100 text-red-700 rounded-md">Error during validation: {e}</div>')


@router.get("/templates/{template_id}/files/{filename}", name="get_template_file")
async def get_template_file(template_id: str, filename: str):
    file_path = Path("outputs") / template_id / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)
