# Stickman Studio

Local MVP for turning stickman animation scripts into render-ready scenes.

## Run on Windows

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. The SQLite database is created at `data/stickman.db`.

Current slice: project-isolated image reference uploads, SRT upload, subtitle parsing, optional short-scene merging, time-range scene search, one-second scene marker generation, Google Flow rendering through Playwright/CDP, and a responsive dashboard. Time inputs use `MM:SS`; the search API returns scenes overlapping the requested range.

## Google Flow renderer

1. Close Chrome/Coc Coc instances that are not running with remote debugging.
2. Start Chrome with `--remote-debugging-port=9222`, sign in to Google Flow, and leave the Flow page open.
3. Click `Bắt đầu tạo ảnh` in a project that already has scenes.

Rendered files are saved to `storage/<project_id>/renders/`. If the Flow UI uses different selectors, configure `FLOW_PROMPT_SELECTOR`, `FLOW_SUBMIT_SELECTOR`, and `FLOW_DOWNLOAD_SELECTOR` before starting the server. The default selectors are a textarea, a `Create` button, and a download link.
