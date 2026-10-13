# algosproj-sandbox

Python FastAPI service that will run user-submitted code inside Docker containers.
Only the backend calls this service; it is not exposed to the frontend. Right now it is
scaffold only — a single health route, no Docker or code-execution logic yet.

## Running it

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then check http://localhost:8000/health — it returns `{"status": "ok"}`.
