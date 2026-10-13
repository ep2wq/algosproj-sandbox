# CLAUDE.md

## Project overview

AlgosProj is an interactive learning platform for data structures and algorithms.
Students read a lesson, watch a visualization, write code in the browser (Python, Java,
JavaScript or C++), and the code is run against test cases. Passing earns points on a leaderboard.
An AI tutor gives hints.

Three separate repos, three separate deployments:

- **algosproj-frontend**: React + TypeScript + Vite + Tailwind v4. Talks only to the backend.
- **algosproj-backend**: Laravel API. Handles auth (Sanctum tokens), lessons, problems,
  submissions, points and the leaderboard. It is the only service that calls the sandbox.
- **algosproj-sandbox**: FastAPI service that runs user code in throwaway Docker containers
  and returns the results. Never exposed to the public internet; the backend calls it with
  a shared secret.

Flow: frontend -> backend -> sandbox. The frontend never calls the sandbox directly.

Points and completions are only awarded after the sandbox grades a submission
server-side. Never trust a score sent by the client.

## This repo

- Stack: Python, FastAPI, Docker SDK for Python. Dependencies are only fastapi, uvicorn,
  docker and pytest.
- Layout: `app/main.py` (API, secret check, request limits), `app/sandbox.py` (container
  settings, maps runner output to the API response), `runner/` (the `algosproj-runner`
  image: `Dockerfile` and `runner.py`), `tests/test_sandbox.py`.
- Each submission runs in its own container, destroyed afterward. Every container must
  have: no network, 256 MB memory with swap equal to memory, a pids limit of 64, one CPU,
  user `nobody` with all capabilities dropped and `no-new-privileges`, and a read-only
  filesystem apart from an exec-enabled 64 MB tmpfs at `/tmp`. Timeouts: 30 s compile,
  3 s per test, 40 s for the whole container.
- One runner image holds every language. `runner.py` has the language table, reads the
  submission from the `SUBMISSION` env var (base64 JSON) and prints exactly one JSON
  object. Its output format is the same for every language, so adding a language means
  adding a row to its table, the package to the Dockerfile and the name to
  `sandbox.LANGUAGES`, without changing the API.

  | Language     | Source file | Compile                               | Run                           |
  |--------------|-------------|---------------------------------------|-------------------------------|
  | `python`     | `main.py`   | none                                  | `python3 main.py`             |
  | `java`       | `Main.java` | `javac Main.java`                     | `java -Xmx128m -Xss512k Main` |
  | `javascript` | `main.js`   | none                                  | `node main.js`                |
  | `cpp`        | `main.cpp`  | `g++ -O2 -std=c++17 -o main main.cpp` | `./main`                      |

- Java submissions must declare `public class Main`; the file is always `Main.java`.
- `runner.py` must stay PID 1 in the container: after each program run it kills every
  other process (`kill(-1)`) and reaps zombies, and it makes itself non-dumpable so user
  code can't read the expected outputs from `/proc/1/environ`.
- Reject any request that doesn't carry the shared secret in the `X-Sandbox-Secret` header.
- Commands:
  - Build the image (again after any change in `runner/`): `docker build -t algosproj-runner runner`
  - Run: `python -m venv venv`, `pip install -r requirements.txt`, copy `.env.example`
    to `.env`, `uvicorn app.main:app --reload --port 8001`
  - Test (needs Docker running and the image built): `python -m pytest tests -v`

## Working rules

- Keep code simple. Don't add abstractions, patterns or dependencies I didn't ask for.
- Don't do extra work beyond the request. If you spot something worth fixing, mention it
  instead of changing it.
- Ask before adding a new dependency.
