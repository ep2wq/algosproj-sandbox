"""Runs one submission inside the sandbox container.

Reads a base64 JSON payload {"language", "code", "test_cases"} from the SUBMISSION
environment variable, compiles the code if the language needs it, runs it once per test
case and prints exactly one JSON object to stdout:

    {"compile_error": "..."}                                   on a compile failure
    {"compile_error": null, "runtime_ms": int,
     "results": [{"passed", "actual", "error", "timed_out"}]}  otherwise

It must run as PID 1 of the container: after every program run it kills every other
process in the container, which is only safe there.
"""
import base64
import ctypes
import json
import os
import signal
import subprocess
import sys
import time

LANGUAGES = {
    "python": {
        "source": "main.py",
        "compile": None,
        "run": ["python3", "main.py"],
    },
    "java": {
        "source": "Main.java",
        "compile": ["javac", "Main.java"],
        "run": ["java", "-Xmx128m", "-Xss512k", "Main"],
    },
    "javascript": {
        "source": "main.js",
        "compile": None,
        "run": ["node", "main.js"],
    },
    "cpp": {
        "source": "main.cpp",
        "compile": ["g++", "-O2", "-std=c++17", "-o", "main", "main.cpp"],
        "run": ["./main"],
    },
}

WORK_DIR = "/tmp/work"
OUTPUT_DIR = "/tmp/output"
COMPILE_TIMEOUT = 30
TEST_TIMEOUT = 3
MAX_READ = 1024 * 1024  # bytes of program output read back for comparison
MAX_REPORT = 500  # characters of output / error text echoed back per test


def read_capped(path):
    with open(path, "rb") as f:
        return f.read(MAX_READ).decode("utf-8", "replace")


def execute(cmd, stdin_text, timeout):
    """Run cmd in WORK_DIR. Returns (exit code or None on timeout, stdout, stderr)."""
    out_path = os.path.join(OUTPUT_DIR, "stdout")
    err_path = os.path.join(OUTPUT_DIR, "stderr")
    # Output goes to files, not pipes, so a chatty program can't blow up our memory and
    # leftover background processes can't keep a pipe open.
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        proc = subprocess.Popen(
            cmd, cwd=WORK_DIR, stdin=subprocess.PIPE, stdout=out, stderr=err
        )
        try:
            proc.communicate(stdin_text.encode(), timeout=timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            exit_code = None
        finally:
            # Kill everything except ourselves (PID 1), including anything the program
            # forked, then reap the zombies so they don't use up the pids limit.
            try:
                os.kill(-1, signal.SIGKILL)
            except ProcessLookupError:
                pass  # nothing left to kill
            proc.wait()
            while True:
                try:
                    os.wait()
                except ChildProcessError:
                    break
    return exit_code, read_capped(out_path), read_capped(err_path)


def shorten(text, limit):
    """Keep the start and the end: Node puts the error first, Python's traceback puts it last."""
    text = text.strip()
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n...\n" + text[-half:]


def describe_failure(exit_code, stderr):
    if exit_code is None:
        return None
    if exit_code < 0:
        name = signal.Signals(-exit_code).name
        if exit_code == -signal.SIGKILL:
            return f"Killed by {name} (probably out of memory)"
        return f"Killed by {name}"
    if exit_code != 0:
        return shorten(stderr, MAX_REPORT) or f"Exited with code {exit_code}"
    return None


def main():
    if os.getpid() != 1:
        sys.exit("runner.py must run as PID 1 inside the sandbox container")

    submission = json.loads(base64.b64decode(os.environ.pop("SUBMISSION")))
    # Not dumpable: user code (same uid) can't read our /proc/1/environ, which holds the
    # expected outputs, or write to our stdout through /proc/1/fd/1.
    ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE = 4

    language = LANGUAGES[submission["language"]]
    os.makedirs(WORK_DIR)
    os.makedirs(OUTPUT_DIR)
    with open(os.path.join(WORK_DIR, language["source"]), "w", encoding="utf-8") as f:
        f.write(submission["code"])

    if language["compile"]:
        exit_code, stdout, stderr = execute(language["compile"], "", COMPILE_TIMEOUT)
        if exit_code is None:
            print(json.dumps({"compile_error": f"Compilation timed out ({COMPILE_TIMEOUT} s)"}))
            return
        if exit_code != 0:
            message = shorten(stderr + stdout, MAX_REPORT * 4)
            print(json.dumps({"compile_error": message or f"Compiler exited with code {exit_code}"}))
            return

    results = []
    started = time.monotonic()
    for test in submission["test_cases"]:
        exit_code, stdout, stderr = execute(language["run"], test["input"], TEST_TIMEOUT)
        timed_out = exit_code is None
        error = f"Time limit exceeded ({TEST_TIMEOUT} s)" if timed_out else describe_failure(exit_code, stderr)
        actual = stdout.strip()
        results.append(
            {
                "passed": exit_code == 0 and actual == test["expected_output"].strip(),
                "actual": actual[:MAX_REPORT],
                "error": error,
                "timed_out": timed_out,
            }
        )
    runtime_ms = int((time.monotonic() - started) * 1000)

    print(json.dumps({"compile_error": None, "runtime_ms": runtime_ms, "results": results}))


if __name__ == "__main__":
    main()
