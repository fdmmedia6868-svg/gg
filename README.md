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

Use the `Download Midjourney Commands` link on a project to export its scenes to `storage/<project_id>/midjourney_commands.txt`. Set `MIDJOURNEY_CREF_URL` before starting the server to replace the reference-image placeholder in every command.

The app migrates existing SQLite databases automatically. For a clean reset during development, stop the server, remove `data/stickman.db`, and start it again:

```powershell
Remove-Item data/stickman.db
uvicorn app.main:app --reload
```

## Google Flow renderer

1. Close Chrome/Coc Coc instances that are not running with remote debugging.
2. Start Chrome with `--remote-debugging-port=9222`, sign in to Google Flow, and leave the Flow page open. From PowerShell in this project:

```powershell
Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe" -ArgumentList '--remote-debugging-port=9222', '--user-data-dir=".\chrome-flow-profile"'
```

Verify that `http://127.0.0.1:9222/json/version` opens before clicking the render button.
3. Click `Bắt đầu tạo ảnh` in a project that already has scenes.

Rendered files are saved to `storage/<project_id>/renders/`. If the Flow UI uses different selectors, configure `FLOW_PROMPT_SELECTOR`, `FLOW_SUBMIT_SELECTOR`, and `FLOW_DOWNLOAD_SELECTOR` before starting the server. The default selectors are a textarea, a `Create` button, and a download link.
