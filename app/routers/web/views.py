
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
import shutil
import tempfile
import os

# Use the shared, centralized components
from app.templating import templates
from app.services.web.task_manager import task_manager
from app.services.web.generation_service import generation_service
from app.services.web.template_service import template_service
from app.services.web.preview_service import preview_validator
from app.services.web.submission_service import submission_service

router = APIRouter()

@router.get("/templates", name="list_templates")
async def list_templates(request: Request):
    """Displays the list of all generated templates."""
    template_list = template_service.list_generated_templates()
    return templates.TemplateResponse(
        request=request, 
        name="web/templates_list.html", 
        context={
            "templates": template_list,
            "page_title": "All Templates"
        }
    )

@router.get("/generate", name="generate_new_template_form")
async def generate_new_template_form(request: Request):
    """Shows the form to upload a new CV and LM to generate a template."""
    return templates.TemplateResponse(
        request=request, 
        name="web/generation_form.html", 
        context={
            "page_title": "Generate New Template"
        }
    )

@router.post("/generate", name="start_generation")
async def start_generation(
    background_tasks: BackgroundTasks,
    cv_pdf: UploadFile = File(...),
    lm_pdf: UploadFile = File(None)
):
    """Handles file uploads and starts the background generation task."""
    task_id = task_manager.create_task("template_generation")
    
    temp_dir = tempfile.mkdtemp(prefix="karria_upload_")
    cv_path = os.path.join(temp_dir, cv_pdf.filename)
    with open(cv_path, "wb") as buffer:
        shutil.copyfileobj(cv_pdf.file, buffer)

    lm_path = None
    if lm_pdf and lm_pdf.filename:
        lm_path = os.path.join(temp_dir, lm_pdf.filename)
        with open(lm_path, "wb") as buffer:
            shutil.copyfileobj(lm_pdf.file, buffer)

    background_tasks.add_task(
        generation_service.run_generation_pipeline,
        task_id,
        cv_path,
        lm_path,
        temp_dir
    )
    
    return RedirectResponse(url=f"/web/generate/status/{task_id}", status_code=303)

@router.get("/generate/status/{task_id}", name="generation_status")
async def generation_status(request: Request, task_id: str):
    """Displays the status page, which will poll for updates."""
    task = task_manager.get_task(task_id)
    if not task:
        return HTMLResponse("Task not found", status_code=404)

    return templates.TemplateResponse(
        request=request, 
        name="web/generation_status.html", 
        context={
            "task_id": task_id,
            "task": task
        }
    )

@router.get("/generate/status-update/{task_id}", name="generation_status_update")
async def generation_status_update(request: Request, task_id: str):
    """This endpoint is polled by HTMX to get the latest task status."""
    task = task_manager.get_task(task_id)
    if not task:
        return HTMLResponse("Task not found", status_code=404)

    if task['status'] == 'completed':
        template_id = task['result']['template_id']
        return HTMLResponse(
            f'<div class="text-green-500 font-bold">Redirecting...</div>',
            headers={'HX-Redirect': f'/web/preview/{template_id}'}
        )

    return templates.TemplateResponse(
        request=request, 
        name="web/fragments/status_update.html", 
        context={
            "task": task
        }
    )

@router.get("/preview/{template_id}", name="preview_template")
async def preview_template(request: Request, template_id: str):
    """Displays the side-by-side preview and validation page."""
    details = template_service.get_template_details(template_id)
    if not details:
        return HTMLResponse("Template not found", status_code=404)

    return templates.TemplateResponse(
        request=request, 
        name="web/preview.html", 
        context={
            "template": details,
            "page_title": f"Preview: {template_id}"
        }
    )

@router.get("/preview-render/{template_id}", name="render_template_for_preview")
async def render_template_for_preview(template_id: str):
    """Renders the raw HTML of the template for the iframe preview."""
    from template_generator.preview_renderer import _rebuild_rendered
    from pathlib import Path

    template_dir = Path("outputs") / template_id
    if not template_dir.is_dir():
         return HTMLResponse("HTML file not found for template.", status_code=404)

    rendered_html = _rebuild_rendered(template_dir)
    return HTMLResponse(content=rendered_html)

@router.post("/api/validate-render/{template_id}", name="validate_render")
async def validate_render(request: Request, template_id: str):
    """Runs technical validation and returns the results as an HTMX fragment."""
    validation_results = preview_validator.validate_preview(template_id)
    return templates.TemplateResponse(
        request=request, 
        name="web/fragments/validation_results.html", 
        context={
            "results": validation_results,
            "template_id": template_id
        }
    )

@router.post("/api/submit/{template_id}", name="submit_template")
async def submit_template(template_id: str):
    """Submits the template to the Karria API."""
    try:
        result = await submission_service.submit_template(template_id)
        message = f"Successfully submitted template {template_id}."
        return HTMLResponse(content="", headers={'X-Message': message})
    except Exception as e:
        message = f"Error submitting template: {e}"
        return HTMLResponse(
            content=f"<div class='text-red-500 text-sm mt-2'>{message}</div>",
            status_code=400,
            headers={'X-Message': message}
        )
