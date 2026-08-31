from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class AssetType(StrEnum):
    CHARACTER = "Character"
    BACKGROUND = "Background"
    STYLE = "Style"


class SceneStatus(StrEnum):
    PENDING = "Pending"
    PROMPT_READY = "Prompt_Ready"
    RENDERING = "Rendering"
    RENDERED = "Rendered"
    FAILED = "Failed"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    generation_status: Mapped[str] = mapped_column(String(20), default="Idle", nullable=False)
    generation_progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generation_current: Mapped[str | None] = mapped_column(String(10))
    assets: Mapped[list["ReferenceAsset"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    scenes: Mapped[list["ScriptScene"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ReferenceAsset(Base):
    __tablename__ = "reference_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    tag_name: Mapped[str] = mapped_column(String(100), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(30), nullable=False)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    project: Mapped[Project] = relationship(back_populates="assets")


class ScriptScene(Base):
    __tablename__ = "script_scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_prompt: Mapped[str | None] = mapped_column(Text)
    video_prompt: Mapped[str | None] = mapped_column(Text)
    use_cref: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reference_url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(30), default=SceneStatus.PENDING.value)
    project: Mapped[Project] = relationship(back_populates="scenes")
    renders: Mapped[list["RenderResult"]] = relationship(back_populates="scene", cascade="all, delete-orphan")

    @property
    def use_reference(self) -> bool:
        return self.use_cref

    @use_reference.setter
    def use_reference(self, value: bool):
        self.use_cref = value


class RenderResult(Base):
    __tablename__ = "render_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("script_scenes.id", ondelete="CASCADE"), nullable=False)
    output_image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    render_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    scene: Mapped[ScriptScene] = relationship(back_populates="renders")
