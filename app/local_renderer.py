from html import escape
from pathlib import Path

from playwright.sync_api import sync_playwright

from .database import SessionLocal
from .models import Project, ScriptScene
from .renderer import GoogleFlowAutomator


def render_project_locally(project_id: int) -> int:
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        scenes = (
            db.query(ScriptScene)
            .filter(ScriptScene.project_id == project_id)
            .order_by(ScriptScene.start_ms)
            .all()
        )
        output_dir = Path(__file__).resolve().parent.parent / "storage" / str(project_id) / "renders"
        output_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            browser = playwright.chromium.launch(headless=True, executable_path=chrome_path)
            page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
            for scene in scenes:
                timestamp = f"{scene.start_ms // 60000:02d}:{scene.start_ms // 1000 % 60:02d}"
                text = escape(scene.original_text[:180])
                page.set_content(f"""
                <html><body style="margin:0;background:#f4efe4;font-family:Arial,sans-serif">
                  <main style="height:720px;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#172126">
                    <div style="font-size:24px;letter-spacing:3px;color:#c2573d">SCENE {timestamp}</div>
                    <svg width="260" height="300" viewBox="0 0 260 300" aria-label="stickman">
                      <circle cx="130" cy="58" r="34" fill="none" stroke="#172126" stroke-width="10"/>
                      <path d="M130 92 L130 205 M130 120 L68 170 M130 120 L192 170 M130 205 L76 270 M130 205 L184 270" fill="none" stroke="#172126" stroke-width="10" stroke-linecap="round"/>
                      <circle cx="118" cy="54" r="4" fill="#172126"/><circle cx="142" cy="54" r="4" fill="#172126"/>
                    </svg>
                    <p style="max-width:900px;text-align:center;font-size:28px;line-height:1.3">{text}</p>
                  </main>
                </body></html>
                """)
                output_path = output_dir / GoogleFlowAutomator.filename_for(scene)
                page.screenshot(path=str(output_path), type="png")
            browser.close()
        return len(scenes)
    finally:
        db.close()


if __name__ == "__main__":
    import sys

    print(f"Created {render_project_locally(int(sys.argv[1]))} images")