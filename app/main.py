import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import ensure_schema, get_db
from .models import AssetType, Project, ReferenceAsset, SceneStatus, ScriptScene
from .renderer import GoogleFlowAutomator
from .srt_parser import merge_short_subtitles, parse_srt

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(exist_ok=True)

ensure_schema()
app = FastAPI(title="Stickman Studio")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
generation_jobs: dict[str, dict] = {}
generation_jobs_lock = Lock()
MIDJOURNEY_CREF_URL = os.getenv("MIDJOURNEY_CREF_URL", "<URL_ANH_THAM_CHIEU_CUA_BAN>")


class SceneUpdate(BaseModel):
    image_prompt: str = ""
    video_prompt: str = ""
    use_cref: bool = True
    reference_url: str = ""


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse("dashboard.html", {"request": request, "projects": projects})


def format_scene_time(value: int) -> str:
    total_seconds = value // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


@app.get("/projects/{project_id}/export-prompts")
def export_prompts(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    scenes = db.query(ScriptScene).filter(
        ScriptScene.project_id == project_id,
    ).order_by(ScriptScene.start_ms).all()
    lines = []
    for scene in scenes:
        lines.extend([
            f"--- [{format_scene_time(scene.start_ms)} - {format_scene_time(scene.end_ms)}] Scene {scene.id} ---",
            f"/imagine prompt: {GoogleFlowAutomator.prompt_for(scene)}{reference_options_for(scene)} --ar 16:9",
            "",
        ])

    export_path = STORAGE_DIR / str(project_id) / "midjourney_commands.txt"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return FileResponse(
        export_path,
        media_type="text/plain; charset=utf-8",
        filename="midjourney_commands.txt",
    )


def reference_options_for(scene: ScriptScene) -> str:
    if not scene.use_cref:
        return ""
    reference_url = scene.reference_url or MIDJOURNEY_CREF_URL
    return f" --cref {reference_url} --cw 100"


def video_prompt_for(scene: ScriptScene) -> str:
    return scene.video_prompt or "Extremely slow cinematic camera movement. The objects remain perfectly still. Zero morphing, flat 2D style."


@app.post("/api/projects/{project_id}/scenes/{scene_id}")
def update_scene(
    project_id: int,
    scene_id: int,
    generated_prompt: str = Form(""),
    video_prompt: str = Form(""),
    use_reference: bool = Form(False),
    reference_url: str = Form(""),
    db: Session = Depends(get_db),
):
    scene = db.get(ScriptScene, scene_id)
    if not scene or scene.project_id != project_id:
        raise HTTPException(status_code=404, detail="Scene not found")
    scene.generated_prompt = generated_prompt.strip() or None
    scene.video_prompt = video_prompt.strip() or None
    scene.use_cref = use_reference
    scene.reference_url = reference_url.strip() or None
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/api/scenes/{scene_id}/update")
def update_scene_json(scene_id: int, payload: SceneUpdate, db: Session = Depends(get_db)):
    scene = db.get(ScriptScene, scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    scene.generated_prompt = payload.image_prompt.strip() or None
    scene.video_prompt = payload.video_prompt.strip() or None
    scene.use_cref = payload.use_cref
    scene.reference_url = payload.reference_url.strip() or None
    db.commit()
    return {
        "id": scene.id,
        "image_prompt": scene.generated_prompt or "",
        "video_prompt": scene.video_prompt or "",
        "use_cref": scene.use_cref,
        "reference_url": scene.reference_url or "",
    }


@app.get("/projects/{project_id}/export-video-commands")
def export_video_commands(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    scenes = db.query(ScriptScene).filter(
        ScriptScene.project_id == project_id,
    ).order_by(ScriptScene.start_ms).all()
    lines = []
    for scene in scenes:
        lines.extend([
            f"--- [{format_scene_time(scene.start_ms)} - {format_scene_time(scene.end_ms)}] Scene {scene.id} ---",
            video_prompt_for(scene),
            "",
        ])
    export_path = STORAGE_DIR / str(project_id) / "video_commands.txt"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return FileResponse(
        export_path,
        media_type="text/plain; charset=utf-8",
        filename="video_commands.txt",
    )


@app.get("/projects/{project_id}/export-video-prompts")
def export_video_prompts(project_id: int, db: Session = Depends(get_db)):
    return export_video_commands(project_id, db)


@app.post("/projects")
def create_project(project_name: str = Form(...), db: Session = Depends(get_db)):
    project = Project(project_name=project_name.strip())
    db.add(project)
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/projects/{project_id}/assets")
def upload_reference_asset(
    project_id: int,
    tag_name: str = Form(...),
    asset_type: str = Form(AssetType.CHARACTER.value),
    image_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project or not image_file.filename:
        raise HTTPException(status_code=404, detail="Project or file not found")
    if asset_type not in {item.value for item in AssetType}:
        raise HTTPException(status_code=400, detail="Invalid asset type")
    project_dir = STORAGE_DIR / str(project_id) / "assets"
    project_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(image_file.filename).name
    destination = project_dir / safe_name
    destination.write_bytes(image_file.file.read())
    db.add(ReferenceAsset(
        project_id=project_id,
        tag_name=tag_name.strip().lstrip("@"),
        asset_type=asset_type,
        image_path=str(destination),
    ))
    db.commit()
    return RedirectResponse(url="/", status_code=303)


def parse_clock(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("Use MM:SS format")
    minutes, seconds = (int(part) for part in parts)
    if minutes < 0 or not 0 <= seconds <= 59:
        raise ValueError("Invalid time")
    return (minutes * 60 + seconds) * 1000


@app.get("/api/projects/{project_id}/scenes")
def search_scenes(
    project_id: int,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        start_ms = parse_clock(start) if start else 0
        end_ms = parse_clock(end) if end else 24 * 60 * 60 * 1000
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if end_ms < start_ms:
        raise HTTPException(status_code=400, detail="End must be after start")
    scenes = db.query(ScriptScene).filter(
        ScriptScene.project_id == project_id,
        ScriptScene.start_ms < end_ms,
        ScriptScene.end_ms > start_ms,
    ).order_by(ScriptScene.start_ms).all()
    return JSONResponse([
        {
            "id": scene.id,
            "start_ms": scene.start_ms,
            "end_ms": scene.end_ms,
            "original_text": scene.original_text,
            "status": scene.status,
        }
        for scene in scenes
    ])


@app.post("/projects/{project_id}/scenes/each-second")
def create_each_second_scenes(
    project_id: int,
    start: str = Form(...),
    end: str = Form(...),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        start_ms = parse_clock(start)
        end_ms = parse_clock(end)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if end_ms <= start_ms:
        raise HTTPException(status_code=400, detail="End must be after start")
    job_id = str(uuid4())
    total = max(0, (end_ms - start_ms) // 1000)
    project = db.get(Project, project_id)
    project.generation_status = "Pending"
    project.generation_progress = 0
    project.generation_current = start
    db.commit()
    with generation_jobs_lock:
        generation_jobs[job_id] = {"status": "queued", "created": 0, "total": total, "current": start}
    if background_tasks is None:
        create_each_second_scenes_background(job_id, project_id, start_ms, end_ms, db)
    else:
        background_tasks.add_task(create_each_second_scenes_background, job_id, project_id, start_ms, end_ms)
    return RedirectResponse(url=f"/?job_id={job_id}", status_code=303)


def create_each_second_scenes_background(
    job_id: str,
    project_id: int,
    start_ms: int,
    end_ms: int,
    db_override: Session | None = None,
):
    db = db_override or next(get_db())
    owns_db = db_override is None
    try:
        existing = {
            scene.start_ms
            for scene in db.query(ScriptScene).filter(ScriptScene.project_id == project_id).all()
        }
        with generation_jobs_lock:
            generation_jobs[job_id]["status"] = "running"
        project = db.get(Project, project_id)
        project.generation_status = "Running"
        db.commit()
        for timestamp in range(start_ms, end_ms, 1000):
            if timestamp not in existing:
                db.add(ScriptScene(
                    project_id=project_id,
                    start_ms=timestamp,
                    end_ms=min(timestamp + 1000, end_ms),
                    original_text=f"Moc {timestamp // 60000:02d}:{timestamp // 1000 % 60:02d}",
                    status=SceneStatus.PENDING.value,
                ))
                db.commit()
                existing.add(timestamp)
            with generation_jobs_lock:
                processed = generation_jobs[job_id]["created"] + 1
                current = f"{timestamp // 60000:02d}:{timestamp // 1000 % 60:02d}"
                generation_jobs[job_id].update({"created": processed, "current": current})
            project.generation_progress = round(processed / generation_jobs[job_id]["total"] * 100) if generation_jobs[job_id]["total"] else 100
            project.generation_current = current
            db.commit()
        project.generation_status = "Done"
        project.generation_progress = 100
        db.commit()
        with generation_jobs_lock:
            generation_jobs[job_id]["status"] = "completed"
    except Exception as error:
        print(f"CRITICAL ERROR IN JOB: {str(error)}")
        db.rollback()
        project = db.get(Project, project_id)
        if project:
            project.generation_status = "Failed"
            db.commit()
        with generation_jobs_lock:
            generation_jobs[job_id].update({"status": "failed", "current": str(error), "error": str(error)})
    finally:
        if owns_db:
            db.close()


@app.get("/api/jobs/{job_id}")
def generation_status(job_id: str):
    with generation_jobs_lock:
        job = generation_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/projects/{project_id}/start-render")
def start_render(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not db.query(ScriptScene).filter(ScriptScene.project_id == project_id).count():
        raise HTTPException(status_code=400, detail="Project has no scenes")
    job_id = str(uuid4())
    with generation_jobs_lock:
        generation_jobs[job_id] = {"status": "queued", "created": 0, "total": 0, "current": None}
    project.generation_status = "Pending"
    project.generation_progress = 0
    db.commit()
    background_tasks.add_task(render_project_background, job_id, project_id)
    return RedirectResponse(url=f"/?job_id={job_id}", status_code=303)


def render_project_background(job_id: str, project_id: int):
    db = next(get_db())
    try:
        scenes_count = db.query(ScriptScene).filter(ScriptScene.project_id == project_id).count()
        with generation_jobs_lock:
            generation_jobs[job_id]["total"] = scenes_count
        def update_render_progress(index: int, total: int, scene: ScriptScene):
            with generation_jobs_lock:
                generation_jobs[job_id].update({
                    "created": index,
                    "total": total,
                    "current": f"{scene.start_ms // 60000:02d}:{scene.start_ms // 1000 % 60:02d}",
                })

        GoogleFlowAutomator(STORAGE_DIR, progress_callback=update_render_progress).render_project(project_id, db)
        with generation_jobs_lock:
            generation_jobs[job_id].update({"status": "completed", "created": scenes_count})
    except Exception as error:
        print(f"CRITICAL ERROR IN JOB: {str(error)}")
        project = db.get(Project, project_id)
        if project:
            project.generation_status = "Failed"
            db.commit()
        with generation_jobs_lock:
            generation_jobs[job_id].update({"status": "failed", "current": str(error), "error": str(error)})
    finally:
        db.close()


@app.post("/projects/{project_id}/srt")
def upload_srt(
    project_id: int,
    srt_file: UploadFile = File(...),
    merge: bool = Form(False),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project or not srt_file.filename or not srt_file.filename.lower().endswith(".srt"):
        return RedirectResponse(url="/", status_code=303)
    content = (srt_file.file.read()).decode("utf-8-sig")
    subtitles = parse_srt(content)
    if merge:
        subtitles = merge_short_subtitles(subtitles)
    project.scenes.clear()
    for subtitle in subtitles:
        project.scenes.append(ScriptScene(
            start_ms=subtitle.start_ms,
            end_ms=subtitle.end_ms,
            original_text=subtitle.text,
            status=SceneStatus.PENDING.value,
        ))
    db.commit()
    return RedirectResponse(url="/", status_code=303)
