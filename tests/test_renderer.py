from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
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
