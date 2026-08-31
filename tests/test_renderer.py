from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app import main as main_module
from app.main import app
from app.models import Project, ScriptScene
from app.renderer import GoogleFlowAutomator, create_render_result


def test_renderer_naming_prompt_and_result_record(tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    project = Project(project_name="Render test")
    db.add(project)
    db.flush()
    scene = ScriptScene(project_id=project.id, start_ms=15_200, end_ms=20_000, original_text="Hello")
    db.add(scene)
    db.commit()

    automator = GoogleFlowAutomator(tmp_path)
    assert automator.filename_for(scene) == "00_00_15_20_scene_1.png"
    assert "NO FINGERS" in automator.prompt_for(scene)
    result = create_render_result(project.id, scene.id, Path(tmp_path) / "output.png", db)
    assert result.output_image_path.endswith("output.png")
    assert scene.renders[0].id == result.id
    db.close()


def test_start_render_requires_scenes():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    project = Project(project_name="Empty")
    db.add(project)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app, follow_redirects=False).post(f"/projects/{project.id}/start-render")
        assert response.status_code == 400
        assert response.json()["detail"] == "Project has no scenes"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_export_prompts_writes_download_file(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    project = Project(project_name="Export test")
    db.add(project)
    db.flush()
    db.add(ScriptScene(
        project_id=project.id,
        start_ms=1_000,
        end_ms=2_500,
        original_text="Hello",
        generated_prompt="Flat stickman scene",
    ))
    db.commit()

    def override_db():
        yield db

    monkeypatch.setattr(main_module, "STORAGE_DIR", tmp_path)
    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get(f"/projects/{project.id}/export-prompts")
        assert response.status_code == 200
        assert response.headers["content-disposition"].endswith('filename="midjourney_commands.txt"')
        assert response.text == (
            "--- [00:01 - 00:02] Scene 1 ---\n"
            "/imagine prompt: Flat stickman scene --cref <URL_ANH_THAM_CHIEU_CUA_BAN> --cw 100 --ar 16:9\n\n"
        )
        assert (tmp_path / str(project.id) / "midjourney_commands.txt").read_text(encoding="utf-8") == response.text
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_scene_update_and_exports_respect_reference_toggle(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    project = Project(project_name="Overrides")
    db.add(project)
    db.flush()
    scene = ScriptScene(project_id=project.id, start_ms=20_000, end_ms=25_000, original_text="Meeting")
    db.add(scene)
    db.commit()

    def override_db():
        yield db

    monkeypatch.setattr(main_module, "STORAGE_DIR", tmp_path)
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            f"/api/scenes/{scene.id}/update",
            json={
                "image_prompt": "Dark luxury lounge table",
                "video_prompt": "Extremely slow push-in camera",
                "use_cref": False,
                "reference_url": "https://example.com/ref.png",
            },
        )
        assert response.status_code == 200
        assert scene.generated_prompt == "Dark luxury lounge table"
        assert scene.video_prompt == "Extremely slow push-in camera"
        assert scene.use_cref is False

        image_export = client.get(f"/projects/{project.id}/export-prompts")
        assert "--cref" not in image_export.text
        video_export = client.get(f"/projects/{project.id}/export-video-commands")
        assert video_export.status_code == 200
        assert "Extremely slow push-in camera" in video_export.text
        assert "video_commands.txt" in video_export.headers["content-disposition"]
    finally:
        app.dependency_overrides.clear()
        db.close()
