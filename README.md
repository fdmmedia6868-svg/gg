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

Current slice: project-isolated image reference uploads, SRT upload, subtitle parsing, optional short-scene merging, time-range scene search, one-second scene marker generation, and a responsive dashboard. Time inputs use `MM:SS`; the search API returns scenes overlapping the requested range. AI prompt generation, rendering adapters, and CapCut export are next modules.
