import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
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

app = FastAPI()


class TestCase(BaseModel):
    input: str
    expected_output: str


class RunRequest(BaseModel):
    language: str
    code: str
    test_cases: list[TestCase]


def check_secret(x_sandbox_secret: str | None = Header(default=None)):
    expected = os.environ.get("SANDBOX_SECRET")
    if not expected or not x_sandbox_secret or not hmac.compare_digest(x_sandbox_secret, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Sandbox-Secret")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/languages")
def languages():
    return {"languages": sandbox.LANGUAGES}


# A plain def, so FastAPI runs the blocking Docker calls in its thread pool.
@app.post("/run", dependencies=[Depends(check_secret)])
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

    return sandbox.run_submission(request.language, request.code, test_cases)
