from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import AssetType, Project, ReferenceAsset, SceneStatus, ScriptScene
from .srt_parser import merge_short_subtitles, parse_srt

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(exist_ok=True)

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Stickman Studio")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
generation_jobs: dict[str, dict] = {}
generation_jobs_lock = Lock()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse("dashboard.html", {"request": request, "projects": projects})


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
        image_path=str(destination.relative_to(BASE_DIR)),
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
                generation_jobs[job_id].update({
                    "created": generation_jobs[job_id]["created"] + 1,
                    "current": f"{timestamp // 60000:02d}:{timestamp // 1000 % 60:02d}",
                })
        with generation_jobs_lock:
            generation_jobs[job_id]["status"] = "completed"
    except Exception as error:
        db.rollback()
        with generation_jobs_lock:
            generation_jobs[job_id].update({"status": "failed", "error": str(error)})
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
