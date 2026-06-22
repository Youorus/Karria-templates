
from pathlib import Path as FilePath

from fastapi import APIRouter, Request, File, UploadFile, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
import shutil
import tempfile
import os
import asyncio
import json

from app.templating import templates
from app.services.web.task_manager import task_manager
from app.services.web.generation_service import generation_service
from app.services.web.template_service import template_service
from app.services.web.preview_service import preview_validator
from app.services.web.submission_service import submission_service
from app.services.web.test_service import test_service

router = APIRouter()


@router.get("/templates", name="list_templates")
async def list_templates(request: Request):
    template_list = template_service.list_generated_templates()
    return templates.TemplateResponse(
        request=request,
        name="web/templates_list.html",
        context={"templates": template_list, "page_title": "All Templates"},
    )


@router.get("/generate", name="generate_new_template_form")
async def generate_new_template_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="web/generation_form.html",
        context={"page_title": "Generate New Template"},
    )


@router.post("/generate", name="start_generation")
async def start_generation(
    background_tasks: BackgroundTasks,
    cv_pdf: UploadFile = File(...),
    lm_pdf: UploadFile = File(None),
):
    task_id = task_manager.create_task("template_generation")

    temp_dir = tempfile.mkdtemp(prefix="karria_upload_")
    cv_path = os.path.join(temp_dir, cv_pdf.filename)
    with open(cv_path, "wb") as buf:
        shutil.copyfileobj(cv_pdf.file, buf)

    lm_path = None
    if lm_pdf and lm_pdf.filename:
        lm_path = os.path.join(temp_dir, lm_pdf.filename)
        with open(lm_path, "wb") as buf:
            shutil.copyfileobj(lm_pdf.file, buf)

    background_tasks.add_task(
        generation_service.run_generation_pipeline,
        task_id,
        cv_path,
        lm_path,
        temp_dir,
    )

    return RedirectResponse(url=f"/web/generate/status/{task_id}", status_code=303)


@router.get("/generate/status/{task_id}", name="generation_status")
async def generation_status(request: Request, task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        return HTMLResponse("Task not found", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="web/generation_status.html",
        context={"task_id": task_id, "task": task},
    )


@router.get("/generate/status-update/{task_id}", name="generation_status_update")
async def generation_status_update(request: Request, task_id: str):
    """Polled by HTMX. Returns a self-refreshing fragment; shows a completion
    card when done — never issues HX-Redirect."""
    task = task_manager.get_task(task_id)
    if not task:
        return HTMLResponse("Task not found", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="web/fragments/status_update.html",
        context={"task": task, "task_id": task_id},
    )


@router.get("/generate/logs/{task_id}", name="generation_logs")
async def generation_logs(request: Request, task_id: str):
    """Polled by HTMX for live log lines. Self-refreshes until task is done."""
    task = task_manager.get_task(task_id)
    if not task:
        return HTMLResponse("Task not found", status_code=404)
    logs = task_manager.get_logs(task_id)
    is_done = task["status"] in ("completed", "failed")
    return templates.TemplateResponse(
        request=request,
        name="web/fragments/generation_logs.html",
        context={"task_id": task_id, "logs": logs, "is_done": is_done},
    )


@router.get("/preview/{template_id}", name="preview_template")
async def preview_template(request: Request, template_id: str):
    details = template_service.get_template_details(template_id)
    if not details:
        return HTMLResponse("Template not found", status_code=404)
    has_lm = (FilePath("outputs") / template_id / "lm" / "lm_template.html").exists()
    return templates.TemplateResponse(
        request=request,
        name="web/preview.html",
        context={
            "template": details,
            "has_lm": has_lm,
            "page_title": f"Preview: {template_id}",
        },
    )


@router.get("/preview-render/{template_id}", name="render_template_for_preview")
async def render_template_for_preview(template_id: str):
    """Renders the CV template HTML for the iframe preview."""
    from template_generator.preview_renderer import _rebuild_rendered

    template_dir = FilePath("outputs") / template_id
    if not template_dir.is_dir():
        return HTMLResponse("Template not found.", status_code=404)
    rendered_html = _rebuild_rendered(template_dir)
    return HTMLResponse(content=rendered_html)


@router.get("/preview-render/{template_id}/lm", name="render_lm_for_preview")
async def render_lm_for_preview(template_id: str):
    """Renders the cover letter template HTML for the iframe preview."""
    from template_generator.preview_renderer import _rebuild_rendered

    lm_dir = FilePath("outputs") / template_id / "lm"
    if not lm_dir.is_dir():
        return HTMLResponse("Cover letter not found for this template.", status_code=404)
    rendered_html = _rebuild_rendered(lm_dir)
    return HTMLResponse(content=rendered_html)


@router.post("/api/validate-render/{template_id}", name="validate_render")
async def validate_render(request: Request, template_id: str):
    """Runs Playwright-based visual validation (sync API wrapped in thread)."""
    validation_results = await asyncio.to_thread(preview_validator.validate_preview, template_id)
    return templates.TemplateResponse(
        request=request,
        name="web/fragments/validation_results.html",
        context={"results": validation_results, "template_id": template_id},
    )


@router.get("/test/{template_id}", name="test_template")
async def test_template(request: Request, template_id: str):
    details = template_service.get_template_details(template_id)
    if not details:
        return HTMLResponse("Template not found", status_code=404)

    has_lm = test_service.has_lm(template_id)
    cv_data = test_service.get_cv_test_data(template_id)
    lm_data = test_service.get_lm_test_data(template_id) if has_lm else {}

    return templates.TemplateResponse(
        request=request,
        name="web/test.html",
        context={
            "template": details,
            "has_lm": has_lm,
            "cv_data_json": json.dumps(cv_data, ensure_ascii=False, indent=2),
            "lm_data_json": json.dumps(lm_data, ensure_ascii=False, indent=2),
            "page_title": f"Test: {template_id}",
        },
    )


@router.post("/api/test-render/{template_id}", name="test_render")
async def test_render_api(request: Request, template_id: str):
    """Renders the template with custom JSON data and returns raw HTML."""
    try:
        body = await request.json()
        doc_type = body.get("doc_type", "cv")
        data = body.get("data", {})
        if not isinstance(data, dict):
            raise ValueError("data must be a JSON object")
        if doc_type == "lm":
            html = await asyncio.to_thread(test_service.render_lm, template_id, data)
        else:
            html = await asyncio.to_thread(test_service.render_cv, template_id, data)
        return HTMLResponse(content=html)
    except Exception as e:
        return HTMLResponse(
            content=f"<p style='color:red;font-family:monospace;padding:1rem'>Render error: {e}</p>",
            status_code=500,
        )


@router.post("/api/submit/{template_id}", name="submit_template")
async def submit_template(template_id: str):
    try:
        await submission_service.submit_template(template_id)
        message = f"Successfully submitted template {template_id}."
        return HTMLResponse(content="", headers={"X-Message": message})
    except Exception as e:
        message = f"Error submitting template: {e}"
        return HTMLResponse(
            content=f"<div class='text-red-500 text-sm mt-2'>{message}</div>",
            status_code=400,
            headers={"X-Message": message},
        )
