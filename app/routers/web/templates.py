
import shutil
import tempfile
from pathlib import Path

from fastapi import (
    APIRouter,
    Request,
    Depends,
    UploadFile,
    File,
    HTTPException,
    Form,
    BackgroundTasks,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.web.template_service import template_service, TemplateService
from app.services.web.task_manager import task_manager, TaskManager
from app.services.web.generation_service import generation_service, GenerationService

router = APIRouter(prefix="/web")
templates = Jinja2Templates(directory="templates")

@router.get("/templates", response_class=HTMLResponse, name="list_templates")
async def list_templates(request: Request, t_service: TemplateService = Depends(lambda: template_service)):
    all_templates = t_service.get_all_templates()
    return templates.TemplateResponse("index.html", {"request": request, "templates": all_templates})

@router.get("/generate", response_class=HTMLResponse, name="show_generate_form")
async def show_generate_form(request: Request):
    return templates.TemplateResponse("pages/generate.html", {"request": request})

@router.post("/generate", response_class=HTMLResponse, name="handle_generate_form")
async def handle_generate_form(
    request: Request,
    background_tasks: BackgroundTasks,
    cv_pdf: UploadFile = File(...),
    lm_pdf: UploadFile = File(...),
    tm: TaskManager = Depends(lambda: task_manager),
    g_service: GenerationService = Depends(lambda: generation_service)
):
    
    # Save uploaded files to temporary locations
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as cv_tmp:
        shutil.copyfileobj(cv_pdf.file, cv_tmp)
        cv_pdf_path = Path(cv_tmp.name)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as lm_tmp:
        shutil.copyfileobj(lm_pdf.file, lm_tmp)
        lm_pdf_path = Path(lm_tmp.name)
        
    # Create a new task
    task = tm.create_task()
    
    # Add the generation to background tasks
    background_tasks.add_task(
        g_service.run_generation_in_background,
        task.id,
        cv_pdf_path,
        lm_pdf_path
    )
    
    # Redirect to the status page
    return RedirectResponse(url=router.url_path_for("show_task_status", task_id=task.id), status_code=303)

@router.get("/tasks/{task_id}", response_class=HTMLResponse, name="show_task_status")
async def show_task_status(request: Request, task_id: str, tm: TaskManager = Depends(lambda: task_manager)):
    task = tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return templates.TemplateResponse("pages/status.html", {"request": request, "task": task})

@router.get("/preview/{template_id}", response_class=HTMLResponse, name="show_preview")
async def show_preview(request: Request, template_id: str, t_service: TemplateService = Depends(lambda: template_service)):
    template = t_service.get_template_by_id(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
        
    return templates.TemplateResponse("pages/preview.html", {"request": request, "template": template})
