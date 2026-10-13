# algosproj-sandbox

Runs user-submitted code for AlgosProj, a platform for learning data structures and
algorithms. It takes code plus test cases, runs them in a throwaway Docker container, and
returns the results as JSON. Only the Laravel backend (`algosproj-backend`) calls this
service, using a shared secret; it is never exposed to the public internet.

## Stack

Python, FastAPI, Docker SDK for Python.

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The backend also defaults to port 8000, so pass `--port 8001` if you run both locally.

## Environment variables

- `SANDBOX_SECRET` — shared secret; requests must send it in the `X-Sandbox-Secret` header
