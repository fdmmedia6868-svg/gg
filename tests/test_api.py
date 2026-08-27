from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app, create_each_second_scenes
from app.models import Project, ScriptScene


def test_project_asset_and_scene_search_are_isolated(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()

    def override_db():
        try:
            yield db
        finally:
            pass

    monkeypatch.setattr("app.main.STORAGE_DIR", Path(tmp_path))
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app, follow_redirects=False)
        first = client.post("/projects", data={"project_name": "First"})
        second = client.post("/projects", data={"project_name": "Second"})
        assert first.status_code == 303
        assert second.status_code == 303
        projects = db.query(Project).order_by(Project.id).all()

        asset = client.post(
            f"/projects/{projects[0].id}/assets",
            data={"tag_name": "@NhanVat", "asset_type": "Character"},
            files={"image_file": ("hero.png", b"fake-image", "image/png")},
        )
        assert asset.status_code == 303
        assert projects[0].assets[0].tag_name == "NhanVat"
        assert projects[1].assets == []

        db.add_all([
            ScriptScene(project_id=projects[0].id, start_ms=10_000, end_ms=12_000, original_text="First scene"),
            ScriptScene(project_id=projects[1].id, start_ms=10_000, end_ms=12_000, original_text="Second scene"),
        ])
        db.commit()
        result = client.get(f"/api/projects/{projects[0].id}/scenes?start=00:11&end=00:12")
        assert result.status_code == 200
        assert [scene["original_text"] for scene in result.json()] == ["First scene"]

        create_each_second_scenes(projects[0].id, "00:02", "00:05", db=db, background_tasks=None)
        assert db.query(ScriptScene).filter(ScriptScene.project_id == projects[0].id).count() == 4
    finally:
        app.dependency_overrides.clear()
        db.close()
