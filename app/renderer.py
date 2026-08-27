import os
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from .models import Project, ReferenceAsset, RenderResult, SceneStatus, ScriptScene


class GoogleFlowAutomator:
    """Drive an already-authenticated Chromium session over CDP."""

    def __init__(
        self,
        storage_dir: Path,
        cdp_url: str = "http://127.0.0.1:9222",
        prompt_selector: str | None = None,
        submit_selector: str | None = None,
        download_selector: str | None = None,
        playwright_factory: Callable | None = None,
        progress_callback: Callable[[int, int, ScriptScene], None] | None = None,
    ):
        self.storage_dir = storage_dir
        self.cdp_url = cdp_url
        self.prompt_selector = prompt_selector or os.getenv("FLOW_PROMPT_SELECTOR", "textarea")
        self.submit_selector = submit_selector or os.getenv("FLOW_SUBMIT_SELECTOR", "button:has-text('Create')")
        self.download_selector = download_selector or os.getenv("FLOW_DOWNLOAD_SELECTOR", "a[download]")
        self.playwright_factory = playwright_factory
        self.progress_callback = progress_callback

    @staticmethod
    def filename_for(scene: ScriptScene) -> str:
        def format_ms(value: int) -> str:
            total_seconds, millis = divmod(value, 1000)
            minutes, seconds = divmod(total_seconds, 60)
            return f"00_{minutes:02d}_{seconds:02d}_{millis // 10:02d}_scene_{scene.id}.png"

        return format_ms(scene.start_ms)

    @staticmethod
    def prompt_for(scene: ScriptScene) -> str:
        return scene.generated_prompt or (
            "2D flat vector art, stickman animation style, plain background, "
            f"visualize this dialogue: {scene.original_text}. NO FINGERS."
        )

    def render_project(self, project_id: int, db: Session) -> None:
        project = db.get(Project, project_id)
        if not project:
            raise ValueError("Project not found")
        scenes = db.query(ScriptScene).filter(ScriptScene.project_id == project_id).order_by(ScriptScene.start_ms).all()
        render_dir = self.storage_dir / str(project_id) / "renders"
        render_dir.mkdir(parents=True, exist_ok=True)
        project.generation_status = "Rendering"
        project.generation_progress = 0
        db.commit()

        factory = self.playwright_factory
        if factory is None:
            from playwright.sync_api import sync_playwright
            factory = sync_playwright
        with factory() as playwright:
            browser = playwright.chromium.connect_over_cdp(self.cdp_url)
            if not browser.contexts:
                raise RuntimeError("No browser context found at the CDP endpoint")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            for index, scene in enumerate(scenes, start=1):
                try:
                    scene.status = SceneStatus.RENDERING.value
                    db.commit()
                    output_path = self.render_scene(page, scene, project.assets, render_dir)
                    create_render_result(project_id, scene.id, output_path, db)
                    scene.status = SceneStatus.RENDERED.value
                except Exception:
                    scene.status = SceneStatus.FAILED.value
                    db.commit()
                    raise
                project.generation_progress = round(index / len(scenes) * 100) if scenes else 100
                project.generation_current = f"{scene.start_ms // 60000:02d}:{scene.start_ms // 1000 % 60:02d}"
                db.commit()
                if self.progress_callback:
                    self.progress_callback(index, len(scenes), scene)
            project.generation_status = "Done"
            project.generation_progress = 100
            db.commit()

    def render_scene(self, page, scene: ScriptScene, assets: list[ReferenceAsset], render_dir: Path) -> Path:
        page.locator(self.prompt_selector).fill(self.prompt_for(scene))
        for asset in assets:
            if f"@{asset.tag_name}" in self.prompt_for(scene):
                file_input = page.locator("input[type=file]").first
                file_input.set_input_files(asset.image_path)
        with page.expect_download(timeout=180_000) as download_info:
            page.locator(self.submit_selector).click()
        download = download_info.value
        output_path = render_dir / self.filename_for(scene)
        download.save_as(str(output_path))
        return output_path


def create_render_result(project_id: int, scene_id: int, output_path: Path, db: Session) -> RenderResult:
    scene = db.get(ScriptScene, scene_id)
    if not scene or scene.project_id != project_id:
        raise ValueError("Scene does not belong to project")
    result = RenderResult(scene_id=scene_id, output_image_path=str(output_path))
    db.add(result)
    db.commit()
    return result
