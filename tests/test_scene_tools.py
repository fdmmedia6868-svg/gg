import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import create_each_second_scenes, parse_clock, search_scenes
from app.models import Project, ScriptScene


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_parse_clock_and_search_overlapping_scenes():
    db = make_session()
    project = Project(project_name="Test")
    db.add(project)
    db.flush()
    db.add_all([
        ScriptScene(project_id=project.id, start_ms=10_000, end_ms=12_000, original_text="A"),
        ScriptScene(project_id=project.id, start_ms=20_000, end_ms=22_000, original_text="B"),
    ])
    db.commit()

    assert parse_clock("01:05") == 65_000
    result = search_scenes(project.id, "00:11", "00:21", db)
    payload = json.loads(result.body)
    assert [scene["original_text"] for scene in payload] == ["A", "B"]


def test_create_each_second_scenes_is_idempotent():
    db = make_session()
    project = Project(project_name="Test")
    db.add(project)
    db.commit()

    create_each_second_scenes(project.id, "00:02", "00:05", db=db, background_tasks=None)
    create_each_second_scenes(project.id, "00:02", "00:05", db=db, background_tasks=None)
    scenes = db.query(ScriptScene).order_by(ScriptScene.start_ms).all()
    assert [(scene.start_ms, scene.end_ms) for scene in scenes] == [
        (2_000, 3_000), (3_000, 4_000), (4_000, 5_000)
    ]
