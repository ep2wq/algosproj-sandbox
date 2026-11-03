import hmac
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import sandbox

MAX_CODE_BYTES = 64 * 1024
MAX_TEST_CASES = 50


def load_env_file(path):
    """Minimal .env reader, so we don't need python-dotenv. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env_file(Path(__file__).resolve().parent.parent / ".env")

# At most this many runs at once (each is a container with 1 CPU and 256 MB); more get 503 at once.
MAX_RUNS = int(os.environ.get("SANDBOX_MAX_RUNS", "4"))
RUN_SLOTS = threading.BoundedSemaphore(MAX_RUNS)
# The API docs (/docs, /redoc, /openapi.json) only with SANDBOX_DOCS=1, for local development.
DOCS = os.environ.get("SANDBOX_DOCS") == "1"
# The only paths without the secret.
PUBLIC_PATHS = {"/health", "/languages"} | ({"/docs", "/redoc", "/openapi.json"} if DOCS else set())


app = FastAPI(
    docs_url="/docs" if DOCS else None,
    redoc_url="/redoc" if DOCS else None,
    openapi_url="/openapi.json" if DOCS else None,
)


class TestCase(BaseModel):
    input: str
    expected_output: str


class RunRequest(BaseModel):
    language: str
    code: str
    test_cases: list[TestCase]


# Middleware, so the secret is checked before the body is read or parsed. Constant-time, on bytes
# (a str compare fails on non-ASCII text); no configured secret rejects everything.
@app.middleware("http")
async def check_secret(request: Request, call_next):
    if request.url.path not in PUBLIC_PATHS:
        expected = os.environ.get("SANDBOX_SECRET", "").encode()
        given = request.headers.get("x-sandbox-secret", "").encode("latin-1")
        if not expected or not given or not hmac.compare_digest(given, expected):
            return JSONResponse({"detail": "Invalid or missing X-Sandbox-Secret"}, status_code=401)
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/languages")
def languages():
    return {"languages": sandbox.LANGUAGES}


# A plain def, so FastAPI runs the blocking Docker calls in its thread pool.
@app.post("/run")
def run(request: RunRequest):
    if request.language not in sandbox.LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {request.language}")
    if len(request.code.encode("utf-8")) > MAX_CODE_BYTES:
        raise HTTPException(status_code=413, detail="Code is larger than 64 KB")
    if len(request.test_cases) > MAX_TEST_CASES:
        raise HTTPException(status_code=413, detail=f"More than {MAX_TEST_CASES} test cases")

    test_cases = [tc.model_dump() for tc in request.test_cases]
    if len(sandbox.encode_submission(request.language, request.code, test_cases)) > sandbox.MAX_PAYLOAD:
        raise HTTPException(status_code=413, detail="Submission (code plus test cases) is too large")

    # No queue: when every slot is busy the caller (the backend) answers "try again shortly".
    if not RUN_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="Sandbox busy", headers={"Retry-After": "5"})
    try:
        return sandbox.run_submission(request.language, request.code, test_cases)
    finally:
        RUN_SLOTS.release()
