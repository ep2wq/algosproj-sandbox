"""Runs a submission in a throwaway algosproj-runner container and builds the API response."""
import base64
import json
import time
import uuid

import docker
import requests

IMAGE = "algosproj-runner"
LANGUAGES = ["python", "java", "javascript", "cpp"]
WALL_TIMEOUT = 40  # seconds for the whole container, compile included
MAX_OUTPUT = 64 * 1024  # bytes of container output we read
# The payload travels in an environment variable, and Linux caps a single one at 128 KiB.
MAX_PAYLOAD = 120 * 1024

_client = None


def client():
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def encode_submission(language, code, test_cases):
    payload = {"language": language, "code": code, "test_cases": test_cases}
    return base64.b64encode(json.dumps(payload).encode()).decode()


def run_submission(language, code, test_cases):
    """test_cases is a list of {"input", "expected_output"} dicts."""
    payload = encode_submission(language, code, test_cases)
    started = time.monotonic()
    container = None
    try:
        container = client().containers.create(
            IMAGE,
            name=f"algosproj-run-{uuid.uuid4().hex[:12]}",
            environment={"SUBMISSION": payload, "HOME": "/tmp"},
            network_disabled=True,
            mem_limit="256m",
            memswap_limit="256m",
            pids_limit=64,
            read_only=True,
            # Docker mounts tmpfs noexec by default; compiled binaries run from /tmp.
            tmpfs={"/tmp": "rw,exec,nosuid,nodev,size=64m,mode=1777"},
            user="nobody",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            nano_cpus=1_000_000_000,
        )
        container.start()
        try:
            container.wait(timeout=WALL_TIMEOUT)
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            try:
                container.kill()
            except docker.errors.APIError:
                pass  # it exited on its own in the meantime
            return failure_response(
                test_cases, "timeout", f"Sandbox time limit exceeded ({WALL_TIMEOUT} s)", elapsed_ms(started)
            )

        output = b""
        for chunk in container.logs(stdout=True, stderr=False, stream=True):
            output += chunk
            if len(output) >= MAX_OUTPUT:
                break
        output = output[:MAX_OUTPUT]
    finally:
        if container is not None:
            container.remove(force=True)

    return build_response(output, test_cases, elapsed_ms(started))


def elapsed_ms(started):
    return int((time.monotonic() - started) * 1000)


def failure_response(test_cases, status, message, runtime_ms):
    """A response where the sandbox itself failed, so every test case gets the same error."""
    results = [
        {"passed": False, "actual": "", "expected": tc["expected_output"], "error": message}
        for tc in test_cases
    ]
    return {"status": status, "results": results, "runtime_ms": runtime_ms, "compile_error": None}


def build_response(output, test_cases, wall_ms):
    try:
        data = json.loads(output.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return failure_response(test_cases, "error", "Sandbox produced no valid result", wall_ms)

    if data.get("compile_error") is not None:
        return {"status": "error", "results": [], "runtime_ms": 0, "compile_error": data["compile_error"]}

    runner_results = data["results"]
    results = [
        {"passed": r["passed"], "actual": r["actual"], "expected": tc["expected_output"], "error": r["error"]}
        for r, tc in zip(runner_results, test_cases)
    ]
    if any(r["timed_out"] for r in runner_results):
        status = "timeout"
    elif any(r["error"] is not None for r in runner_results):
        status = "error"  # crashed: runtime error, syntax error in an interpreted language, out of memory
    elif all(r["passed"] for r in runner_results):
        status = "passed"
    else:
        status = "failed"
    return {"status": status, "results": results, "runtime_ms": data["runtime_ms"], "compile_error": None}
